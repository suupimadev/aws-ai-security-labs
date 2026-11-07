# Lab 03: Guardrails による PII 保護（計画のみ・未着手）

記事案: 「Amazon Bedrock Guardrailsで個人情報をマスキングしてみた」

## 検証計画
- Guardrails の Terraform 構築、PII フィルター（BLOCK / ANONYMIZE）の設定
- 架空のメール・電話番号等での検出・マスキング確認、通常入力との比較
- 検出漏れ・誤検知の計測、処理時間・コスト測定

着手条件: Lab 02 完了後、ユーザーの指示。
