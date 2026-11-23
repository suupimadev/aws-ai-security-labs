"""実 AWS 統合テスト（既定ではスキップ。課金・事前承認が必要）。

実行条件: terraform apply 済み、LAB02_TF_OUTPUT を設定、pytest -m integration で明示実行。
モックでは確認できない「実際のログにどう残るか」をここで検証する。
"""

import os

import pytest
from bedrock_logging_lab import cli

pytestmark = pytest.mark.integration

TF_OUTPUT = os.environ.get("LAB02_TF_OUTPUT")


@pytest.mark.skipif(not TF_OUTPUT, reason="LAB02_TF_OUTPUT が未設定")
def test_呼び出しが両方のログに残りログは読める人を絞れている(tmp_path):
    # assert: 2 回の呼び出しが呼び出しログと CloudTrail の両方で見つかり、
    #         reader は読めて invoker は読めない（cli が 0 を返す）
    assert (
        cli.main(
            ["run", "--tf-output", TF_OUTPUT, "--out-dir", str(tmp_path), "--confirm-real-calls"]
        )
        == 0
    )
