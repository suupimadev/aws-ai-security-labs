"""実 AWS 検証の CLI。

使い方:
  # 1. apply の前に、既存のログ設定がないことを確認する（読み取りのみ）
  python -m bedrock_logging_lab.cli preflight --region ap-northeast-1

  # 2. apply の後に、検証を実行する（Converse を 2 回呼ぶ。課金あり）
  terraform -chdir=02-bedrock-logging/terraform output -json \
      > docs/results/raw/lab02_tf_outputs.json
  python -m bedrock_logging_lab.cli run --tf-output docs/results/raw/lab02_tf_outputs.json \
      --confirm-real-calls
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import boto3

from . import aws
from .runner import (
    PROMPTS,
    parse_terraform_outputs,
    run_call,
    save_results,
    to_payload,
    try_read_logs,
)


def cmd_preflight(region: str) -> int:
    """既存のモデル呼び出しログ設定の有無を確認する。設定があれば 1 を返して止める。"""
    status = aws.logging_config_status(boto3.client("bedrock", region_name=region))
    if status == "EXISTS":
        print(
            f"[中止] {region} には既にモデル呼び出しログの設定があります。"
            "Terraform で上書き・削除してしまうため、この Lab は実行しないでください。"
        )
        return 1
    print(f"[OK] {region} にモデル呼び出しログの設定はありません。apply に進めます。")
    return 0


def cmd_run(tf_output: Path, out_dir: Path, timeout_s: float, interval_s: float) -> int:
    cfg = parse_terraform_outputs(json.loads(tf_output.read_text()))
    region, group = cfg["region"], cfg["log_group_name"]
    sts = boto3.client("sts", region_name=region)

    def role_client(role: str, service: str):
        return aws.client_for_role(sts, cfg["role_arns"][role], f"lab02-{role}", region, service)

    invoker_bedrock = role_client("invoker", "bedrock-runtime")
    reader_logs = role_client("reader", "logs")  # ログの検索は reader ロールで行う
    trail = boto3.client("cloudtrail", region_name=region)  # イベント履歴は検証者自身の権限で見る

    calls = []
    for call_id in PROMPTS:
        r = run_call(
            call_id,
            invoker_bedrock,
            cfg["model_ref"],
            reader_logs,
            group,
            trail,
            timeout_s,
            interval_s,
        )
        calls.append(r)
        print(
            f"{call_id}: log={'found' if r.invocation_log else 'NOT FOUND'} "
            f"cloudtrail={'found' if r.cloudtrail else 'NOT FOUND'} "
            f"pii_in_log={r.pii_in_invocation_log} pii_in_trail={r.pii_in_cloudtrail}"
        )

    access = {
        "reader": try_read_logs(reader_logs, group),  # 期待: ALLOWED
        "invoker": try_read_logs(role_client("invoker", "logs"), group),  # 期待: DENIED
    }
    print(f"log access: {access}")
    print(f"saved: {save_results(to_payload(calls, access), out_dir)}")

    ok = all(c.invocation_log and c.cloudtrail for c in calls) and access == {
        "reader": "ALLOWED",
        "invoker": "DENIED",
    }
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Lab02 Bedrock ログ・監査の検証")
    sub = p.add_subparsers(dest="cmd", required=True)

    pre = sub.add_parser("preflight", help="既存のログ設定がないことを確認（読み取りのみ）")
    pre.add_argument("--region", default="ap-northeast-1")

    run = sub.add_parser("run", help="検証を実行（課金あり）")
    run.add_argument("--tf-output", type=Path, required=True)
    run.add_argument("--out-dir", type=Path, default=Path("docs/results/raw"))
    run.add_argument("--timeout", type=float, default=900, help="ログを待つ上限（秒）")
    run.add_argument("--interval", type=float, default=30, help="探し直す間隔（秒）")
    run.add_argument("--confirm-real-calls", action="store_true")

    args = p.parse_args(argv)
    if args.cmd == "preflight":
        return cmd_preflight(args.region)
    if not args.confirm_real_calls:
        print(
            f"実 AWS を呼びます（Converse {len(PROMPTS)} 回）。実行するなら "
            "--confirm-real-calls を付けてください。"
        )
        return 2
    return cmd_run(args.tf_output, args.out_dir, args.timeout, args.interval)


if __name__ == "__main__":
    sys.exit(main())
