############################################################
# Lab 02: Bedrock ログ・監査（東京リージョン）
#
# 公式ドキュメントで確認した前提
#   - モデル呼び出しログは「アカウント × リージョン」単位の設定（既定は無効）
#     有効にすると、そのリージョンの全ての呼び出しが記録される
#   - CloudWatch Logs の記録には、プロンプトと応答の本文（100KB まで）が入る
#   - Converse / InvokeModel は CloudTrail の管理イベント（トレイルなしでもイベント履歴に残る）
#
# 設計方針
#   - 既存のログ設定を上書きしない: apply の前に preflight（読み取り専用）で確認し、
#     既に設定があれば中止する（destroy で既存設定を消してしまう事故も防ぐ）
#   - CloudTrail のトレイルは作らない（イベント履歴で確認でき、費用とリソースを増やさない）
#   - ログの保存期間は最短の 1 日。暗号化は CloudWatch Logs の既定の暗号化
#     （KMS のカスタマー管理キーは月額がかかるため、今回は使わない）
#
# 作成するもの
#   - CloudWatch Logs ロググループ（呼び出しログの保存先）
#   - Bedrock がログを書き込むためのロール（サービス用）
#   - モデル呼び出しログの設定（アカウント × 東京）
#   - invoker ロール: モデルを呼ぶ。ログは読めない
#   - reader ロール: ログを読める。モデルは呼べない
############################################################

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = "aws-ai-security-labs"
      Lab         = "02-bedrock-logging"
      Environment = "lab"
      ManagedBy   = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id

  # Lab 01 と同じく、Nova Micro を推論プロファイル経由で呼ぶための許可
  # （プロファイル ARN + 振り分け先の基盤モデル ARN の両方が必要）
  profile_arn = "arn:aws:bedrock:${var.region}:${local.account_id}:inference-profile/${var.profile_prefix}${var.model_id}"
  foundation_model_arns = [
    for r in var.routing_regions :
    "arn:aws:bedrock:${r}::foundation-model/${var.model_id}"
  ]
}

# ---------- ログの保存先 ----------
resource "aws_cloudwatch_log_group" "invocations" {
  name              = var.log_group_name
  retention_in_days = 1 # 最短。プロンプト本文が残るため、長く保存しない
}

# ---------- Bedrock がログを書き込むためのロール ----------
# 信頼ポリシーは公式ドキュメントの形。SourceAccount / SourceArn の条件で、
# 自分のアカウントの Bedrock からの利用に限定する（混乱した代理問題の対策）
data "aws_iam_policy_document" "delivery_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:bedrock:${var.region}:${local.account_id}:*"]
    }
  }
}

data "aws_iam_policy_document" "delivery" {
  statement {
    sid     = "WriteInvocationLogs"
    effect  = "Allow"
    actions = ["logs:CreateLogStream", "logs:PutLogEvents"]
    # 公式ドキュメントの形: このロググループの決まったログストリームだけ
    resources = [
      "${aws_cloudwatch_log_group.invocations.arn}:log-stream:aws/bedrock/modelinvocations",
    ]
  }
}

resource "aws_iam_role" "delivery" {
  name                 = "lab02-bedrock-log-delivery"
  description          = "Lab02 role for Bedrock to deliver invocation logs to CloudWatch Logs"
  assume_role_policy   = data.aws_iam_policy_document.delivery_trust.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy" "delivery" {
  name   = "lab02-bedrock-log-delivery-policy"
  role   = aws_iam_role.delivery.id
  policy = data.aws_iam_policy_document.delivery.json
}

# ---------- モデル呼び出しログの設定（アカウント × リージョン） ----------
# 注意: この設定は 1 アカウント・1 リージョンに 1 つ。既存の設定があると上書きする。
# そのため apply の前に preflight で「設定なし」を確認すること（README 参照）。
resource "aws_bedrock_model_invocation_logging_configuration" "this" {
  logging_config {
    text_data_delivery_enabled      = true # 今回はテキストだけを記録
    image_data_delivery_enabled     = false
    embedding_data_delivery_enabled = false
    # 書かないと有効（true）のまま設定されることを、実環境の destroy の計画で確認した。
    # 記録しないものは、すべて false を明示する
    video_data_delivery_enabled = false

    cloudwatch_config {
      log_group_name = aws_cloudwatch_log_group.invocations.name
      role_arn       = aws_iam_role.delivery.arn
    }
  }

  # ロールの権限が付いてから設定する（Bedrock が設定時にロールを検証するため）
  depends_on = [aws_iam_role_policy.delivery]
}

# ---------- 検証者が引き受けるロール ----------
data "aws_iam_policy_document" "operator_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = [var.trusted_principal_arn]
    }
  }
}

# invoker: モデルは呼べるが、ログは読めない
data "aws_iam_policy_document" "invoker" {
  statement {
    sid       = "InvokeNovaMicroViaProfile"
    effect    = "Allow"
    actions   = ["bedrock:InvokeModel"]
    resources = concat([local.profile_arn], local.foundation_model_arns)
  }
}

# reader: ログは読めるが、モデルは呼べない（ログを読める人を分けて絞る検証用）
data "aws_iam_policy_document" "reader" {
  statement {
    sid       = "ReadInvocationLogsOnly"
    effect    = "Allow"
    actions   = ["logs:FilterLogEvents", "logs:GetLogEvents"]
    resources = ["${aws_cloudwatch_log_group.invocations.arn}:*"]
  }
}

locals {
  operator_roles = {
    invoker = data.aws_iam_policy_document.invoker.json
    reader  = data.aws_iam_policy_document.reader.json
  }
}

resource "aws_iam_role" "operator" {
  for_each = local.operator_roles

  name                 = "lab02-bedrock-${each.key}"
  description          = "Lab02 verification role (${each.key})"
  assume_role_policy   = data.aws_iam_policy_document.operator_trust.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy" "operator" {
  for_each = local.operator_roles

  name   = "lab02-bedrock-${each.key}-policy"
  role   = aws_iam_role.operator[each.key].id
  policy = each.value
}
