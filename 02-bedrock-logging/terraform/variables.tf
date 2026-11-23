variable "region" {
  description = "検証リージョン（東京）"
  type        = string
  default     = "ap-northeast-1"
}

variable "log_group_name" {
  description = "モデル呼び出しログの保存先ロググループ名（新規作成する）"
  type        = string
  default     = "/aws-ai-security-labs/lab02/bedrock-invocations"
}

variable "model_id" {
  description = "呼び出すモデル（Lab 01 と同じ Nova Micro）"
  type        = string
  default     = "amazon.nova-micro-v1:0"
}

variable "profile_prefix" {
  description = "推論プロファイルのプレフィックス（東京起点は apac.）"
  type        = string
  default     = "apac."
}

variable "routing_regions" {
  description = "apac.amazon.nova-micro-v1:0 の振り分け先（Lab 01 で get-inference-profile により確認した値）"
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
  description = "invoker / reader ロールを引き受ける検証者の IAM ロールまたはユーザーの ARN（Lab 01 と同じ値）"
  type        = string

  validation {
    condition     = can(regex("^arn:aws:iam::[0-9]{12}:(user|role)/", var.trusted_principal_arn))
    error_message = "arn:aws:iam::<12桁>:user/... または role/... 形式で指定してください。"
  }
}
