# aws-ai-security-labs

Amazon Bedrock を中心とした AI セキュリティの技術検証リポジトリ。各 Lab を Terraform + Boto3 + pytest で再現可能にし、Qiita 記事として公開する。

> 既存の Bedrock / Docker / Nuxt アプリとは独立。検証用リソースは `Project=aws-ai-security-labs` タグ付きで新規作成のみ行い、本番適用は想定しない。

| Lab | テーマ | 状態 |
|-----|--------|------|
| [01](01-bedrock-iam/) | Bedrock IAM アクセス制御 | 実測完了・記事下書きあり（destroy・公開は承認待ち） |
| [02](02-bedrock-logging/) | CloudTrail / CloudWatch による監査 | 計画のみ |
| [03](03-guardrails-pii/) | Guardrails による PII 保護 | 計画のみ |
| [04](04-prompt-injection/) | Prompt Injection 対策 | 計画のみ |
| [05](05-rag-access-control/) | RAG の部署別アクセス制御 | 計画のみ |

## セットアップ
```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest          # モック単体テスト（AWS 接続なし）
ruff check .
```

## 運用ルール
- AWS リソースの作成・変更・削除、GitHub push、Qiita 公開は事前承認制
- 実際に行っていない検証は成功扱いにしない（モック成功 ≠ 権限制御の実証）
- 攻撃検証は自身の検証環境・架空データのみ
- 認証情報・アカウント ID・tfvars・state はコミットしない
