# Lab 01 検証結果: Bedrock IAM アクセス制御

- 実施日: 2026-11-07
- リージョン: ap-northeast-1（東京）
- 実行方法: Terraform で IAM ロール 4 つを作成 → `bedrock_iam_lab.cli` が各ロールを AssumeRole して Converse を 8 回実行
- アカウント ID は `<ACCOUNT_ID>` に置換済み。生データ（`docs/results/raw/`）は `.gitignore` 済みで非公開

## 1. 事前調査（実環境で確認した事実）

| 項目 | 結果 | 確認方法 |
|---|---|---|
| Nova Micro の東京での提供 | 推論プロファイル経由のみ（`ON_DEMAND` 不可） | `aws bedrock list-foundation-models` |
| Nova Lite の東京での提供 | `ON_DEMAND` と推論プロファイルの両方 | 同上 |
| `apac.amazon.nova-micro-v1:0` の宛先 | ap-northeast-1/2/3, ap-south-1, ap-southeast-1/2 の 6 リージョン | `aws bedrock get-inference-profile` |

## 2. 検証結果（8 シナリオ: 期待どおり 8 / 8）

| ID | ロール | 呼び出し先 | 期待 | 実測 | 拒否されたリソース |
|---|---|---|---|---|---|
| S1 | allowlist | Micro（`apac.` プロファイル） | 成功 | **成功** (入力7/出力2 tokens) | - |
| S2 | allowlist | Lite 直接 | 暗黙 Deny | 暗黙 Deny | `ap-northeast-1::foundation-model/amazon.nova-lite-v1:0` |
| S3 | allowlist | Lite（`apac.`） | 暗黙 Deny | 暗黙 Deny | `ap-northeast-1:<ACCOUNT_ID>:inference-profile/apac.amazon.nova-lite-v1:0` |
| S4 | profileonly | Micro（`apac.`） | 暗黙 Deny（仮説） | 暗黙 Deny | **`ap-southeast-2::foundation-model/amazon.nova-micro-v1:0`** |
| S5 | denylist | Micro（`apac.`） | 成功 | **成功** (入力7/出力2 tokens) | - |
| S6 | denylist | Lite 直接 | 明示 Deny | 明示 Deny | `ap-northeast-1::foundation-model/amazon.nova-lite-v1:0` |
| S7 | denylist | Lite（`apac.`） | 明示 Deny（仮説） | 明示 Deny | **`ap-southeast-2::foundation-model/amazon.nova-lite-v1:0`** |
| S8 | noperm | Micro（`apac.`） | 暗黙 Deny | 暗黙 Deny | `ap-northeast-1:<ACCOUNT_ID>:inference-profile/apac.amazon.nova-micro-v1:0` |

エラー文言（実測、アカウント ID 伏せ）:
- 暗黙 Deny: `... is not authorized to perform: bedrock:InvokeModel on resource: <ARN> because no identity-based policy allows the bedrock:InvokeModel action`
- 明示 Deny: `... is not authorized to perform: bedrock:InvokeModel on resource: <ARN> with an explicit deny in an identity-based policy`

## 3. 発見（考察の材料）

1. **S4**: プロファイル ARN だけの Allow では呼べない。IAM はプロファイルとは別に、**ルーティング先の基盤モデル ARN** を評価する。拒否ログにはシドニー(`ap-southeast-2`)の ARN が出ており、東京だけ許可しても不足する。
2. **S7**: 明示 Deny はプロファイル経由でも効く。広い Allow（`foundation-model/*`・`inference-profile/*`）があっても、基盤モデルへの Deny が勝つ。Deny を `arn:aws:bedrock:*::foundation-model/...`（全リージョン）にしたため、ルーティング先がどこでも効いた。
3. **S2 と S3**: 同じモデルでも、直接呼び出し（基盤モデル ARN を評価）とプロファイル経由（プロファイル ARN を評価）で拒否対象のリソースが変わる。
4. 拒否されたとき、モデルは実行されず、トークン数は 0（`usage` なし）。
5. `classify.py` の文言判定は実環境のメッセージと一致した。

## 4. 実際に起きた失敗（記録）

- `terraform apply` が 1 回失敗した。IAM ロールの `description` に日本語を入れていたため、`CreateRole` が `ValidationError`（許容文字は `[\u0009\u000A\u000D -~¡-ÿ]*`）。`terraform validate` / `plan` では検出されず、実際の API 呼び出しで初めて判明。ロールは 1 つも作成されず（IAM 一覧で確認）、description を英語にして再実行して成功。

## 5. 未検証・限界

- 実行は各シナリオ 1 回のみ。**ルーティング先は呼び出しごとに変わりうる**ため、S1/S5 の成功が他のリージョンへのルーティングでも成功することの保証にはならない（allowlist は 6 リージョン全てを Allow している）。
- S4 の拒否リージョンが毎回 `ap-southeast-2` になるかは未確認（1 回の観測）。
- 拒否された呼び出しが課金対象外かは未確認（請求データで後日確認が必要）。
- 東京の Nova Micro 単価は公式ページで確認できていない（後述）。
- `bedrock:InferenceProfileArn` 条件キーによる「基盤モデルはプロファイル経由でのみ許可」の絞り込みは**未検証**（公式ドキュメントに例あり）。
- SCP・権限境界・リソースベースポリシー・VPC エンドポイントポリシー・モデルアクセス設定との組み合わせは未検証。
- 統合テスト（`pytest -m integration`）は未実行（CLI で同じ 8 シナリオを実測済みのため）。単体テストは 23 件成功だがモックであり、IAM 制御の証拠は本結果のみ。

## 6. 費用

- 成功呼び出し 2 回（S1, S5）: 各 入力 7 / 出力 2 tokens（実測）。
- 参考単価（AWS 公式ブログ、2025-05 時点、米国東部 Ohio）: Nova Micro 入力 $0.000035 / 出力 $0.00014 per 1,000 tokens → 2 回で約 $0.000001。
- **東京の geo クロスリージョン推論の単価は未確認**（料金ページの表が取得できなかった）。上記は目安。数日後に Cost Explorer で実額を確認する。
- IAM ロール・ポリシーは無料。継続課金リソースなし。

## 7. セキュリティ評価

| リスク | 評価 | 対策 |
|---|---|---|
| 権限過大（`bedrock:*`・`Resource: *`） | 本 Lab の allowlist は 2 アクション + 個別 ARN で最小化。denylist ロールは比較用の広い Allow | 本番では allowlist 方式。denylist は SCP などのガードレールとして併用 |
| 新モデルが自動で使えるようになる | 広い Allow + 個別 Deny 方式で起きる | allowlist 方式を採用 |
| ルーティング先変更への追従漏れ | allowlist は宛先 6 リージョンを固定列挙。AWS 側で増えると新しい宛先で拒否される（安全側に失敗） | 宛先の変更を定期確認 / IaC で変数化 |
| SCP でリージョン制限している組織 | 宛先が制限リージョンに入ると拒否されうる（公式ドキュメントの注意） | 宛先リージョンを SCP で許可 |
| ロールの引き受け範囲 | 信頼ポリシーは検証者の SSO ロール 1 つのみ。セッション 1 時間 | 検証後に `terraform destroy` |
| アカウント ID・ARN の漏洩 | 結果はマスク済み。tfvars/state/raw は `.gitignore` | 公開前に grep で再確認 |
| 拒否ログの扱い | エラー文に ARN・ロール名が含まれる | ログ共有時はマスク |

## 8. 削除方法

```bash
cd 01-bedrock-iam/terraform
AWS_PROFILE=personal terraform destroy
aws iam list-roles --profile personal --query "Roles[?starts_with(RoleName,'lab01-bedrock-')].RoleName"   # [] なら完了
```
（削除は未実施。承認後に実行する）

## 9. 参考（公式）

- [Geographic cross-Region inference（IAM ポリシー要件）](https://docs.aws.amazon.com/bedrock/latest/userguide/geographic-cross-region-inference.html)
- [Supported Regions and models for inference profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html)
- [Amazon Nova Micro モデルカード](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-micro.html)
- [Amazon Bedrock 料金](https://aws.amazon.com/bedrock/pricing/)
