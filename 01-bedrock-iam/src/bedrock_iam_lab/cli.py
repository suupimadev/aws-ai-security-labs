"""実 AWS 検証の CLI。

使い方:
  terraform -chdir=01-bedrock-iam/terraform output -json > docs/results/raw/tf_outputs.json
  python -m bedrock_iam_lab.cli --tf-output docs/results/raw/tf_outputs.json --confirm-real-calls

モデルを実際に呼び出す（課金あり）ため、--confirm-real-calls が無い限り何も実行しない。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import boto3

from .aws_clients import bedrock_client_for_role
from .runner import parse_terraform_outputs, run_all, save_results
from .scenarios import SCENARIOS


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Lab01 Bedrock IAM 検証")
    p.add_argument("--tf-output", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, default=Path("docs/results/raw"))
    p.add_argument("--confirm-real-calls", action="store_true")
    args = p.parse_args(argv)

    if not args.confirm_real_calls:
        print(
            f"実 AWS を呼びます（最大 {len(SCENARIOS)} 回の Converse）。実行するなら "
            "--confirm-real-calls を付けてください。"
        )
        return 2

    cfg = parse_terraform_outputs(json.loads(args.tf_output.read_text()))
    sts = boto3.client("sts", region_name=cfg["region"])

    def client_for_role(role_key: str):
        return bedrock_client_for_role(
            sts, cfg["role_arns"][role_key], f"lab01-{role_key}", cfg["region"]
        )

    results = run_all(
        SCENARIOS,
        client_for_role,
        cfg["allowed_model_id"],
        cfg["denied_model_id"],
        cfg["profile_prefix"],
    )
    for r in results:
        mark = "OK " if r.matched else "NG "
        print(
            f"{mark}{r.scenario_id} {r.role_key:9} {r.model_id:32} "
            f"expected={r.expected} actual={r.actual}"
        )
    for path in save_results(results, args.out_dir):
        print(f"saved: {path}")
    return 0 if all(r.matched for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
