"""records（ログの検索と要約）と polling（待ち合わせ）の単体テスト。AWS には接続しない。"""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

from bedrock_logging_lab import records
from bedrock_logging_lab.polling import poll

LOG = {
    "schemaType": "ModelInvocationLog",
    "requestId": "req-1",
    "region": "ap-northeast-1",
    "operation": "Converse",
    "modelId": "apac.amazon.nova-micro-v1:0",
    "identity": {"arn": "arn:aws:sts::123456789012:assumed-role/lab02-bedrock-invoker/s"},
    "input": {
        "inputBodyJson": {"messages": [{"content": [{"text": "メール: a@example.com"}]}]},
        "inputTokenCount": 7,
    },
    "output": {"outputBodyJson": {"output": "ok"}, "outputTokenCount": 2},
}


# ---------- 呼び出しログ ----------
def test_呼び出しログをrequestIdのJSONフィルターで探す():
    logs = MagicMock()
    logs.filter_log_events.return_value = {"events": [{"message": json.dumps(LOG)}]}
    found = records.find_invocation_log(logs, "/grp", "req-1")
    kwargs = logs.filter_log_events.call_args.kwargs
    # assert: 指定ロググループを、requestId の JSON フィルターで検索している
    assert kwargs["logGroupName"] == "/grp"
    assert kwargs["filterPattern"] == '{ $.requestId = "req-1" }'
    # assert: 見つかったログを dict に戻して返す
    assert found["requestId"] == "req-1"


def test_呼び出しログがまだ無ければNone():
    logs = MagicMock()
    logs.filter_log_events.return_value = {"events": []}
    # assert: まだ届いていない状態を None で表す（成功扱いしない）
    assert records.find_invocation_log(logs, "/grp", "req-1") is None


def test_呼び出しログの要約は本文を含まない():
    s = records.summarize_invocation_log(LOG)
    # assert: 比較に必要な項目が取り出せる
    assert (s["operation"], s["input_tokens"], s["output_tokens"]) == ("Converse", 7, 2)
    assert s["identity_arn"].endswith("lab02-bedrock-invoker/s")
    # assert: 本文は「あるかどうか」だけを持ち、内容そのものは結果に残さない
    assert s["has_input_body"] is True
    assert "a@example.com" not in json.dumps(s)
    # assert: 該当する項目がない場合は None（推測で埋めない）
    assert s["inference_region"] is None


# ---------- CloudTrail ----------
def _trail_with_pages(pages):
    trail = MagicMock()
    trail.get_paginator.return_value.paginate.return_value = pages
    return trail


def test_CloudTrailは複数ページからrequestIDが一致するイベントを探す():
    other = {"CloudTrailEvent": json.dumps({"requestID": "x", "eventName": "Converse"})}
    hit = {
        "CloudTrailEvent": json.dumps(
            {
                "requestID": "req-1",
                "eventName": "Converse",
                "eventType": "AwsApiCall",
                "managementEvent": True,
                "awsRegion": "ap-northeast-1",
                "userIdentity": {"arn": "arn:aws:sts::123456789012:assumed-role/r/s"},
                "requestParameters": {"modelId": "apac.amazon.nova-micro-v1:0"},
                "additionalEventData": {"inferenceRegion": "ap-southeast-2"},
            }
        )
    }
    trail = _trail_with_pages([{"Events": [other]}, {"Events": [hit]}])
    start = end = datetime(2026, 11, 14, tzinfo=UTC)
    event = records.find_cloudtrail_event(trail, "req-1", start, end)
    kwargs = trail.get_paginator.return_value.paginate.call_args.kwargs
    # assert: Bedrock のイベントだけに絞って検索している（トレイルは使わない）
    assert kwargs["LookupAttributes"][0]["AttributeValue"] == "bedrock.amazonaws.com"
    # assert: 2 ページ目にある一致イベントを見つける
    assert event["requestID"] == "req-1"
    s = records.summarize_cloudtrail_event(event)
    # assert: 処理リージョンがどの階層にあっても拾える / パラメーターはキー名だけ残す
    assert s["inference_region"] == "ap-southeast-2"
    assert s["request_parameter_keys"] == ["modelId"]


def test_CloudTrailに一致がなければNone():
    trail = _trail_with_pages([{"Events": []}])
    t = datetime(2026, 11, 14, tzinfo=UTC)
    # assert: 見つからない状態を None で表す
    assert records.find_cloudtrail_event(trail, "req-1", t, t) is None


# ---------- 共通 ----------
def test_find_keyは入れ子とリストの中も探す():
    # assert: dict の中の list の中の dict まで探せる
    assert records.find_key({"a": [{"b": {"inferenceRegion": "x"}}]}, "inferenceRegion") == "x"
    # assert: なければ None
    assert records.find_key({"a": 1}, "inferenceRegion") is None


def test_contains_textは日本語を含む記録でも判定できる():
    # assert: JSON の中の文字列に、そのまま含まれていれば True
    assert records.contains_text(LOG, "a@example.com") is True
    assert records.contains_text(LOG, "zzz@example.com") is False


# ---------- polling ----------
class FakeClock:
    """sleep した分だけ時間が進む、テスト用の時計。"""

    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def test_pollは見つかった時点で返す():
    c = FakeClock()
    answers = iter([None, None, "found"])
    got = poll(lambda: next(answers), timeout_s=100, interval_s=10, sleep=c.sleep, clock=c.clock)
    # assert: 3 回目で見つかり、その前に 2 回だけ待った
    assert got == "found"
    assert c.sleeps == [10, 10]


def test_pollは時間切れでNoneを返す():
    c = FakeClock()
    got = poll(lambda: None, timeout_s=30, interval_s=10, sleep=c.sleep, clock=c.clock)
    # assert: 上限を超えて待ち続けない（30 秒以内に収まる）
    assert got is None
    assert sum(c.sleeps) <= 30
