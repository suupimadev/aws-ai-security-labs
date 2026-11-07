# Lab 01 アーキテクチャ

構成図は [01-bedrock-iam/README.md](../../01-bedrock-iam/README.md) の Mermaid 図を参照。

判断記録:
- リージョン ap-northeast-1（東京）: 実環境で Micro=プロファイルのみ, Lite=直接+プロファイルを確認。apac. プロファイルのルーティング先は6リージョン
- モデル: 最安クラスの Nova Micro（許可）/ Nova Lite（拒否）
- Converse の認可は bedrock:InvokeModel（専用アクション無し）
- terraform validate / plan / apply は実施済み（結果は docs/results/lab01-bedrock-iam.md）。検証用ロールは destroy 済み
