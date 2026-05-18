# DipTriage 簡易マニュアル

**目的**: 株価急落銘柄が「事故（一時的）」か「事件（構造的）」かを判断する材料を提示するツール。最終判断は人間が行う。

---

## 起動手順

### 1. Ollama を起動する（LLM が必要な場合）

```bash
# Ollama サービスを起動
ollama serve

# 必要なモデルを確認（未 pull の場合は pull）
ollama list
ollama pull qwen3.5:9b    # 問診用（速い）
ollama pull qwen3.6:35b   # 診断用（精度高い・数分かかる）
```

### 2. Web サーバーを起動する

```powershell
# まずプロジェクトディレクトリに移動する
cd "C:\Users\yuich\OneDrive\ドキュメント\GitHub\DipTriage"

uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

ブラウザで **http://localhost:8000** を開く。

---

## 日次ワークフロー

```
毎朝 7:00 に自動実行
   ↓
① 急落検知（前日比 -5% 以下 かつ マクロ要因でない銘柄）
   ↓
② 数値分析（出来高・β値・PER/PBR・セクター相関）
   ↓
③ ニュース取得（Yahoo Finance RSS）
   ↓
④ 問診 LLM（Qwen3 9b）→「事故型 / 事件型 / 不明」の初期分類
   ↓
⑤ 診断 LLM（Qwen3 35b）→ オンデマンドで実行（ユーザーが手動起動）
```

### 手動実行（任意の日付でテスト）

```bash
# 本日分のパイプラインを手動実行
uv run python scripts/run_pipeline_once.py

# 過去日付でバックフィル（例: CrowdStrike 事例）
uv run python scripts/backfill.py 2024-07-19
```

---

## 画面説明

### ダッシュボード（/）

急落検知済みのイベント一覧。

| 表示項目 | 内容 |
|---|---|
| バッジ（事故型 / 事件型 / 不明） | 問診 LLM の初期分類 |
| ステータス | detected → analyzed → interviewed → diagnosed |
| 前日比 | 急落率（%） |
| マクロフラグ | ✓ = 市場全体の下落が原因（分析スキップ） |

### 詳細画面（/dip/{id}）

銘柄をクリックすると表示。

**数値分析セクション**
- 前日比 / 週間騰落率
- 出来高異常度（過去20日平均比）
- β値・ETF相関（銘柄固有か市場連動かの判定）
- PER / PBR（バリュエーション）

**問診ブリーフィング**
- LLM による状況サマリー
- 初期分類（事故型 / 事件型 / 不明）

**診断ブリーフィング**（問診完了後にボタンが出現）

1. **「診断を実行」ボタン**をクリック
2. 「分析中（数分かかります）...」と表示される
3. 完了すると以下が表示される：
   - 原因分析（事故サブタイプ：システム障害 / 決算ミス / リコール など）
   - moat 評価（スイッチングコスト / ネットワーク効果 / 規制障壁 / ブランド）
   - 類似ケース
   - **反証3件**（事件である可能性）
   - 見落としリスク
   - 確信度（high / medium / low）

---

## 環境変数（.env ファイルで設定可）

| 変数 | デフォルト | 説明 |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama のエンドポイント |
| `OLLAMA_MODEL_INTERVIEW` | `qwen3.5:9b` | 問診モデル |
| `OLLAMA_MODEL_DIAGNOSIS` | `qwen3.6:35b` | 診断モデル |
| `THRESHOLD_DIP_PCT` | `-5.0` | 急落検知の閾値（%） |
| `MACRO_FILTER_PCT` | `-2.0` | マクロフィルタの閾値（%） |
| `DB_PATH` | `data/diptriage.db` | SQLite DB のパス |
| `PIPELINE_HOUR` | `7` | 自動実行の時刻（時） |

設定例（`.env`）：
```
OLLAMA_HOST=http://192.168.1.100:11434
OLLAMA_MODEL_DIAGNOSIS=qwen3.6:35b
THRESHOLD_DIP_PCT=-7.0
```

---

## トラブルシューティング

| 症状 | 原因 | 対処 |
|---|---|---|
| 診断ボタンが表示されない | status が interviewed/diagnosed でない | 問診が完了するまで待つ |
| 「診断に失敗しました」 | Ollama が起動していない | `ollama serve` を実行 |
| 問診で止まる（interviewed にならない） | Ollama 未起動、またはモデル未 pull | `ollama list` で確認・pull |
| ダッシュボードが空 | データ未投入 | `scripts/backfill.py` でテストデータを投入 |
| 「マクロフラグ」のイベントが多い | 市場全体が大きく下落している | 正常動作（個別要因の急落のみ分析対象） |

---

## テスト実行

```bash
uv run pytest -v
# → 75件 PASSED が期待値
```
