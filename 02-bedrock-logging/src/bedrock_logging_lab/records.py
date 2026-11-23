"""呼び出しログと CloudTrail のイベントを探し、記事に必要な項目だけを取り出す。"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any


# ---------- モデル呼び出しログ（CloudWatch Logs） ----------
def find_invocation_log(logs_client, log_group: str, request_id: str) -> dict | None:
    """ロググループから、request_id が一致する呼び出しログを 1 件探す。

    処理: FilterLogEvents に JSON のフィルター（$.requestId = "..."）を付けて検索する
    戻り値: ログの JSON（dict）。まだ届いていなければ None
    """
    resp = logs_client.filter_log_events(
        logGroupName=log_group,
        filterPattern=f'{{ $.requestId = "{request_id}" }}',
        limit=5,
    )
    for event in resp.get("events", []):
        return json.loads(event["message"])
    return None


def summarize_invocation_log(record: dict) -> dict:
    """呼び出しログから、比較に使う項目だけを取り出す（本文そのものは返さない）。"""
    return {
        "operation": record.get("operation"),
        "model_id": record.get("modelId"),
        "region": record.get("region"),
        "identity_arn": record.get("identity", {}).get("arn"),
        "input_tokens": record.get("input", {}).get("inputTokenCount"),
        "output_tokens": record.get("output", {}).get("outputTokenCount"),
        "has_input_body": "inputBodyJson" in record.get("input", {}),
        "has_output_body": "outputBodyJson" in record.get("output", {}),
        "inference_region": find_key(record, "inferenceRegion"),
    }


# ---------- CloudTrail（イベント履歴） ----------
def find_cloudtrail_event(
    trail_client, request_id: str, start: datetime, end: datetime
) -> dict | None:
    """イベント履歴から、requestID が一致する Bedrock のイベントを 1 件探す。

    処理: LookupEvents を EventSource=bedrock.amazonaws.com で絞り、ページを順にたどる
    戻り値: CloudTrail イベントの JSON（dict）。まだ届いていなければ None
    理由: トレイルを作らず、無料のイベント履歴だけで確認するため。
    """
    pages = trail_client.get_paginator("lookup_events").paginate(
        LookupAttributes=[
            {"AttributeKey": "EventSource", "AttributeValue": "bedrock.amazonaws.com"}
        ],
        StartTime=start,
        EndTime=end,
    )
    for page in pages:
        for event in page.get("Events", []):
            detail = json.loads(event["CloudTrailEvent"])
            if detail.get("requestID") == request_id:
                return detail
    return None


def summarize_cloudtrail_event(event: dict) -> dict:
    """CloudTrail のイベントから、比較に使う項目だけを取り出す。"""
    return {
        "event_name": event.get("eventName"),
        "event_type": event.get("eventType"),
        "management_event": event.get("managementEvent"),
        "aws_region": event.get("awsRegion"),
        "identity_arn": event.get("userIdentity", {}).get("arn"),
        "request_parameter_keys": sorted((event.get("requestParameters") or {}).keys()),
        "inference_region": find_key(event, "inferenceRegion"),
    }


# ---------- 共通 ----------
def find_key(obj: Any, key: str) -> Any:
    """入れ子の dict / list の中から、最初に見つかった key の値を返す（なければ None）。

    理由: inferenceRegion がどの階層に入るかは、ドキュメントで確定できなかったため。
    """
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        children = obj.values()
    elif isinstance(obj, list):
        children = obj
    else:
        return None
    for child in children:
        found = find_key(child, key)
        if found is not None:
            return found
    return None


def contains_text(obj: Any, needle: str) -> bool:
    """記録の中のどこかに、needle の文字列がそのまま含まれるか。

    理由: 「プロンプトに入れた個人情報が、ログにそのまま残るか」を判定するため。
    """
    return needle in json.dumps(obj, ensure_ascii=False)
