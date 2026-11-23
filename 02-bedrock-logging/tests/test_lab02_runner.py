"""runner / aws / cli の単体テスト（AWS はモック。実 AWS には接続しない）。

重要: ここが通っても「ログにどう残るか」を実証したことにはならない。
      実証は、実 AWS での検証結果だけ。
"""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from bedrock_logging_lab import aws, cli, runner
from botocore.exceptions import ClientError

T0 = datetime(2026, 11, 14, tzinfo=UTC)


def _bedrock(request_id="req-1"):
    b = MagicMock()
    b.converse.return_value = {
        "ResponseMetadata": {"RequestId": request_id},
        "usage": {"inputTokens": 30, "outputTokens": 2},
    }
    return b


def _logs_with(record):
    logs = MagicMock()
    logs.filter_log_events.return_value = {"events": [{"message": json.dumps(record)}]}
    return logs


def _trail_with(event):
    trail = MagicMock()
    trail.get_paginator.return_value.paginate.return_value = [
        {"Events": [{"CloudTrailEvent": json.dumps(event)}]}
    ]
    return trail


def _empty_trail():
    trail = MagicMock()
    trail.get_paginator.return_value.paginate.return_value = [{"Events": []}]
    return trail


# ---------- aws ----------
def test_converseはrequestIdとトークン数を返す():
    b = _bedrock()
    got = aws.converse(b, "apac.amazon.nova-micro-v1:0", "hi")
    kwargs = b.converse.call_args.kwargs
    # assert: 指定のモデル ID と、出力上限（費用を抑える）で呼んでいる
    assert kwargs["modelId"] == "apac.amazon.nova-micro-v1:0"
    assert kwargs["inferenceConfig"]["maxTokens"] == aws.MAX_OUTPUT_TOKENS
    # assert: ログとの突き合わせに使う request_id を返す
    assert got == {"request_id": "req-1", "input_tokens": 30, "output_tokens": 2}


@pytest.mark.parametrize(
    ("resp", "expected"),
    [({}, "NONE"), ({"loggingConfig": {"textDataDeliveryEnabled": True}}, "EXISTS")],
)
def test_既存のログ設定の有無を判定する(resp, expected):
    b = MagicMock()
    b.get_model_invocation_logging_configuration.return_value = resp
    # assert: 設定がなければ NONE（進めてよい）、あれば EXISTS（上書きしないため中止）
    assert aws.logging_config_status(b) == expected


# ---------- run_call ----------
def test_個人情報入りの呼び出しが両方のログで見つかり残り方を判定する():
    pii = runner.FAKE_PII
    log = {
        "requestId": "req-1",
        "operation": "Converse",
        "input": {"inputBodyJson": {"text": f"{pii['email']} {pii['phone']}"}},
    }
    event = {
        "requestID": "req-1",
        "eventName": "Converse",
        "requestParameters": {"modelId": "apac.amazon.nova-micro-v1:0"},
    }
    r = runner.run_call(
        "L2",
        _bedrock(),
        "apac.amazon.nova-micro-v1:0",
        _logs_with(log),
        "/g",
        _trail_with(event),
        timeout_s=0,
        interval_s=1,
        now=lambda: T0,
    )
    # assert: 送ったプロンプトは L2（個人情報入り）
    # assert: 呼び出しログと CloudTrail の両方で、同じ request_id の記録が見つかった
    assert r.invocation_log is not None and r.cloudtrail is not None
    # assert: 呼び出しログには個人情報がそのまま残り、CloudTrail には残っていない
    #         （このモックの想定。実際の残り方は実 AWS で確かめる）
    assert r.pii_in_invocation_log == {"email": True, "phone": True}
    assert r.pii_in_cloudtrail == {"email": False, "phone": False}


def test_CloudTrailが見つからなければNoneのまま成功扱いしない():
    r = runner.run_call(
        "L1",
        _bedrock(),
        "m",
        _logs_with({"requestId": "req-1"}),
        "/g",
        _empty_trail(),
        timeout_s=0,
        interval_s=1,
        now=lambda: T0,
    )
    # assert: 見つからなかった記録は None のまま（推測で埋めない）
    assert r.cloudtrail is None and r.pii_in_cloudtrail == {}


# ---------- 読める人の確認 ----------
def _err(code):
    return ClientError({"Error": {"Code": code, "Message": "m"}}, "FilterLogEvents")


def test_ログを読めるかの判定():
    ok = MagicMock()
    denied = MagicMock()
    denied.filter_log_events.side_effect = _err("AccessDeniedException")
    other = MagicMock()
    other.filter_log_events.side_effect = _err("ThrottlingException")
    # assert: 読めた / 権限で拒否 / 権限以外の失敗、を区別する
    assert runner.try_read_logs(ok, "/g") == "ALLOWED"
    assert runner.try_read_logs(denied, "/g") == "DENIED"
    assert runner.try_read_logs(other, "/g") == "ERROR"


# ---------- 保存と設定 ----------
def test_保存時にアカウントIDと架空の個人情報を伏せる(tmp_path):
    payload = {"arn": "arn:aws:sts::123456789012:assumed-role/r/s", "note": runner.PROMPTS["L2"]}
    text = runner.save_results(payload, tmp_path / "out").read_text()
    # assert: 公開する結果に、アカウント ID と個人情報の値が残らない
    assert "123456789012" not in text
    assert runner.FAKE_PII["email"] not in text and runner.FAKE_PII["phone"] not in text
    assert "[EMAIL]" in text


def test_terraform出力の解析と不足の検出():
    raw = {
        "region": {"value": "ap-northeast-1"},
        "log_group_name": {"value": "/g"},
        "model_ref": {"value": "apac.amazon.nova-micro-v1:0"},
        "role_arns": {"value": {"invoker": "a", "reader": "b"}},
    }
    # assert: 必要な値が取り出せる
    assert runner.parse_terraform_outputs(raw)["log_group_name"] == "/g"
    raw["role_arns"]["value"] = {"invoker": "a"}
    # assert: ロールが足りなければ、実 AWS を呼ぶ前に止める
    with pytest.raises(ValueError):
        runner.parse_terraform_outputs(raw)


# ---------- cli ----------
def test_確認フラグなしでは実行しない(tmp_path):
    # assert: --confirm-real-calls がなければ、AWS を呼ばずに 2 で終わる
    assert cli.main(["run", "--tf-output", str(tmp_path / "x.json")]) == 2


def test_既存のログ設定があればpreflightは中止を返す(monkeypatch):
    fake = MagicMock()
    fake.get_model_invocation_logging_configuration.return_value = {"loggingConfig": {"x": 1}}
    monkeypatch.setattr(cli.boto3, "client", lambda *a, **k: fake)
    # assert: 既存設定があれば 1（中止）を返す
    assert cli.main(["preflight"]) == 1
