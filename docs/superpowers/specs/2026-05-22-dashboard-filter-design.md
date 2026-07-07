# ダッシュボード フィルタ機能 設計仕様

## 背景・目的

ダッシュボードにはソート機能のみ実装されており、フィルタ（絞り込み）機能がない。
日数が経過した古い急落情報が常に表示されてしまい、直近の注目銘柄を素早く確認できない。

追加するフィルタ：
- **期間フィルタ**：`trigger_date` から N 日以内のイベントのみ（デフォルト30日）
- **市場フィルタ**：東証プライム / スタンダード / グロース / US
- **ステータスフィルタ**：DipEvent.status で絞り込み（6値 + all）
- **分類フィルタ**：Briefing.initial_class で絞り込み
- **急落率フィルタ**：X%以上の急落のみ表示（数値入力）
- **週間変化率フィルタ**：週間でX%以上の下落のみ表示（数値入力）

## URL 設計

クエリパラメータ方式。ブックマーク・リロードで状態が保持される。

```
/?sort=date&days=30&market=all&status=all&class=all&min_drop=0&min_weekly_drop=0
```

| パラメータ | デフォルト | 有効値 |
|---|---|---|
| `days` | `30` | `30` / `60` / `90` / `0`（全件） |
| `market` | `all` | `all` / `prime` / `standard` / `growth` / `US` |
| `status` | `all` | `all` / `detected` / `analyzed` / `interviewed` / `diagnosed` / `watching` / `closed` |
| `class` | `all` | `all` / `accident` / `incident` / `structural` / `macro` / `unknown` |
| `min_drop` | `0` | 整数（0 = フィルタなし、5 = -5%以下の急落のみ） |
| `min_weekly_drop` | `0` | 整数（0 = フィルタなし） |

### 市場パラメータと StockMeta フィールドの対応

| 値 | 条件 |
|---|---|
| `prime` | `StockMeta.index_name = "Nikkei225"` |
| `standard` | `StockMeta.index_name = "TSE Standard"` |
| `growth` | `StockMeta.index_name = "TSE Growth"` |
| `US` | `StockMeta.market = "US"` |

## アーキテクチャ

### サーバーサイド（dashboard.py）

クエリパラメータを受け取り、SQLAlchemy クエリに条件を動的に付加してから `.limit(50)` を実行する。

```python
from datetime import date, timedelta

query = select(DipEvent)

# 期間フィルタ
if days > 0:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    query = query.where(DipEvent.trigger_date >= cutoff)

# ステータスフィルタ
if status != "all":
    query = query.where(DipEvent.status == status)

# 市場フィルタ（StockMeta との JOIN）
if market != "all":
    query = query.join(StockMeta, DipEvent.symbol == StockMeta.symbol)
    if market == "prime":
        query = query.where(StockMeta.index_name == "Nikkei225")
    elif market == "standard":
        query = query.where(StockMeta.index_name == "TSE Standard")
    elif market == "growth":
        query = query.where(StockMeta.index_name == "TSE Growth")
    elif market == "US":
        query = query.where(StockMeta.market == "US")

# 分類フィルタ（Briefing サブクエリ）
if class_filter != "all":
    subq = (
        select(Briefing.dip_event_id)
        .where(
            Briefing.briefing_type == "interview",
            Briefing.is_latest == 1,
            Briefing.initial_class == class_filter,
        )
        .scalar_subquery()
    )
    query = query.where(DipEvent.id.in_(subq))

# 急落率フィルタ
if min_drop > 0:
    query = query.where(DipEvent.change_pct_1d <= -min_drop)

# 週間変化率フィルタ
if min_weekly_drop > 0:
    query = query.where(DipEvent.change_pct_5d <= -min_weekly_drop)

query = query.order_by(desc(DipEvent.detected_date), desc(DipEvent.change_pct_1d)).limit(50)
```

### フロントエンド（dashboard.html）

急落リストヘッダーの下にフィルタバーを追加する（6行）。

```
[期間]  30日  60日  90日  すべて
[市場]  すべて  プライム  スタンダード  グロース  US
[状態]  すべて  検出済  分析済  問診済  診断済  監視中  完了
[分類]  すべて  事故型  事件型  構造的  マクロ  不明
[急落]  ≤ -[ 数値入力 ]%  週 ≤ -[ 数値入力 ]%  [適用]
```

数値フィルタ行は `<form method="get" action="/">` + 全パラメータの hidden フィールド。
ボタン系フィルタは `<a href="...">` リンク（全パラメータを保持）。

## 変更ファイル

1. `app/routers/dashboard.py` — クエリパラメータ追加・動的 WHERE 句・テンプレートコンテキスト追加
2. `app/templates/dashboard.html` — フィルタバー追加・ソートリンク更新

## 検証方法

1. `uvicorn app.main:app --reload` でサーバー起動
2. ブラウザで `http://localhost:8000/` を開く
3. 期間「すべて」→ デフォルト30日より古いイベントが表示されることを確認
4. 市場「プライム」→ 日経225銘柄のみ表示されることを確認
5. 市場「US」→ 米国株のみ表示されることを確認
6. ステータス「watching」→ 監視中のみ表示されることを確認
7. 分類「accident」→ 事故型のみ表示されることを確認
8. 急落率に「10」入力→「適用」→ -10%以下のイベントのみ表示されることを確認
9. ソートボタンクリック後もフィルタが保持されることを確認
10. フィルタ組み合わせ URL をリロード → 状態が保持されることを確認
