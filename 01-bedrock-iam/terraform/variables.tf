variable "region" {
  description = "検証リージョン（東京）。Bedrock 呼び出しの起点リージョンでもある"
  type        = string
  default     = "ap-northeast-1"
}

variable "allowed_model_id" {
  description = "許可するモデル ID（最安クラスの Nova Micro。東京では推論プロファイル経由のみ）"
  type        = string
  default     = "amazon.nova-micro-v1:0"
}

variable "denied_model_id" {
  description = "拒否されることを確認するモデル ID（Nova Lite。東京では直接/プロファイル両方で呼べる）"
  type        = string
  default     = "amazon.nova-lite-v1:0"
}

variable "profile_prefix" {
  description = "地域型（geo）推論プロファイルのプレフィックス。東京起点は apac."
  type        = string
  default     = "apac."
}

variable "routing_regions" {
  description = <<-EOT
    apac.amazon.nova-micro-v1:0 のルーティング先リージョン。
    `aws bedrock get-inference-profile --inference-profile-identifier apac.amazon.nova-micro-v1:0`
    で確認した値（2026-11 時点）。AWS 側で変わりうるため実施前に再確認する。
  EOT
  type        = list(string)
  default = [
    "ap-northeast-1",
    "ap-northeast-2",
    "ap-northeast-3",
    "ap-south-1",
    "ap-southeast-1",
    "ap-southeast-2",
  ]
}

variable "trusted_principal_arn" {
  description = <<-EOT
    ロールを AssumeRole できる検証者の IAM ロール/ユーザー ARN。
    SSO の場合は arn:aws:iam::<acct>:role/aws-reserved/sso.amazonaws.com/<region>/AWSReservedSSO_xxx
    （assumed-role のセッション ARN ではない）。アカウント ID を含むため tfvars はコミットしない。
  EOT
  type        = string

  validation {
    condition     = can(regex("^arn:aws:iam::[0-9]{12}:(user|role)/", var.trusted_principal_arn))
    error_message = "arn:aws:iam::<12桁>:user/... または role/... 形式で指定してください。"
  }
}
