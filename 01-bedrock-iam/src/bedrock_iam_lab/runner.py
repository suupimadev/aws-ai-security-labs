"""シナリオ実行と結果保存。AWS クライアントは外から渡す（テストでモック差し替え可能）。"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from botocore.exceptions import ClientError

from .aws_clients import converse
from .classify import Outcome, classify_error
from .scenarios import Scenario, resolve_model_id

# エラーメッセージ内の 12 桁アカウント ID を伏せる（結果を GitHub/記事に載せる前提のため）
_ACCOUNT_ID = re.compile(r"\b\d{12}\b")


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    role_key: str
    model_id: str
    expected: str
    actual: str
    matched: bool  # expected == actual
    purpose: str
    error_code: str
    error_message: str  # アカウント ID はマスク済み
    input_tokens: int
    output_tokens: int


def redact(text: str) -> str:
    return _ACCOUNT_ID.sub("************", text)


def run_scenario(
    scenario: Scenario,
    bedrock_client,
    allowed_model_id: str,
    denied_model_id: str,
    profile_prefix: str,
) -> ScenarioResult:
    """1 シナリオを実行して結果を返す。

    入力: シナリオ定義, そのロール権限の Bedrock クライアント, 許可/拒否モデル ID
    処理: Converse を 1 回呼び、成功なら ALLOWED、ClientError なら classify_error で分類
    戻り値: ScenarioResult（期待値との一致も判定）
    注意: ClientError 以外（ネットワーク断など）は握りつぶさず上位に伝える。
          「拒否された」と誤判定して検証が成功したように見えるのを防ぐため。
    """
    model_id = resolve_model_id(
        scenario.model_ref, allowed_model_id, denied_model_id, profile_prefix
    )
    code = message = ""
    in_tok = out_tok = 0
    try:
        resp = converse(bedrock_client, model_id)
        outcome = Outcome.ALLOWED
        usage = resp.get("usage", {})
        in_tok, out_tok = usage.get("inputTokens", 0), usage.get("outputTokens", 0)
    except ClientError as e:
        outcome = classify_error(e)
        code = e.response.get("Error", {}).get("Code", "")
        message = redact(e.response.get("Error", {}).get("Message", ""))

    return ScenarioResult(
        scenario_id=scenario.id,
        role_key=scenario.role_key,
        model_id=model_id,
        expected=scenario.expected.value,
        actual=outcome.value,
        matched=outcome == scenario.expected,
        purpose=scenario.purpose,
        error_code=code,
        error_message=message,
        input_tokens=in_tok,
        output_tokens=out_tok,
    )


def run_all(
    scenarios: Iterable[Scenario],
    client_for_role: Callable[[str], object],
    allowed_model_id: str,
    denied_model_id: str,
    profile_prefix: str,
) -> list[ScenarioResult]:
    """全シナリオを順番に実行する。ロールごとのクライアントは 1 回だけ作ってキャッシュする。"""
    clients: dict[str, object] = {}
    results = []
    for s in scenarios:
        if s.role_key not in clients:
            clients[s.role_key] = client_for_role(s.role_key)
        results.append(
            run_scenario(s, clients[s.role_key], allowed_model_id, denied_model_id, profile_prefix)
        )
    return results


def save_results(results: list[ScenarioResult], out_dir: Path, stem: str = "lab01") -> list[Path]:
    """結果を JSON と CSV で保存し、書き出したパスを返す。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [asdict(r) for r in results]
    json_path = out_dir / f"{stem}.json"
    csv_path = out_dir / f"{stem}.csv"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["scenario_id"])
        w.writeheader()
        w.writerows(rows)
    return [json_path, csv_path]


def parse_terraform_outputs(raw: Mapping) -> dict:
    """`terraform output -json` の内容から必要な値を取り出して検証する。

    不足キーがあれば ValueError。誤った設定のまま実 AWS を叩かないための入力チェック。
    """
    try:
        role_arns = raw["role_arns"]["value"]
        cfg = {
            "region": raw["region"]["value"],
            "allowed_model_id": raw["allowed_model_id"]["value"],
            "denied_model_id": raw["denied_model_id"]["value"],
            "profile_prefix": raw["profile_prefix"]["value"],
            "role_arns": role_arns,
        }
    except (KeyError, TypeError) as e:
        raise ValueError(f"terraform output の形式が不正です: {e!r}") from e
    missing = {"allowlist", "profileonly", "denylist", "noperm"} - set(role_arns)
    if missing:
        raise ValueError(f"role_arns に不足キーがあります: {sorted(missing)}")
    return cfg
