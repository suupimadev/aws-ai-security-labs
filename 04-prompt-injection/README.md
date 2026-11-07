# Lab 04: Prompt Injection 対策（計画のみ・未着手）

記事案: 「Amazon Bedrock GuardrailsでPrompt Injectionはどこまで防げるのか？」

## 検証計画
- 仕組みの解説、通常質問 vs 攻撃プロンプトのデータセット作成
- Guardrails あり／なしでの検出率・誤検知率の測定（CSV 記録）
- 検出できない攻撃パターンの整理と追加対策の考察

制約: 自身の検証環境のみ。実データ・外部・第三者環境は対象外。
着手条件: Lab 03 完了後、ユーザーの指示。
