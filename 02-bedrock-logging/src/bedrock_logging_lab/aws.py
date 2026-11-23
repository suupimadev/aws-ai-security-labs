"""AWS 呼び出しの薄いラッパー（boto3 の呼び出しをここに集約する）。"""

from __future__ import annotations

import boto3
from botocore.config import Config

MAX_OUTPUT_TOKENS = 20
_BOTO_CONFIG = Config(retries={"max_attempts": 2, "mode": "standard"}, read_timeout=30)


def client_for_role(sts_client, role_arn: str, session_name: str, region: str, service: str):
    """指定ロールを AssumeRole し、そのロールの権限で動く boto3 クライアントを返す。

    入力: STS クライアント, ロール ARN, セッション名, リージョン, サービス名
    処理: sts:AssumeRole（15 分）→ 一時認証情報で Session を作り、指定サービスのクライアントを作る
    戻り値: boto3 クライアント
    理由: invoker（モデルを呼ぶ）と reader（ログを読む）で権限を分けて検証するため。
    """
    c = sts_client.assume_role(RoleArn=role_arn, RoleSessionName=session_name, DurationSeconds=900)[
        "Credentials"
    ]
    session = boto3.Session(
        aws_access_key_id=c["AccessKeyId"],
        aws_secret_access_key=c["SecretAccessKey"],
        aws_session_token=c["SessionToken"],
        region_name=region,
    )
    return session.client(service, config=_BOTO_CONFIG)


def converse(bedrock_client, model_id: str, prompt: str) -> dict:
    """Converse を 1 回呼び、ログとの突き合わせに必要な値を返す。

    戻り値: {"request_id": ..., "input_tokens": ..., "output_tokens": ...}
    request_id は、呼び出しログと CloudTrail のイベントを探すときの「鍵」になる。
    """
    resp = bedrock_client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": MAX_OUTPUT_TOKENS, "temperature": 0},
    )
    usage = resp.get("usage", {})
    return {
        "request_id": resp["ResponseMetadata"]["RequestId"],
        "input_tokens": usage.get("inputTokens", 0),
        "output_tokens": usage.get("outputTokens", 0),
    }


def logging_config_status(bedrock_control_client) -> str:
    """モデル呼び出しログの設定が、既にあるかを読み取り専用で確認する。

    戻り値: "NONE"（設定なし。Lab を進めてよい） / "EXISTS"（既存の設定あり。中止する）
    理由: 設定はアカウント × リージョンに 1 つで、Terraform は既存の設定を上書きし、
          destroy で削除してしまう。既存の運用を壊さないための事前確認。
    """
    resp = bedrock_control_client.get_model_invocation_logging_configuration()
    return "EXISTS" if resp.get("loggingConfig") else "NONE"
