"""Bedrock 呼び出し時の例外を「IAM 判定の種類」に分類する。

なぜ分類が必要か:
  AccessDeniedException は「暗黙の Deny（Allow が無い）」と「明示的 Deny」の
  両方で返る。Lab の目的はこの 2 つを区別して観察することなので、
  エラーメッセージの文言から判別する。
  ※ 文言は AWS 側の仕様変更で変わりうる。実 AWS で得た文言を docs/results に残して
    判定ロジックが現行メッセージと合っているかを確認すること。
"""

from __future__ import annotations

from enum import StrEnum

from botocore.exceptions import ClientError


class Outcome(StrEnum):
    ALLOWED = "ALLOWED"  # 呼び出し成功
    DENIED_IMPLICIT = "DENIED_IMPLICIT"  # Allow が無いため拒否
    DENIED_EXPLICIT = "DENIED_EXPLICIT"  # 明示的 Deny により拒否
    DENIED_OTHER = "DENIED_OTHER"  # 拒否だが種別不明（SCP・境界等の可能性）
    ERROR = "ERROR"  # 権限以外の失敗（Throttling・Validation 等）。検証結果としては無効


# IAM の拒否理由として AWS が返す定型文（部分一致で判定）
_EXPLICIT_MARKER = "explicit deny"
_IMPLICIT_MARKER = "no identity-based policy allows"
_DENY_CODES = {"AccessDeniedException", "AccessDenied"}


def classify_error(error: ClientError) -> Outcome:
    """ClientError を Outcome に変換する。

    入力: boto3 が投げた ClientError
    処理: エラーコードが AccessDenied 系か確認 → メッセージ文言で明示/暗黙を判別
    戻り値: Outcome（権限以外のエラーは ERROR）
    """
    code = error.response.get("Error", {}).get("Code", "")
    if code not in _DENY_CODES:
        # Throttling 等を「拒否された」と誤解釈すると検証結果が汚れるため分離する
        return Outcome.ERROR

    message = error.response.get("Error", {}).get("Message", "").lower()
    if _EXPLICIT_MARKER in message:
        return Outcome.DENIED_EXPLICIT
    if _IMPLICIT_MARKER in message:
        return Outcome.DENIED_IMPLICIT
    return Outcome.DENIED_OTHER
