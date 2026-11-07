"""AssumeRole と Bedrock 呼び出しの薄いラッパー（boto3 呼び出しをここに集約する）。"""

from __future__ import annotations

import boto3
from botocore.config import Config

# 検証コストを抑えるため出力トークンを小さく固定する
MAX_OUTPUT_TOKENS = 20
PROMPT = "Reply with the single word: ok"

# リトライは最小限。AccessDenied はリトライ対象外だが、Throttling 時の課金増を避ける
_BOTO_CONFIG = Config(retries={"max_attempts": 2, "mode": "standard"}, read_timeout=30)


def bedrock_client_for_role(sts_client, role_arn: str, session_name: str, region: str):
    """指定ロールを AssumeRole し、そのロール権限の bedrock-runtime クライアントを返す。

    入力: STS クライアント, ロール ARN, セッション名, リージョン
    処理: sts:AssumeRole（有効期限は最短の 900 秒）→ 一時認証情報で新しい Session を作成
    戻り値: bedrock-runtime クライアント
    理由: 長期アクセスキーを使わず一時認証情報だけで「ロールごとの権限差」を検証するため。
    """
    resp = sts_client.assume_role(
        RoleArn=role_arn,
        RoleSessionName=session_name,
        DurationSeconds=900,
    )
    c = resp["Credentials"]
    session = boto3.Session(
        aws_access_key_id=c["AccessKeyId"],
        aws_secret_access_key=c["SecretAccessKey"],
        aws_session_token=c["SessionToken"],
        region_name=region,
    )
    return session.client("bedrock-runtime", config=_BOTO_CONFIG)


def converse(bedrock_client, model_id: str) -> dict:
    """Converse API を 1 回呼ぶ。

    入力: bedrock-runtime クライアント, モデル ID（または推論プロファイル ID）
    処理: 固定の短いプロンプトを送信（maxTokens=20, temperature=0）
    戻り値: Converse のレスポンス（usage にトークン数が入る）
    補足: Converse の認可は bedrock:InvokeModel で行われる（専用 Converse アクションは無い）。
    """
    return bedrock_client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": PROMPT}]}],
        inferenceConfig={"maxTokens": MAX_OUTPUT_TOKENS, "temperature": 0},
    )
