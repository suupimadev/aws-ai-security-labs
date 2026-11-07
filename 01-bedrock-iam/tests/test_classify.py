"""classify_error の単体テスト。

目的: 「暗黙 Deny / 明示 Deny / 権限以外のエラー」を取り違えないこと。
      取り違えると Lab の結論（Deny が Allow に勝つ等）が誤って記録される。
注意: ここで確認できるのは“文言の分類ロジック”だけ。IAM が実際に拒否するかは
      実 AWS 統合テストでしか確認できない。
"""

import pytest
from bedrock_iam_lab.classify import Outcome, classify_error
from botocore.exceptions import ClientError


def make_error(code: str, message: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, "Converse")


IMPLICIT = (
    "User: arn:aws:sts::111122223333:assumed-role/x/y is not authorized to perform: "
    "bedrock:InvokeModel on resource: arn:... because no identity-based policy allows "
    "the bedrock:InvokeModel action"
)
EXPLICIT = (
    "User: arn:aws:sts::111122223333:assumed-role/x/y is not authorized to perform: "
    "bedrock:InvokeModel on resource: arn:... with an explicit deny in an identity-based policy"
)


def test_暗黙denyを判別できる():
    # assert: メッセージに「no identity-based policy allows」があれば暗黙 Deny と分類される
    assert classify_error(make_error("AccessDeniedException", IMPLICIT)) == Outcome.DENIED_IMPLICIT


def test_明示denyを判別できる():
    # assert: 「explicit deny」を含むメッセージは明示 Deny と分類される
    assert classify_error(make_error("AccessDeniedException", EXPLICIT)) == Outcome.DENIED_EXPLICIT


def test_大文字小文字が違っても判別できる():
    # assert: 文言の大文字化に影響されない（lower() 比較している）
    assert classify_error(make_error("AccessDeniedException", EXPLICIT.upper())) == (
        Outcome.DENIED_EXPLICIT
    )


def test_拒否だが理由不明はDENIED_OTHER():
    # assert: SCP 等で文言が異なる場合に、勝手に暗黙/明示と断定しない
    assert classify_error(make_error("AccessDeniedException", "denied by SCP")) == (
        Outcome.DENIED_OTHER
    )


@pytest.mark.parametrize(
    "code",
    [
        "ThrottlingException",
        "ValidationException",
        "ResourceNotFoundException",
        "ModelNotReadyException",
    ],
)
def test_権限以外のエラーは拒否扱いにしない(code):
    # assert: 権限以外の失敗は ERROR。拒否として数えると「制御できた」と誤認するため
    assert classify_error(make_error(code, "something")) == Outcome.ERROR
