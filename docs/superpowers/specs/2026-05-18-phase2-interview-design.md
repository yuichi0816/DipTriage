# Phase 2 設計書 — 問診・LLM 統合

**日付**: 2026-05-18  
**対象フェーズ**: Phase 2（第3段階：問診）  
**前提**: Phase 1（第0〜2段階）実装完了済み

---

## 概要

株価急落イベントに対して、ニュース取得と Qwen3 on Ollama による初期分類（事故型/事件型/不明）を日次パイプラインに追加する。

---

## スコープ

| 対象 | 内容 |
|---|---|
| ニュースソース | Yahoo Finance RSS のみ（TDnet は Phase 3 以降） |
| Ollama 呼び出し | Python ollama SDK（async）|
| エラー時挙動 | スキップして続行（status を analyzed のまま保持） |
| 問診対象 | macro_flag=0 かつ status="analyzed" のイベントのみ |

---

## ファイル構成

```
app/intelligence/
  ollama_client.py   ← 新規：ollama SDK の async ラッパー
  news_fetcher.py    ← 新規：Yahoo Finance RSS 取得 + DB 保存
  interview.py       ← 新規：プロンプト生成 + Qwen3 呼び出し + パース

app/pipeline/
  runner.py          ← 既存：Stage 3a・3b を追加

app/routers/
  dashboard.py       ← 既存：問診バッジ用に Briefing クエリを追加

app/templates/
  dashboard.html     ← 既存：事故/事件バッジを追加
```

---

## アーキテクチャ

### 各モジュールの責務

| ファイル | 何をするか | 依存 |
|---|---|---|
| `ollama_client.py` | `generate(prompt, model) -> (text, elapsed_sec)` で Ollama を呼ぶ | ollama SDK |
| `news_fetcher.py` | RSS 取得 → dedup → before_trigger 分類 → DB 保存 | feedparser, SQLAlchemy |
| `interview.py` | 数値 + ニュースからプロンプトを組み立て LLM を呼ぶ | ollama_client |
| `runner.py` | Stage 3a と 3b を順番に呼ぶ | news_fetcher, interview |

---

## データフロー

### Stage 3a: ニュース取得・保存（news_fetcher.py）

```
runner.py
  └─ fetch_and_save_news(session, event)
       ├─ Yahoo Finance RSS を feedparser で取得
       │    US株: feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US
       │    JP株: feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=JP&lang=ja-JP
       ├─ content_hash = sha256(title + url) を付与
       ├─ URL 重複なら is_duplicate=1 でスキップ
       ├─ published_at < trigger_date → before_trigger=1（原因記事候補）
       │   published_at >= trigger_date → before_trigger=0（後追い記事）
       └─ news_articles テーブルに upsert（on url）
```

### Stage 3b: LLM 問診（interview.py）

```
runner.py
  └─ run_interview(session, event, analysis, articles)
       ├─ is_duplicate=0 の記事を取得（before_trigger=1 を先頭にソート）
       ├─ プロンプトを組み立て → ollama_client.generate()
       ├─ JSON レスポンスをパース
       │    {"situation_summary": "...", "initial_class": "accident|incident|unknown"}
       ├─ Briefing レコードを INSERT（briefing_type="interview"）
       └─ DipEvent.status を "interviewed" に更新
```

### ステータス遷移

```
detected → analyzed → interviewed
                       ↑
              macro_flag=0 のイベントのみ進む
              macro_flag=1 は analyzed で停止
```

---

## プロンプト設計

### 入力フォーマット

```
/no_think
以下の株価急落イベントについて分析してください。

【銘柄】{symbol}（{name}） / {market} / {sector}
【急落日】{trigger_date}
【前日比】{change_pct_1d}%  【週間】{change_pct_5d}%
【出来高】{volume_ratio}倍（20日平均比）
【セクター超過下落】{sector_relative}%（{idiosyncratic_label}）

【関連ニュース（急落前後）】
{記事リスト（before_trigger 順、最大10件）}

以下のJSON形式のみで回答してください（他のテキスト不要）:
{
  "situation_summary": "1〜2文で何が起きたかを説明",
  "initial_class": "accident または incident または unknown"
}
```

`/no_think` により Qwen3 の思考チェーンを無効化し、推論速度を優先する。問診は簡易分類が目的であり、深い思考は Phase 3 の診断で行う。

### レスポンスのパース

- 正規表現で `{...}` ブロックを抽出して `json.loads()` でパース
- パース失敗時: `initial_class="unknown"`・`situation_summary="（解析失敗）"` で Briefing を保存し、status は `"analyzed"` のまま

---

## エラーハンドリング

| 状況 | 挙動 |
|---|---|
| Ollama 未起動・接続失敗 | `logger.error` に記録、そのイベントをスキップ、status は `"analyzed"` のまま |
| RSS 取得失敗 or 記事数 0 | `logger.warning` に記録、Stage 3b もスキップ（ニュースなしでは問診不可）|
| JSON パース失敗 | `situation_summary="（解析失敗）"`、`initial_class="unknown"` で保存 |
| タイムアウト | ollama SDK のデフォルトタイムアウトに委ねる（将来設定化可能） |

---

## UI 変更

### dashboard.html — 問診バッジ

既存の `event.status` 文字列バッジを問診結果バッジに置き換え：

| 状態 | バッジ |
|---|---|
| `initial_class = "accident"` | `bg-green-900 text-green-300` 「事故型」 |
| `initial_class = "incident"` | `bg-red-900 text-red-300` 「事件型」 |
| `initial_class = "unknown"` | `bg-gray-700 text-gray-400` 「不明」 |
| 未問診（macro_flag=1 or Ollama 障害） | `bg-gray-800 text-gray-500` status 文字列（現行） |

### dashboard.py — クエリ追加

`Briefing` テーブルから `briefing_type="interview"` かつ `is_latest=1` のレコードを `dip_event_id` でまとめて取得し、`interviews` 辞書としてテンプレートに渡す。

---

## 既存設計との整合性

- `Briefing` モデル（`briefing_type`, `situation_summary`, `initial_class`, `initial_class_jp`）は Phase 1 で定義済み。スキーマ変更不要。
- `NewsArticle` モデル（`content_hash`, `before_trigger`, `is_duplicate`）は Phase 1 で定義済み。スキーマ変更不要。
- `DipEvent.status` の遷移（`analyzed → interviewed`）は Phase 1 で定義済み。
- Alembic マイグレーション不要（テーブル・カラムに変更なし）。
- `OLLAMA_HOST`・`OLLAMA_MODEL_INTERVIEW` は `config.py` に定義済み。

---

## スコープ外（将来フェーズ）

- TDnet 適時開示の取得（Phase 3 以降）
- HTMX 再問診ボタン（Phase 3 の診断ボタンと同時実装）
- Qwen3 `/think` モードによる深い分析（Phase 3 診断で使用）
- ニュース本文の取得・要約（現在はタイトルのみ）
