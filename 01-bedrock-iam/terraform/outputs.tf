output "region" {
  value = var.region
}

# Python 検証コードが `terraform output -json` を読み込んで使う
output "role_arns" {
  description = "検証用ロール ARN（allowlist / profileonly / denylist / noperm）"
  value       = { for k, r in aws_iam_role.lab : k => r.arn }
}

output "allowed_model_id" {
  value = var.allowed_model_id
}

output "denied_model_id" {
  value = var.denied_model_id
}

output "profile_prefix" {
  value = var.profile_prefix
}
