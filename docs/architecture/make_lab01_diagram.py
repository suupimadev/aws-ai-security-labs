"""Lab 01 の AWS 構成図を、AWS 公式アイコン（diagrams ライブラリ同梱）で生成する。

実行: python docs/architecture/make_lab01_diagram.py
前提: graphviz（dot）と `pip install diagrams`
出力: docs/architecture/lab01-architecture.png
"""

from pathlib import Path

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.general import User
from diagrams.aws.ml import Bedrock
from diagrams.aws.security import IAMAWSSts, IAMRole

FONT = "Hiragino Sans GB"  # macOS 標準の日本語フォント
OUT = Path(__file__).parent / "lab01-architecture"

graph_attr = {
    "fontname": FONT,
    "fontsize": "20",
    "pad": "0.5",
    "ranksep": "1.6",
    "nodesep": "0.9",
    "splines": "spline",
}
node_attr = {"fontname": FONT, "fontsize": "13"}
edge_attr = {"fontname": FONT, "fontsize": "12"}

ALLOW, DENY = "#2e7d32", "#c62828"

with Diagram(
    "Lab 01: Bedrock IAM アクセス制御（ap-northeast-1）\n"
    "緑の実線 = 許可 / 赤の破線 = 拒否（シナリオ S1〜S8 は記事の表を参照）",
    filename=str(OUT),
    outformat="png",
    direction="LR",
    show=False,
    graph_attr=graph_attr,
    node_attr=node_attr,
    edge_attr=edge_attr,
):
    user = User("検証者\n(IAM Identity Center)")
    sts = IAMAWSSts("AWS STS\nAssumeRole\n(一時認証情報 15分)")

    with Cluster("IAM ロール（Terraform で作成）"):
        allowlist = IAMRole("allowlist\nMicro のみ Allow")
        profileonly = IAMRole("profileonly\nプロファイル ARN のみ")
        denylist = IAMRole("denylist\n広い Allow +\nNova Lite を Deny")
        noperm = IAMRole("noperm\n権限なし")

    with Cluster("Amazon Bedrock（Converse API / bedrock:InvokeModel）"):
        profile = Bedrock("推論プロファイル\napac.amazon.nova-micro / lite")
        with Cluster(
            "ルーティング先: APAC 6 リージョン\n"
            "（東京・大阪・ソウル・ムンバイ・シンガポール・シドニー）"
        ):
            micro = Bedrock("Nova Micro\n基盤モデル")
        lite_direct = Bedrock("Nova Lite\n直接呼び出し\n(東京のみ)")

    user >> sts
    sts >> [noperm, profileonly, denylist, allowlist]  # 図の上から allowlist が並ぶ順

    # 許可された経路（緑）
    allowlist >> Edge(color=ALLOW) >> profile
    denylist >> Edge(color=ALLOW) >> profile
    profile >> Edge(color=ALLOW) >> micro

    # 拒否された経路（赤）
    profileonly >> Edge(color=DENY, style="dashed") >> profile
    noperm >> Edge(color=DENY, style="dashed") >> profile
    allowlist >> Edge(color=DENY, style="dashed") >> lite_direct
    denylist >> Edge(color=DENY, style="dashed") >> lite_direct
