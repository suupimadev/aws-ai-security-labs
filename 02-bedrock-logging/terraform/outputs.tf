output "region" {
  value = var.region
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.invocations.name
}

# Python 検証コードが `terraform output -json` を読み込んで使う
output "role_arns" {
  description = "検証用ロール ARN（invoker / reader）"
  value       = { for k, r in aws_iam_role.operator : k => r.arn }
}

output "model_ref" {
  description = "呼び出しに使う推論プロファイル ID"
  value       = "${var.profile_prefix}${var.model_id}"
}
