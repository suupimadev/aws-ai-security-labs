"""実 AWS 統合テスト（既定ではスキップ。課金・事前承認が必要）。

実行条件:
  1) terraform apply 済み
  2) LAB01_TF_OUTPUT=<terraform output -json のパス> を設定
  3) pytest -m integration を明示実行

モックでは確認できない「IAM が本当に拒否/許可するか」をここで検証する。
"""

import json
import os
from pathlib import Path

import boto3
import pytest
from bedrock_iam_lab.aws_clients import bedrock_client_for_role
from bedrock_iam_lab.runner import parse_terraform_outputs, run_all
from bedrock_iam_lab.scenarios import SCENARIOS

pytestmark = pytest.mark.integration

TF_OUTPUT = os.environ.get("LAB01_TF_OUTPUT")


@pytest.mark.skipif(not TF_OUTPUT, reason="LAB01_TF_OUTPUT が未設定")
def test_全シナリオが期待どおりのIAM判定になる():
    cfg = parse_terraform_outputs(json.loads(Path(TF_OUTPUT).read_text()))
    sts = boto3.client("sts", region_name=cfg["region"])
    results = run_all(
        SCENARIOS,
        lambda k: bedrock_client_for_role(sts, cfg["role_arns"][k], f"lab01-it-{k}", cfg["region"]),
        cfg["allowed_model_id"],
        cfg["denied_model_id"],
        cfg["profile_prefix"],
    )
    mismatches = [(r.scenario_id, r.expected, r.actual) for r in results if not r.matched]
    # assert: 全シナリオで 実際の判定 == 期待した判定（不一致があれば内容を表示して失敗）
    assert mismatches == []
