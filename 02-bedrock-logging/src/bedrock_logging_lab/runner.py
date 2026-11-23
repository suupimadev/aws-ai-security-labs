"""検証の流れ（呼ぶ → ログを探す → 比べる → 読める人を確かめる）と結果の保存。

AWS のクライアントは外から渡す（テストでは偽物に差し替える）。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from botocore.exceptions import ClientError

from . import aws, records
from .polling import poll

# 架空の個人情報（実在しない値。example.com はドキュメント用に予約されたドメイン）
FAKE_PII = {
    "email": "taro.yamada@example.com",
    "phone": "090-0000-0000",
}

PROMPTS = {
    "L1": "Reply with the single word: ok",
    "L2": (
        "次の問い合わせに ok とだけ返答してください。"
        f"氏名: 山田太郎 / メール: {FAKE_PII['email']} / 電話: {FAKE_PII['phone']}"
    ),
}

_ACCOUNT_ID = re.compile(r"\b\d{12}\b")


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class CallResult:
    """1 回の呼び出しと、その呼び出しがログにどう残ったかの記録。"""

    call_id: str
    request_id: str
    input_tokens: int
    output_tokens: int
    invocation_log: dict | None = None  # 呼び出しログの要約（見つからなければ None）
    cloudtrail: dict | None = None  # CloudTrail の要約（見つからなければ None）
    pii_in_invocation_log: dict = field(default_factory=dict)  # 種類ごとに True/False
    pii_in_cloudtrail: dict = field(default_factory=dict)


def redact(text: str) -> str:
    """12 桁のアカウント ID と、架空の個人情報を伏せる（結果を公開する前提のため）。"""
    text = _ACCOUNT_ID.sub("************", text)
    for kind, value in FAKE_PII.items():
        text = text.replace(value, f"[{kind.upper()}]")
    return text


def run_call(
    call_id: str,
    invoker_bedrock,
    model_ref: str,
    logs_client,
    log_group: str,
    trail_client,
    timeout_s: float,
    interval_s: float,
    now: Callable[[], datetime] = _utcnow,
    sleep: Callable[[float], None] | None = None,
) -> CallResult:
    """1 回呼び出し、呼び出しログと CloudTrail の両方で、その記録を探して比べる。

    処理:
      1. invoker ロールで Converse を呼び、request_id を受け取る
      2. 呼び出しログ（CloudWatch Logs）を request_id で探す（届くまで待つ）
      3. CloudTrail のイベント履歴を request_id で探す（届くまで待つ）
      4. それぞれに、架空の個人情報がそのまま残っているかを調べる
    戻り値: CallResult（見つからなかった記録は None のまま。失敗を成功扱いしない）
    """
    start = now() - timedelta(minutes=5)
    called = aws.converse(invoker_bedrock, model_ref, PROMPTS[call_id])
    result = CallResult(call_id=call_id, **called)

    poll_kwargs: dict = {"timeout_s": timeout_s, "interval_s": interval_s}
    if sleep is not None:
        poll_kwargs["sleep"] = sleep

    log = poll(
        lambda: records.find_invocation_log(logs_client, log_group, result.request_id),
        **poll_kwargs,
    )
    if log is not None:
        result.invocation_log = records.summarize_invocation_log(log)
        result.pii_in_invocation_log = {
            k: records.contains_text(log, v) for k, v in FAKE_PII.items()
        }

    event = poll(
        lambda: records.find_cloudtrail_event(
            trail_client, result.request_id, start, now() + timedelta(minutes=5)
        ),
        **poll_kwargs,
    )
    if event is not None:
        result.cloudtrail = records.summarize_cloudtrail_event(event)
        result.pii_in_cloudtrail = {k: records.contains_text(event, v) for k, v in FAKE_PII.items()}
    return result


def try_read_logs(logs_client, log_group: str) -> str:
    """そのロールでロググループを読めるかを試す。

    戻り値: "ALLOWED" / "DENIED"（AccessDenied 系） / "ERROR"（権限以外の失敗）
    理由: 呼び出しログにはプロンプト本文が残るため、「読める人を絞れているか」を確かめる。
          権限以外の失敗を「拒否された」と数えると、制御できたと誤認するため分ける。
    """
    try:
        logs_client.filter_log_events(logGroupName=log_group, limit=1)
        return "ALLOWED"
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        return "DENIED" if code in {"AccessDeniedException", "AccessDenied"} else "ERROR"


def to_payload(calls: list[CallResult], access: Mapping[str, str]) -> dict:
    return {"calls": [asdict(c) for c in calls], "log_access": dict(access)}


def save_results(payload: dict, out_dir: Path, stem: str = "lab02") -> Path:
    """結果を JSON で保存する。アカウント ID と架空の個人情報は伏せてから書く。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{stem}.json"
    path.write_text(redact(json.dumps(payload, ensure_ascii=False, indent=2)), encoding="utf-8")
    return path


def parse_terraform_outputs(raw: Mapping) -> dict:
    """`terraform output -json` から必要な値を取り出し、足りなければ止める。"""
    try:
        cfg = {
            "region": raw["region"]["value"],
            "log_group_name": raw["log_group_name"]["value"],
            "model_ref": raw["model_ref"]["value"],
            "role_arns": raw["role_arns"]["value"],
        }
    except (KeyError, TypeError) as e:
        raise ValueError(f"terraform output の形式が不正です: {e!r}") from e
    missing = {"invoker", "reader"} - set(cfg["role_arns"])
    if missing:
        raise ValueError(f"role_arns に不足キーがあります: {sorted(missing)}")
    return cfg
