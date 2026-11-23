# Lab 02 検証結果: Bedrock ログ・監査

- 実施日: 2026-11-23
- リージョン: ap-northeast-1（東京）
- 実行方法: Terraform でログ設定・ロググループ・ロール 3 つを作成 → `bedrock_logging_lab.cli run` が invoker ロールで Converse を 2 回呼び、呼び出しログ（CloudWatch Logs）と CloudTrail のイベント履歴を requestId で検索 → `terraform destroy`
- アカウント ID と架空の個人情報は伏せてある。生データ（`docs/results/raw/`）は `.gitignore` 済みで非公開

## 1. 事前確認

| 項目 | 結果 | 確認方法 |
|---|---|---|
| 東京のモデル呼び出しログの設定 | 未設定（apply の直前にも再確認） | `GetModelInvocationLoggingConfiguration`（preflight） |
| CloudWatch Logs の料金（東京） | 取り込み $0.76/GB、保存 $0.033/GB・月 | AWS Pricing API |
| Terraform の計画 | 作成 8・変更 0・削除 0 | `terraform plan` |

## 2. 検証結果（すべて期待どおり）

| ID | 内容 | 結果 |
|---|---|---|
| L1 | 通常のプロンプトで Converse | 呼び出しログと CloudTrail の**両方に、同じ requestId で記録**が見つかった |
| L2 | 架空の個人情報（メール・電話番号）入りのプロンプトで Converse | **呼び出しログにはメールと電話番号がそのまま残った**。CloudTrail には残っていない |
| A1 | reader ロールでログを読む | 読めた（ALLOWED） |
| A2 | invoker ロールでログを読む | 拒否された（DENIED） |
| R1 | 処理されたリージョン | **呼び出しログと CloudTrail の両方に `inferenceRegion` があり、2 回とも `ap-northeast-1`** |

### 2つのログの比較（L1・L2 共通）

| 項目 | 呼び出しログ（CloudWatch Logs） | CloudTrail（イベント履歴） |
|---|---|---|
| 記録の種類 | `operation: Converse` | `eventName: Converse`、`eventType: AwsApiCall`、管理イベント |
| 呼び出したロール | `assumed-role/lab02-bedrock-invoker/...` | 同じ |
| モデル | `apac.amazon.nova-micro-v1:0` | `requestParameters` に `modelId` |
| プロンプト・応答の本文 | **あり**（`inputBodyJson` / `outputBodyJson`） | なし（`requestParameters` は `modelId` と `inferenceConfig` だけ） |
| トークン数 | L1: 入力 7・出力 2 / L2: 入力 52・出力 2 | 記録の要約では確認していない |
| 処理リージョン（`inferenceRegion`） | `ap-northeast-1` | `ap-northeast-1` |

## 3. 発見（考察の材料）

1. **呼び出しログは、プロンプトをそのまま保存する。** 架空のメールと電話番号が、加工されずに残った。ログを読める人は、利用者が AI に送った内容をすべて読める。
2. **CloudTrail は「誰が・どのモデルを」だけ。** 本文は残らないので、監査には使えても、何を送ったかの調査には使えない。逆に、個人情報が漏れる経路にもならない。
3. **ログを読める人は IAM で分けられる。** モデルを呼ぶロールにログの読み取り権限を与えなければ、自分や他人のプロンプトを読めない。
4. **処理リージョンがログで分かる。** 公式ドキュメントでは、呼び出しログに `inferenceRegion` の欄は書かれておらず、CloudTrail もストリーミング完了イベントの例しかなかったが、実際には通常の `Converse` でも両方に記録された。Lab 01 で分からなかった「どこで処理されたか」を、ログで確認できる。
5. **書かなかった設定が有効になっていた。** Terraform でテキスト・画像・埋め込みだけを指定したところ、動画の記録（`video_data_delivery_enabled`）は書かなかったため `true` のまま設定されていた（destroy の計画で判明）。記録しないものは `false` を明示する必要がある（`main.tf` を修正済み。修正後の再 apply は未実施）。

## 4. 未検証・限界

- 実行は各 1 回、計 2 回。2 回とも東京で処理されたため、**東京以外に振り分けられた場合の `inferenceRegion` の値は観測していない**。
- `inferenceRegion` が記録のどの階層にあるかは、要約処理（入れ子を探索）の都合で記録していない。
- 100KB を超える本文、画像・動画の記録、S3 への出力は試していない。
- ログが届くまでの時間は計測していない（最大 15 分待つ設定で、時間内に届いた）。
- CloudTrail の閲覧は検証者自身の権限（AdministratorAccess）で行った。`cloudtrail:LookupEvents` を持つ人の範囲の検証はしていない。
- KMS のカスタマー管理キーによる暗号化は試していない。
- `video_data_delivery_enabled = false` の修正は、実環境での再確認をしていない。

## 5. 費用

- Converse 2 回: 入力 59・出力 4 トークン。Lab 01 で請求額から逆算した東京の単価（入力 $0.000042 / 出力 $0.000168 per 1K tokens）で、約 $0.0000032 の計算。
- CloudWatch Logs: 取り込みは数 KB の見込み（$0.76/GB）。月 5GB の無料枠内の見込み。
- CloudTrail: トレイルを作らず、イベント履歴だけを使った。
- **実際の請求額は未確認**（数日後に Cost Explorer で確認する）。
- 継続課金リソース: なし（destroy で全て削除済み）。

## 6. セキュリティ評価

| リスク | 評価 | 対策 |
|---|---|---|
| プロンプトに含まれた個人情報・機密情報がログに残る | **実測で確認**。メール・電話番号がそのまま残った | ログを読める人を最小限にする。保存期間を短くする。入力前のマスキング（Guardrails は Lab 03 で検証） |
| ログを読める人の範囲 | IAM で分けられることを確認（reader のみ読める） | 利用者のロールにログの読み取り権限を与えない |
| ログ設定がアカウント全体に効く | 有効にすると、そのリージョンの全ての呼び出しが本文ごと記録される | 有効化の影響範囲を関係者に周知。検証では有効な時間を最短にした |
| 既存のログ設定の上書き・削除 | Terraform は既存設定を上書きし、destroy で削除する | apply 前に preflight で既存設定の有無を確認し、あれば中止 |
| 意図しないデータ種別の記録 | 動画の記録が既定で有効になっていた | 記録しない種別は `false` を明示する |
| ログの保存期間 | 1 日に設定 | 業務要件と、個人情報を長く持たないことのバランスで決める |
| ログの暗号化 | CloudWatch Logs の既定の暗号化 | 本番では KMS のカスタマー管理キーで、復号できる人も絞る |
| Bedrock 用ロールの悪用（混乱した代理） | 信頼ポリシーに `aws:SourceAccount` / `aws:SourceArn` の条件 | 公式ドキュメントの形を使う |
| 海外リージョンでの処理 | `inferenceRegion` で事後に確認できる | データの所在に要件がある場合は、ログで処理リージョンを監視する |

## 7. 削除方法と削除後の確認

```bash
cd 02-bedrock-logging/terraform
terraform destroy -auto-approve
cd ../..
PYTHONPATH=02-bedrock-logging/src python -m bedrock_logging_lab.cli preflight      # 「設定はありません」
aws iam list-roles --query "Roles[?starts_with(RoleName,'lab02-bedrock-')].RoleName"   # []
aws logs describe-log-groups --log-group-name-prefix /aws-ai-security-labs/lab02     # 空
```

2026-11-23 に削除し、上の確認で、ログ設定・ロール・ロググループがすべて残っていないことを確認した。

## 8. 参考（公式）

- [Monitor model invocation using CloudWatch Logs and Amazon S3](https://docs.aws.amazon.com/bedrock/latest/userguide/model-invocation-logging.html)
- [Monitor Amazon Bedrock API calls using CloudTrail](https://docs.aws.amazon.com/bedrock/latest/userguide/logging-using-cloudtrail.html)
- [Amazon CloudWatch 料金](https://aws.amazon.com/cloudwatch/pricing/)
