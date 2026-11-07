############################################################
# Lab 01: Bedrock IAM アクセス制御（東京リージョン）
#
# 事前調査で分かった東京(ap-northeast-1)の事実（list-foundation-models で確認）
#   - Nova Micro: 推論プロファイル経由のみ（ON_DEMAND の直接呼び出し不可）
#   - Nova Lite : 直接(ON_DEMAND) と推論プロファイルの両方
#   - apac.amazon.nova-micro-v1:0 は 6 リージョンの基盤モデルへルーティングされる
# → Micro を使うには「プロファイル ARN」+「ルーティング先の基盤モデル ARN」の両方の Allow が必要
#    （公式ドキュメントの要件。partial ロールでその不足時の挙動を実測する）
#
# ロールは 4 種（比較したい IAM の挙動ごとに分ける）
#   allowlist    : プロファイル + ルーティング先基盤モデルを Allow（Micro のみ）
#   profileonly  : プロファイル ARN だけ Allow（基盤モデル Allow が不足した場合の挙動）
#   denylist     : 広く Allow + Nova Lite を明示 Deny（Deny が Allow に勝つか）
#   noperm       : 権限なし（ベースライン）
#
# 既存リソースには触れない。課金リソースなし（課金はモデル呼び出しのみ）。
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

  # 全リソースに検証用タグを付与（棚卸し・削除確認に使う）
  default_tags {
    tags = {
      Project     = "aws-ai-security-labs"
      Lab         = "01-bedrock-iam"
      Environment = "lab"
      ManagedBy   = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id

  # システム定義の推論プロファイル ARN（アカウント ID とソースリージョンを含む）
  allowed_profile_arn = "arn:aws:bedrock:${var.region}:${local.account_id}:inference-profile/${var.profile_prefix}${var.allowed_model_id}"

  # ルーティング先リージョンの基盤モデル ARN（"::" = アカウント ID なし）
  allowed_foundation_model_arns = [
    for r in var.routing_regions :
    "arn:aws:bedrock:${r}::foundation-model/${var.allowed_model_id}"
  ]

  # 拒否モデルは「全リージョンの基盤モデル」を Deny（ルーティング先が変わっても効かせる）
  denied_foundation_model_arn_any_region = "arn:aws:bedrock:*::foundation-model/${var.denied_model_id}"

  # Converse / ConverseStream も InvokeModel / InvokeModelWithResponseStream で認可される
  invoke_actions = [
    "bedrock:InvokeModel",
    "bedrock:InvokeModelWithResponseStream",
  ]
}

# ---------- 信頼ポリシー（誰がロールを引き受けられるか） ----------
data "aws_iam_policy_document" "trust" {
  statement {
    sid     = "AllowLabOperatorToAssume"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = [var.trusted_principal_arn]
    }
  }
}

# ---------- 1) allowlist: Micro のプロファイル + ルーティング先基盤モデル ----------
data "aws_iam_policy_document" "allowlist" {
  statement {
    sid       = "InvokeAllowedModelViaProfile"
    effect    = "Allow"
    actions   = local.invoke_actions
    resources = concat([local.allowed_profile_arn], local.allowed_foundation_model_arns)
  }
}

# ---------- 2) profileonly: プロファイル ARN のみ（意図的に不完全） ----------
data "aws_iam_policy_document" "profileonly" {
  statement {
    sid       = "InvokeProfileArnOnly"
    effect    = "Allow"
    actions   = local.invoke_actions
    resources = [local.allowed_profile_arn]
  }
}

# ---------- 3) denylist: 広い Allow + 明示的 Deny ----------
data "aws_iam_policy_document" "denylist" {
  statement {
    sid     = "BroadAllowForComparison"
    effect  = "Allow"
    actions = local.invoke_actions
    # 比較実験のため意図的に広い。本番ではこの形にしない（README 参照）
    resources = [
      "arn:aws:bedrock:*::foundation-model/*",
      "arn:aws:bedrock:*:${local.account_id}:inference-profile/*",
    ]
  }
  statement {
    sid       = "ExplicitDenyOnDeniedModel"
    effect    = "Deny"
    actions   = local.invoke_actions
    resources = [local.denied_foundation_model_arn_any_region]
  }
}

locals {
  roles = {
    allowlist   = data.aws_iam_policy_document.allowlist.json
    profileonly = data.aws_iam_policy_document.profileonly.json
    denylist    = data.aws_iam_policy_document.denylist.json
    noperm      = null
  }
}

resource "aws_iam_role" "lab" {
  for_each = local.roles

  name                 = "lab01-bedrock-${each.key}"
  description          = "Lab01 Bedrock IAM verification role (${each.key})"
  assume_role_policy   = data.aws_iam_policy_document.trust.json
  max_session_duration = 3600 # 最短(1h)
}

resource "aws_iam_role_policy" "lab" {
  # noperm はポリシーなし
  for_each = { for k, v in local.roles : k => v if v != null }

  name   = "lab01-bedrock-${each.key}-policy"
  role   = aws_iam_role.lab[each.key].id
  policy = each.value
}
