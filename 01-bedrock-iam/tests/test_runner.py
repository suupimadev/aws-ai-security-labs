"""runner / aws_clients / scenarios の単体テスト（AWS はモック。実 AWS には接続しない）。

重要: ここが通っても「IAM で制御できた」ことの証明にはならない。
      モックは“こう返ってきたらコードはこう動く”を確認するだけである。
"""

import csv
import json
from unittest.mock import MagicMock

import pytest
from bedrock_iam_lab import aws_clients
from bedrock_iam_lab.classify import Outcome
from bedrock_iam_lab.runner import (
    parse_terraform_outputs,
    redact,
    run_all,
    run_scenario,
    save_results,
)
from bedrock_iam_lab.scenarios import SCENARIOS, Scenario, resolve_model_id
from botocore.exceptions import ClientError

ALLOWED, DENIED = "amazon.nova-micro-v1:0", "amazon.nova-lite-v1:0"
PFX = "apac."


def denied_error(msg: str) -> ClientError:
    return ClientError({"Error": {"Code": "AccessDeniedException", "Message": msg}}, "Converse")


# ---------- aws_clients ----------
def test_converseのboto3パラメータ():
    client = MagicMock()
    aws_clients.converse(client, ALLOWED)
    kwargs = client.converse.call_args.kwargs
    # assert: 指定モデルで呼ぶ / 出力トークン上限でコストを抑える / 決定的な出力にする
    assert kwargs["modelId"] == ALLOWED
    assert kwargs["inferenceConfig"] == {
        "maxTokens": aws_clients.MAX_OUTPUT_TOKENS,
        "temperature": 0,
    }
    assert kwargs["messages"][0]["role"] == "user"


def test_assumeroleは最短の有効期限を要求する(monkeypatch):
    sts = MagicMock()
    sts.assume_role.return_value = {
        "Credentials": {"AccessKeyId": "AKIAEXAMPLE", "SecretAccessKey": "s", "SessionToken": "t"}
    }
    monkeypatch.setattr(aws_clients.boto3, "Session", MagicMock())
    aws_clients.bedrock_client_for_role(
        sts, "arn:aws:iam::111122223333:role/r", "sess", "us-east-1"
    )
    # assert: 一時認証情報の寿命を 900 秒（STS の最小値）にして露出時間を短くしている
    assert sts.assume_role.call_args.kwargs["DurationSeconds"] == 900


# ---------- scenarios ----------
def test_モデルIDの解決():
    # assert: 許可モデルは常に "apac." 付きのプロファイル ID（東京の Micro は直接呼べないため）、
    #         拒否モデルは直接 ID とプロファイル ID の両経路を持つ
    assert resolve_model_id("allowed_profile", ALLOWED, DENIED, PFX) == PFX + ALLOWED
    assert resolve_model_id("denied_direct", ALLOWED, DENIED, PFX) == DENIED
    assert resolve_model_id("denied_profile", ALLOWED, DENIED, PFX) == PFX + DENIED


def test_未知のmodel_refはエラー():
    with pytest.raises(ValueError):
        resolve_model_id("nope", ALLOWED, DENIED, PFX)


def test_シナリオ数は課金上限内():
    # assert: 実 AWS 呼び出しが意図せず増えていない（費用見積りの前提 = 8 回）
    assert len(SCENARIOS) == 8
    assert len({s.id for s in SCENARIOS}) == 8


# ---------- run_scenario ----------
S_OK = Scenario("T1", "allowlist", "allowed_profile", Outcome.ALLOWED, "t")
S_IMPL = Scenario("T2", "allowlist", "denied_direct", Outcome.DENIED_IMPLICIT, "t")


def test_成功時はALLOWEDとトークン数を記録する(monkeypatch):
    client = MagicMock()
    client.converse.return_value = {"usage": {"inputTokens": 9, "outputTokens": 2}}
    r = run_scenario(S_OK, client, ALLOWED, DENIED, PFX)
    # assert: 成功 → ALLOWED、期待と一致、課金に関わるトークン数が記録される
    assert (r.actual, r.matched, r.input_tokens, r.output_tokens) == ("ALLOWED", True, 9, 2)


def test_拒否時は分類されメッセージのアカウントIDがマスクされる():
    client = MagicMock()
    client.converse.side_effect = denied_error(
        "User: arn:aws:sts::123456789012:assumed-role/x/y no identity-based policy allows"
    )
    r = run_scenario(S_IMPL, client, ALLOWED, DENIED, PFX)
    # assert: 暗黙 Deny と分類 / 期待一致 / 12 桁アカウント ID が結果に残らない
    assert r.actual == "DENIED_IMPLICIT" and r.matched
    assert "123456789012" not in r.error_message


def test_期待と違う結果はmatchedがFalse():
    client = MagicMock()
    client.converse.return_value = {"usage": {}}  # 本来拒否されるはずが成功してしまった想定
    r = run_scenario(S_IMPL, client, ALLOWED, DENIED, PFX)
    # assert: 権限が緩すぎる（拒否されるべきが成功）ケースを検出できる
    assert r.actual == "ALLOWED" and r.matched is False


def test_権限以外のエラーはERRORで一致扱いにならない():
    client = MagicMock()
    client.converse.side_effect = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow down"}}, "Converse"
    )
    r = run_scenario(S_IMPL, client, ALLOWED, DENIED, PFX)
    # assert: スロットリングを「拒否成功」と誤判定しない
    assert r.actual == "ERROR" and r.matched is False


def test_ClientError以外の例外は握りつぶさない():
    client = MagicMock()
    client.converse.side_effect = TimeoutError("net")
    # assert: ネットワーク障害などは例外として上位に伝わる
    with pytest.raises(TimeoutError):
        run_scenario(S_OK, client, ALLOWED, DENIED, PFX)


# ---------- run_all ----------
def test_ロールごとのクライアントは1回だけ作る():
    factory = MagicMock(return_value=MagicMock(converse=MagicMock(return_value={"usage": {}})))
    results = run_all(SCENARIOS, factory, ALLOWED, DENIED, PFX)
    # assert: 8 シナリオ全て実行され、AssumeRole 回数 = ロール数(4)に抑えられる
    assert len(results) == 8
    assert factory.call_count == 4


# ---------- 保存 / 設定解析 ----------
def test_結果をJSONとCSVで保存できる(tmp_path):
    client = MagicMock()
    client.converse.return_value = {"usage": {"inputTokens": 1, "outputTokens": 1}}
    results = [run_scenario(S_OK, client, ALLOWED, DENIED, PFX)]
    paths = save_results(results, tmp_path / "nested")
    # assert: 2 ファイルが作られ、内容が結果と一致する
    assert {p.suffix for p in paths} == {".json", ".csv"}
    assert json.loads(paths[0].read_text())[0]["scenario_id"] == "T1"
    assert next(csv.DictReader(paths[1].open()))["actual"] == "ALLOWED"


def test_terraform出力の解析():
    raw = {
        "region": {"value": "us-east-1"},
        "allowed_model_id": {"value": ALLOWED},
        "denied_model_id": {"value": DENIED},
        "profile_prefix": {"value": PFX},
        "role_arns": {
            "value": {"allowlist": "a", "profileonly": "p", "denylist": "b", "noperm": "c"}
        },
    }
    # assert: 必要な値が取り出される
    assert parse_terraform_outputs(raw)["role_arns"]["noperm"] == "c"


def test_terraform出力にロールが不足していたらエラー():
    raw = {
        "region": {"value": "r"},
        "allowed_model_id": {"value": "a"},
        "denied_model_id": {"value": "d"},
        "role_arns": {"value": {"allowlist": "a"}},
    }
    # assert: 設定不備のまま実 AWS を呼ばない
    with pytest.raises(ValueError):
        parse_terraform_outputs(raw)


def test_redactは12桁数字のみ伏せる():
    # assert: アカウント ID は伏せ、モデル ID 等は残す
    assert redact("acct 123456789012 nova-micro-v1:0") == "acct ************ nova-micro-v1:0"
