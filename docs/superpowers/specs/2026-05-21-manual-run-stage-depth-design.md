# 手動実行セクション — ステージ深度選択 設計

## 概要

ダッシュボードの「手動実行」セクションを、パイプライン実行・ニュース更新の2ボタン構成から、
ステージ深度を選べるチェックボックス＋単一実行ボタンに再設計する。

---

## UI 変更（dashboard.html）

### 変更前

```
[パイプライン実行]  ← 全ステージ実行
[ニュース更新]      ← 過去N日の既存データに対してニュース+AIのみ再実行
```

### 変更後

```
手動実行
──────────────────────────────────
☑ ① 株価取得・急落検知
  ☑ ② 数値分析
    ☑ ③ ニュース取得
      ☑ ④ AI問診
[日付 yyyy-mm-dd]
[  実行  ]
──────────────────────────────────
[  ニュース更新  ]  ← 変更なし・別ボタンとして維持
```

### チェックボックスのカスケードルール

- **上位をチェック** → 下位は何もしない（前提なしに下位は動かせない）
- **下位をチェック** → 上位を自動でオン（前提ステージを強制包含）
- **上位をはずす** → 下位を自動でオフ（中間スキップを禁止）

インデントによって「前が必要」を視覚的に示す。

### 実装

- `<input type="hidden" name="max_stage">` に最後にチェックされた番号（1〜4）を保持
- JS `cascadeStages(n, checked)` でカスケードを処理し、hidden フィールドを更新
- `hx-include="#pipeline-date,#pipeline-max-stage"` でフォームデータを送信

---

## バックエンド変更

### 1. `app/routers/settings.py`

`run_pipeline_now` エンドポイントに `max_stage: int = Form(default=4)` を追加し、
`run_daily_pipeline()` に渡す。

```python
async def run_pipeline_now(
    ...
    max_stage: int = Form(default=4),
):
    ...
    await run_daily_pipeline(target_date=resolved_date, on_stage=on_stage, max_stage=max_stage)
```

### 2. `app/pipeline/runner.py`

`run_daily_pipeline()` に `max_stage: int = 4` パラメータを追加。
各ステージグループの終了時に早期リターン：

```python
async def run_daily_pipeline(
    target_date: str | None = None,
    on_stage: Callable[[str, str, str], None] | None = None,
    max_stage: int = 4,
) -> dict:
    ...
    # ステージ0〜1（株価取得・急落検知）
    ...
    if max_stage < 2:
        return stats

    # ステージ2（数値分析）
    ...
    if max_stage < 3:
        return stats

    # ステージ3a（ニュース取得）
    ...
    if max_stage < 4:
        return stats

    # ステージ3b（AI問診）
    ...
```

### 3. ニュース更新ボタン

`/settings/run-news-refresh` エンドポイントは変更なし。
UIでも独立したボタンとして維持する（混在させない）。

---

## ファイル一覧

| ファイル | 変更内容 |
|---|---|
| `app/templates/dashboard.html` | チェックボックスUI、JS cascade、hidden フィールド |
| `app/routers/settings.py` | `max_stage` フォームパラメータ追加 |
| `app/pipeline/runner.py` | `max_stage` パラメータ＋早期リターン |
| `tests/test_routers/test_settings.py` | `max_stage=1` での部分実行テスト追加 |

---

## 検証

1. デフォルト（全チェック）で実行 → 従来と同じ全ステージ動作
2. ①のみチェックで実行 → 株価取得・急落検知のみ完了してリターン
3. ①②チェックで実行 → 数値分析まで完了してリターン
4. ②チェック → ①が自動でオン（カスケード確認）
5. ①をはずす → ②③④が自動でオフ（カスケード確認）
6. ニュース更新ボタンは従来どおり動作
