# Phase 3 実装引継書

**作成日**: 2026-05-18  
**対象**: Phase 3（診断・反証・moat 評価）の設計書作成および実装

---

## 現在の状態

Phase 1・2 が実装完了・動作確認済み（最新コミット: `1796146`）。

| フェーズ | 内容 | 状態 |
|---|---|---|
| Phase 1 | データ取得・急落検知・数値分析・最小 Web UI | 完了 |
| Phase 2 | ニュース取得（Yahoo Finance RSS）+ Qwen3 問診 | 完了 |
| Phase 3 | 診断（反証・moat 評価）| **これから** |

---

## プロジェクト概要

「株価急落銘柄が事故（一時的）か事件（構造的）か」を判断する材料をブリーフィング形式で提示するツール。最終判断は人間が行う。個別株投資初心者の判断補助が目的。

**インフラ**: UM780 + RTX 4090 Ti eGPU、Tailscale 経由リモートアクセス  
**LLM**: Qwen3 on Ollama（ローカル）— `qwen3.5:9b`（問診）/ `qwen3.6:35b`（診断）  
**DB**: SQLite + SQLAlchemy 2.x async  
**Web**: FastAPI + Jinja2 + HTMX + Tailwind CSS（CDN）

---

## 既存ファイル構成

```
app/
  config.py               — 環境変数（OLLAMA_HOST, OLLAMA_MODEL_INTERVIEW/DIAGNOSIS）
  database.py             — AsyncSessionLocal, get_db
  models/
    stock.py              — Base, StockMeta, StockPrice, IndexPrice
    dip.py                — DipEvent（status: detected→analyzed→interviewed→diagnosed）
    analysis.py           — NumericalAnalysis
    news.py               — NewsArticle（before_trigger, is_duplicate, content_hash）
    briefing.py           — Briefing（briefing_type, situation_summary, initial_class,
                            initial_class_jp, accident_subtype, moat_json,
                            counterarguments, confidence, is_latest）
    watchlist.py          — WatchlistEntry, WatchlistSnapshot
  pipeline/
    fetcher.py            — yfinance データ取得
    detector.py           — 急落検知（マクロフィルタ＋スクリーニング）
    analyzer.py           — 数値分析
    runner.py             — Stage 0〜3b のオーケストレーター
  intelligence/
    ollama_client.py      — generate(prompt, model, think=False) → (text, elapsed)
    news_fetcher.py       — fetch_rss_articles / fetch_and_save_news
    interview.py          — build_prompt / parse_llm_response / run_interview
  routers/
    dashboard.py          — GET /（急落リスト）
    dip_detail.py         — GET /dip/{id}（数値分析詳細）
    watchlist.py          — GET /watchlist（スタブ）
  templates/
    base.html, dashboard.html, dip_detail.html, watchlist.html
```

---

## Phase 3 のスコープ（concept_v2.md より）

### 概要

Phase 3 = 第4段階「診断」。オンデマンドで実行する（日次自動ではない）。

ユーザーが問診済みイベントの詳細画面で「診断ボタン」を押すと起動。`qwen3.6:35b` + `think=True` で深い推論を行う。

### 出力フォーマット（concept_v2.md より抜粋）

```
━━ 診断ブリーフィング ━━
銘柄: CRWD（CrowdStrike） 市場: NASDAQ
検知日: 2024-07-19  分析日: 2024-07-20

■ 数値サマリー
  前日比: -11.2% / 週間: -8.7% / 出来高異常度: 4.2倍
  セクター相対: 銘柄固有 / β値: 1.12
  PER: 68.3 / PBR: 25.1 / 自己資本比率: 42%

■ 原因分析
  分類: 事故型 — システム障害
  根拠: ...

■ moat 評価
  スイッチングコスト: 高 / ネットワーク効果: 有
  規制参入障壁: 中 / ブランド依存度: 中
  → 総合: 毀損度 低。

■ 類似ケース
  - Meta（2021-10 大規模障害）: 事故型、数日で回復

■ 反証（事件である可能性）
  1. 品質管理体制に構造的な欠陥がある可能性
  2. 集団訴訟に発展し財務への影響が拡大する可能性
  3. 政府系顧客の契約解除が連鎖する可能性

■ 見落としリスク
  ...

■ 分析の確信度: 中〜高
━━━━━━━━━━━━━━━━
```

### 主要コンポーネント（実装すべきもの）

| ファイル | 操作 | 内容 |
|---|---|---|
| `app/intelligence/diagnosis.py` | 新規 | build_diagnosis_prompt / parse_diagnosis_response / run_diagnosis |
| `app/routers/dip_detail.py` | 修正 | POST /dip/{id}/diagnose エンドポイント追加 |
| `app/templates/dip_detail.html` | 修正 | 診断ブリーフィング表示 + HTMX 診断ボタン |

### Briefing モデルの既存フィールド（追加不要）

`app/models/briefing.py` に診断用フィールドが Phase 1 で定義済み：

```python
briefing_type: str        # "interview" | "diagnosis"
accident_subtype: str     # システム障害 / 一時的決算ミス / 製品リコール / 経営発言・炎上 / 自然災害
moat_json: str            # JSON: {switching_cost, network_effect, regulatory_barrier, brand_dependency}
counterarguments: str     # 反証3件（テキスト）
confidence: str           # "high" | "medium" | "low"
is_latest: int            # 1=最新
```

`DipEvent.status` の `"diagnosed"` への遷移も定義済み。Alembic マイグレーション不要。

---

## Ollama 呼び出しの設計方針

**問診（Phase 2）**: `think=False`、`qwen3.5:9b`（速度優先）  
**診断（Phase 3）**: `think=True`、`qwen3.6:35b`（精度優先）

`ollama_client.generate()` に `think` パラメータ済み。診断では `think=True` を渡すだけ。

```python
# 診断での呼び出し例
text, elapsed = await generate(prompt, model=OLLAMA_MODEL_DIAGNOSIS, think=True)
```

---

## Phase 2 で踏んだ落とし穴（Phase 3 でも注意）

1. **session.rollback() が全オブジェクトを expire させる**  
   LLM 呼び出しと DB 書き込みを別の try/except に分割すること。  
   LLM 失敗時は rollback を呼ばずそのまま `return None` する。  
   → `app/intelligence/interview.py` の構造を参考にすること。

2. **Starlette 1.0 の TemplateResponse**  
   `TemplateResponse(request, "template.html", {...})` の形式（第1引数が request）。

3. **`think=False` は API パラメータで渡す**  
   プロンプトの `/no_think` テキストは効果が不安定。`client.chat(think=False)` を使う。

4. **Yahoo Finance RSS は直近ニュースのみ**  
   バックフィルテストでは記事が空になる。本番（当日）では問題なし。

---

## テスト状況

```
tests/test_pipeline/test_analyzer.py    17件
tests/test_pipeline/test_detector.py   10件
tests/test_intelligence/test_ollama_client.py  2件
tests/test_intelligence/test_news_fetcher.py  14件
tests/test_intelligence/test_interview.py     16件
合計: 59件全通過
```

pytest 設定: `asyncio_mode = "auto"`（pyproject.toml）  
統合テストは `sqlite+aiosqlite:///:memory:` でインメモリ DB を使用。

---

## 次のセッションでやること

1. **設計書を書く**  
   `docs/superpowers/specs/2026-05-18-phase3-diagnosis-design.md` を作成。  
   設計書の構成は `docs/superpowers/specs/2026-05-18-phase2-interview-design.md` を参考にすること。

2. **実装計画を書く**  
   `docs/superpowers/plans/2026-05-18-phase3-diagnosis.md` を作成。  
   計画書の構成は `docs/superpowers/plans/2026-05-18-phase2-interview.md` を参考にすること。

3. **実装に入る**  
   `superpowers:subagent-driven-development` スキルで実行。

---

## 設計書を書く際に参照すべきファイル

| ファイル | 目的 |
|---|---|
| `concept_v2.md` | 第4段階「診断」の全仕様（出力フォーマット・moat 評価軸・反証ステップ）|
| `app/models/briefing.py` | 既存の診断用フィールド確認 |
| `app/intelligence/interview.py` | 問診の実装パターン（診断でも同じ構造を使う）|
| `docs/superpowers/specs/2026-05-18-phase2-interview-design.md` | 設計書のテンプレート |
| `docs/superpowers/plans/2026-05-18-phase2-interview.md` | 計画書のテンプレート（TDD ステップ形式）|
