# ニュース独立更新機能 設計仕様

**Date:** 2026-05-19

## 背景・目的

株価データは1日1回の取得で十分だが、ニュースは日中に何度か更新される。
現在はパイプライン全体（株価取得 → 急落検知 → 分析 → ニュース → LLM）をひとまとめにしか実行できない。
ニュース取得と LLM 問診（Stage 3a + 3b）だけを任意のタイミングで実行できるボタンを `/settings` ページに追加する。

## 要件

- Stage 3a（RSS ニュース取得）+ Stage 3b（LLM 問診）のみ実行
- 対象: 過去 N 日以内に検出された非マクロ急落イベント
- N は設定画面から変更可能（デフォルト 5）
- 実行中はステージ名と進捗（例: `Stage 3b: LLM インタビュー 3 / 5`）を表示
- パイプライン全体の実行と独立して管理（同時実行可）

## データモデル変更

`app_settings` テーブルに 1 カラム追加:

| カラム | 型 | デフォルト | 説明 |
|---|---|---|---|
| `news_refresh_days` | INTEGER | 5 | ニュース更新対象の過去日数 |

Alembic マイグレーション: `ALTER TABLE app_settings ADD COLUMN news_refresh_days INTEGER NOT NULL DEFAULT 5`

## バックエンド

### `app/pipeline/runner.py`

新関数 `run_news_refresh(days: int, on_stage=None)`:
1. 過去 `days` 日以内の非マクロ `DipEvent`（`macro_flag=0`、`detected_date >= today - days`）を取得
2. Stage 3a: 各イベントのニュースを RSS から取得・保存
3. Stage 3b: ニュースがある各イベントに LLM 問診を実行
4. `on_stage(stage, current, total)` で進捗を通知

### `app/routers/settings.py`

エンドポイント追加:
- `POST /settings/run-news-refresh` — BackgroundTasks で `run_news_refresh` を起動、`app.state.news_status` を `running` に設定
- `GET /settings/news-status` — `app.state.news_status` を返す（`partials/news_status.html`）

### `app/main.py`

lifespan で `app.state.news_status = PipelineStatus()` を初期化。

## UI

### `settings.html` 変更点

設定フォームに追加:
```
ニュース更新対象日数: [5] 日以内
```

手動実行セクションに追加:
```
[今すぐパイプラインを実行]   ← 既存
[ニュースを今すぐ更新]       ← 新規
```

右カラムを縦2分割:
```
┌──────────────────────┐
│ パイプライン          │
│ ✓ 完了 07:23        │
├──────────────────────┤
│ ニュース更新          │
│ ⟳ Stage 3b: LLM    │
│   3 / 5              │
└──────────────────────┘
```

### 新規テンプレート

`app/templates/partials/news_status.html` — `pipeline_status.html` と同パターン。HTMX `every 3s` ポーリング（running 時のみ）。

## 変更ファイル一覧

| ファイル | 変更種別 |
|---|---|
| `alembic/versions/xxxx_add_news_refresh_days.py` | 新規マイグレーション |
| `app/models/settings.py` | `news_refresh_days` カラム追加 |
| `app/pipeline/runner.py` | `run_news_refresh()` 追加 |
| `app/routers/settings.py` | 2 エンドポイント追加 |
| `app/main.py` | `app.state.news_status` 初期化 |
| `app/templates/settings.html` | 入力欄・ボタン・パネル追加 |
| `app/templates/partials/news_status.html` | 新規作成 |
| `tests/test_routers/test_settings.py` | 新規テスト追加 |

## 検証

1. `uv run alembic upgrade head` でマイグレーション適用
2. `http://localhost:8000/settings` で `news_refresh_days` 入力欄が表示されること
3. 「ニュースを今すぐ更新」ボタン押下 → 右カラム下部にスピナーと進捗が表示されること
4. 完了後「✓ 完了」が表示されポーリングが停止すること
5. パイプライン実行中にニュース更新を実行しても干渉しないこと
6. `uv run pytest tests/test_routers/test_settings.py -v` で全テスト通過
