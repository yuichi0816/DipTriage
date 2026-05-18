# Phase 4 実装引継書

**作成日**: 2026-05-18（ウォッチリスト実装完了時点で更新）
**対象**: Phase 4 継続実装

---

## 現在の状態

Phase 1〜3 + Phase 4 ウォッチリスト機能が実装完了・テスト通過済み。

| フェーズ | 内容 | 状態 |
|---|---|---|
| Phase 1 | データ取得・急落検知・数値分析・最小 Web UI | 完了 |
| Phase 2 | ニュース取得（Yahoo Finance RSS）+ Qwen3 問診 | 完了 |
| Phase 3 | 診断（反証・moat 評価）| 完了 |
| Phase 4a | ウォッチリスト | **完了** |
| Phase 4b | 再診断ボタン・通知・その他拡張 | **これから** |

---

## プロジェクト概要

「株価急落銘柄が事故（一時的）か事件（構造的）か」を判断する材料をブリーフィング形式で提示するツール。最終判断は人間が行う。個別株投資初心者の判断補助が目的。

**インフラ**: UM780 + RTX 4090 Ti eGPU、Tailscale 経由リモートアクセス
**LLM**: Qwen3 on Ollama（ローカル）— `qwen3:30b`（問診）/ `qwen3:30b`（診断）
**DB**: SQLite + SQLAlchemy 2.x async
**Web**: FastAPI + Jinja2 + HTMX + Tailwind CSS（CDN）
**GitHub**: https://github.com/yuichi0816/DipTriage

---

## 現在のファイル構成

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
                            counterarguments, confidence, full_text, is_latest）
    watchlist.py          — WatchlistEntry（status: watching|closed）, WatchlistSnapshot
  pipeline/
    fetcher.py            — yfinance データ取得
    detector.py           — 急落検知（マクロフィルタ＋スクリーニング）
    analyzer.py           — 数値分析
    runner.py             — Stage 0〜4 のオーケストレーター
                            snapshot_watching_entries(session, today) を公開関数として定義
  intelligence/
    ollama_client.py      — generate(prompt, model, think=False) → (text, elapsed)
    news_fetcher.py       — fetch_rss_articles / fetch_and_save_news
    interview.py          — build_prompt / parse_llm_response / run_interview
    diagnosis.py          — build_diagnosis_prompt / parse_diagnosis_response / run_diagnosis
  routers/
    dashboard.py          — GET /（急落リスト）
    dip_detail.py         — GET /dip/{id}（詳細）
                            POST /dip/{id}/diagnose（HTMX 診断）
                            POST /dip/{id}/watchlist（HTMX ウォッチリスト追加）
    watchlist.py          — GET /watchlist（一覧）
                            POST /watchlist/{id}/close（HTMX クローズ）
  templates/
    base.html             — ベーステンプレート（htmx-indicator CSS 込み）
    dashboard.html        — ダッシュボード（事故型/事件型/不明バッジ）
    dip_detail.html       — 詳細 + HTMX 診断ボタン + HTMX ウォッチリストボタン
    watchlist.html        — ウォッチリスト一覧（回復率・スナップショット表示）
    partials/
      diagnosis_result.html  — HTMX レスポンス用診断結果パーシャル
      watchlist_button.html  — HTMX レスポンス用ウォッチリストボタンパーシャル
scripts/
  backfill.py             — 過去日付のデータ投入
  run_pipeline_once.py    — 手動パイプライン実行
docs/
  manual.md               — 操作マニュアル
  handover-phase3.md      — Phase 3 引継書（参考）
  handover-phase4.md      — このファイル
  superpowers/
    specs/                — 各フェーズの設計書
    plans/                — 各フェーズの実装計画
```

---

## テスト状況

```
tests/test_pipeline/test_analyzer.py              17件
tests/test_pipeline/test_detector.py              10件
tests/test_intelligence/test_ollama_client.py      2件
tests/test_intelligence/test_news_fetcher.py      14件
tests/test_intelligence/test_interview.py         16件
tests/test_intelligence/test_diagnosis.py         16件
tests/test_routers/test_watchlist.py               8件
合計: 83件全通過
```

pytest 設定: `asyncio_mode = "auto"`（pyproject.toml）
統合テストは `sqlite+aiosqlite:///:memory:` でインメモリ DB を使用。

ルーターテストのパターン（`tests/test_routers/test_watchlist.py` を参照）:
- `app.dependency_overrides[get_db]` でインメモリ DB に差し替え
- `httpx.AsyncClient(transport=ASGITransport(app=app))` を使用
- `ASGITransport` はアプリのライフサイクルイベント（init_db, scheduler）を起動しない

---

## Phase 4 で踏んだ落とし穴（Phase 4b でも注意）

1. **session.rollback() が全オブジェクトを expire させる**
   LLM 呼び出しと DB 書き込みを別の try/except に分割すること。
   → `app/intelligence/diagnosis.py` の構造を参考にすること。

2. **Starlette 1.0 の TemplateResponse**
   `TemplateResponse(request, "template.html", {...})` の形式（第1引数が request）。

3. **htmx-indicator の CSS セレクタ**
   HTMX は indicator 要素自身に `htmx-request` クラスを付与する。
   正しい CSS: `.htmx-indicator.htmx-request { display: inline; }`

4. **NumericalAnalysis / WatchlistSnapshot のクエリに `.limit(1)` が必要**
   同一キーに複数レコードが存在しうる。`scalar_one()` では MultipleResultsFound になる。

5. **HTMX の outerHTML swap 後に container の CSS クラスが失われる**
   パーシャル HTML のルート要素にも元の CSS クラス（`mb-4` 等）を付けること。

6. **WatchlistSnapshot の ON CONFLICT**
   `sqlite_insert(WatchlistSnapshot).values(...).on_conflict_do_nothing()` で重複スナップショットをスキップ。
   同一日に複数回パイプラインが走っても安全。

---

## Phase 4b 候補機能

### 優先度 高

| 機能 | 概要 |
|---|---|
| 再診断ボタン | 同じイベントを再度診断。`is_latest` の管理ロジックは `run_diagnosis()` に実装済み |
| Tailscale 通知 | 急落検知時に LINE / メール / Discord へ通知 |

### 優先度 中

| 機能 | 概要 |
|---|---|
| TDnet 適時開示取得 | 日本株の情報ソース強化 |
| 診断履歴表示 | 同一イベントの過去診断を一覧表示（`is_latest=0` のレコードも表示） |
| 確信度ダッシュボード | 診断の confidence 分布をグラフ表示 |

### 優先度 低

| 機能 | 概要 |
|---|---|
| 日本株対応 | NIKKEI225 銘柄のスクリーニング（シンボルリスト取得が課題） |
| PDF エクスポート | 診断ブリーフィングを PDF で保存 |
| バックテスト | 過去の診断結果と実際の株価推移の照合 |

---

## 参照すべきファイル

| ファイル | 目的 |
|---|---|
| `app/intelligence/diagnosis.py` | LLM 呼び出し・DB 保存の構造（rollback 注意） |
| `app/routers/dip_detail.py` | HTMX POST エンドポイントのパターン |
| `app/routers/watchlist.py` | ウォッチリストルーターのパターン |
| `app/templates/partials/watchlist_button.html` | HTMX パーシャルのテンプレートパターン |
| `tests/test_routers/test_watchlist.py` | ルーターテストのパターン（ASGITransport + dependency override） |

---

## サーバー起動方法

```powershell
cd "C:\Users\yuich\OneDrive\ドキュメント\GitHub\DipTriage"
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

詳細は `docs/manual.md` を参照。
