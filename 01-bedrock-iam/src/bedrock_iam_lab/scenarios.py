"""検証シナリオ（どのロールで・どのモデルを呼び・何が期待されるか）の定義。"""

from __future__ import annotations

from dataclasses import dataclass

from .classify import Outcome


@dataclass(frozen=True)
class Scenario:
    id: str
    role_key: str  # terraform output の role_arns のキー
    model_ref: str  # "allowed_profile" / "denied_direct" / "denied_profile"
    expected: Outcome
    purpose: str  # 何を確認するシナリオか（結果表に載せる）


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "S1",
        "allowlist",
        "allowed_profile",
        Outcome.ALLOWED,
        "許可モデル(Micro)をプロファイル経由で呼べる（正常系）",
    ),
    Scenario(
        "S2",
        "allowlist",
        "denied_direct",
        Outcome.DENIED_IMPLICIT,
        "Allow に無いモデル(Lite 直接)は暗黙 Deny",
    ),
    Scenario(
        "S3",
        "allowlist",
        "denied_profile",
        Outcome.DENIED_IMPLICIT,
        "Allow に無いモデル(Lite プロファイル)は暗黙 Deny",
    ),
    Scenario(
        "S4",
        "profileonly",
        "allowed_profile",
        Outcome.DENIED_IMPLICIT,
        "プロファイル ARN だけの Allow では不足か（基盤モデル ARN も必要か）※仮説",
    ),
    Scenario(
        "S5", "denylist", "allowed_profile", Outcome.ALLOWED, "広い Allow では Micro を呼べる"
    ),
    Scenario(
        "S6",
        "denylist",
        "denied_direct",
        Outcome.DENIED_EXPLICIT,
        "明示的 Deny は Allow に勝つ（直接呼び出し）",
    ),
    Scenario(
        "S7",
        "denylist",
        "denied_profile",
        Outcome.DENIED_EXPLICIT,
        "プロファイル経由でも基盤モデルへの Deny を回避できないか ※仮説",
    ),
    Scenario(
        "S8",
        "noperm",
        "allowed_profile",
        Outcome.DENIED_IMPLICIT,
        "権限なしロールはベースライン拒否",
    ),
)


def resolve_model_id(
    ref: str, allowed_model_id: str, denied_model_id: str, profile_prefix: str
) -> str:
    """シナリオの model_ref を実際のモデル ID / 推論プロファイル ID に変換する。

    推論プロファイル ID は「地域プレフィックス + 基盤モデル ID」
    （例: apac.amazon.nova-micro-v1:0）。
    東京の Nova Micro は直接呼び出しができないため、許可モデルは常にプロファイル経由にする。
    """
    table = {
        "allowed_profile": profile_prefix + allowed_model_id,
        "denied_direct": denied_model_id,
        "denied_profile": profile_prefix + denied_model_id,
    }
    try:
        return table[ref]
    except KeyError:
        raise ValueError(f"未知の model_ref: {ref}") from None
