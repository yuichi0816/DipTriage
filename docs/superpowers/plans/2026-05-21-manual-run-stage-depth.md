# 手動実行ステージ深度選択 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 手動実行セクションの「パイプライン実行」ボタンを、4ステージをカスケードチェックボックスで選択して単一の「実行」ボタンで動かす形に変更する。

**Architecture:** バックエンドは `run_daily_pipeline()` に `max_stage: int = 4` を追加し、各ステージ完了後に早期リターンする。ルーターはフォームパラメータ `max_stage` を受け取って runner に渡す。フロントエンドはチェックボックス4個とカスケードJS、hidden フィールドで最大ステージ番号を送信する。

**Tech Stack:** FastAPI, Jinja2 + HTMX, Tailwind CSS (CDN), SQLite/aiosqlite, pytest-asyncio

---

### Task 1: バックエンド — max_stage パラメータ追加 (TDD)

**Files:**
- Modify: `app/pipeline/runner.py:121-124` (関数シグネチャ) + 3箇所に早期リターン追加
- Modify: `app/routers/settings.py:67-109` (`run_pipeline_now` エンドポイント)
- Test: `tests/test_routers/test_settings.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_routers/test_settings.py` の先頭 import に `asyncio` を追加し、末尾に以下を追加する:

```python
import asyncio
```

```python
async def test_run_pipeline_forwards_max_stage(client):
    with patch('app.pipeline.runner.run_daily_pipeline', new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {}
        response = await client.post("/settings/run-pipeline", data={"max_stage": "2"})
        assert response.status_code == 200
        await asyncio.sleep(0.1)
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs.get('max_stage') == 2
```

- [ ] **Step 2: テストが失敗することを確認**

```
uv run pytest tests/test_routers/test_settings.py::test_run_pipeline_forwards_max_stage -v
```

Expected: FAIL — `run_pipeline_now` が `max_stage` を受け取らず mock に渡さないため。

- [ ] **Step 3: runner.py — 関数シグネチャに max_stage を追加**

`app/pipeline/runner.py` の `run_daily_pipeline` 関数シグネチャを変更する:

```python
# 変更前 (line 121-124):
async def run_daily_pipeline(
    target_date: str | None = None,
    on_stage: Callable[[str, str, str], None] | None = None,
) -> dict:

# 変更後:
async def run_daily_pipeline(
    target_date: str | None = None,
    on_stage: Callable[[str, str, str], None] | None = None,
    max_stage: int = 4,
) -> dict:
```

- [ ] **Step 4: runner.py — Stage 1 完了後に早期リターンを追加**

`app/pipeline/runner.py` の line 215-216 付近:

```python
# 変更前:
        dip_events = await save_dip_events(session, dip_candidates, detected_date=target_date)
        stats["dips_detected"] = len(dip_events)

        # ── 第2段階：数値分析 ──

# 変更後:
        dip_events = await save_dip_events(session, dip_candidates, detected_date=target_date)
        stats["dips_detected"] = len(dip_events)

        if max_stage < 2:
            return stats

        # ── 第2段階：数値分析 ──
```

- [ ] **Step 5: runner.py — Stage 2 完了後に早期リターンを追加**

`app/pipeline/runner.py` の line 231-233 付近:

```python
# 変更前:
            except Exception as e:
                logger.error("Analysis failed for %s: %s", event.symbol, e)

        # ── 第3段階a: ニュース取得 ──

# 変更後:
            except Exception as e:
                logger.error("Analysis failed for %s: %s", event.symbol, e)

        if max_stage < 3:
            return stats

        # ── 第3段階a: ニュース取得 ──
```

- [ ] **Step 6: runner.py — Stage 3a 完了後に早期リターンを追加**

`app/pipeline/runner.py` の line 243-245 付近:

```python
# 変更前:
            except Exception as e:
                logger.warning("News fetch failed for %s: %s", event.symbol, e)

        # ── 第3段階b: LLM 問診 ──

# 変更後:
            except Exception as e:
                logger.warning("News fetch failed for %s: %s", event.symbol, e)

        if max_stage < 4:
            return stats

        # ── 第3段階b: LLM 問診 ──
```

- [ ] **Step 7: settings.py — max_stage フォームパラメータを追加**

`app/routers/settings.py` の `run_pipeline_now` 関数を変更する:

```python
# 変更前:
@router.post("/settings/run-pipeline", response_class=HTMLResponse)
async def run_pipeline_now(
    request: Request,
    background_tasks: BackgroundTasks,
    target_date: str = Form(default=""),
):

# 変更後:
@router.post("/settings/run-pipeline", response_class=HTMLResponse)
async def run_pipeline_now(
    request: Request,
    background_tasks: BackgroundTasks,
    target_date: str = Form(default=""),
    max_stage: int = Form(default=4),
):
```

- [ ] **Step 8: settings.py — max_stage を run_daily_pipeline に渡す**

同ファイルの `_run()` クロージャ内の呼び出しを変更:

```python
# 変更前:
            await run_daily_pipeline(target_date=resolved_date, on_stage=on_stage)

# 変更後:
            await run_daily_pipeline(target_date=resolved_date, on_stage=on_stage, max_stage=max_stage)
```

- [ ] **Step 9: テストが通ることを確認**

```
uv run pytest tests/test_routers/test_settings.py -v
```

Expected: 全テスト PASS。

- [ ] **Step 10: コミット**

```bash
git add app/pipeline/runner.py app/routers/settings.py tests/test_routers/test_settings.py
git commit -m "feat: add max_stage depth parameter to run_daily_pipeline"
```

---

### Task 2: フロントエンド — チェックボックスUI

**Files:**
- Modify: `app/templates/dashboard.html` (手動実行セクション)

- [ ] **Step 1: 手動実行セクションを置き換える**

`app/templates/dashboard.html` の手動実行セクション（`<!-- 手動実行 -->` から閉じ `</div>` まで）を以下に置き換える:

```html
    <!-- 手動実行 -->
    <div class="bg-gray-900 border border-gray-800 rounded-lg p-3 space-y-2">
      <h2 class="text-xs font-semibold text-gray-400 uppercase tracking-wide">手動実行</h2>
      <div class="space-y-1">
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" id="stage1" checked class="accent-blue-500" onchange="cascadeStages(1)">
          <span class="text-xs text-gray-300">① 株価取得・急落検知</span>
        </label>
        <label class="flex items-center gap-2 cursor-pointer pl-3">
          <input type="checkbox" id="stage2" checked class="accent-blue-500" onchange="cascadeStages(2)">
          <span class="text-xs text-gray-300">② 数値分析</span>
        </label>
        <label class="flex items-center gap-2 cursor-pointer pl-6">
          <input type="checkbox" id="stage3" checked class="accent-blue-500" onchange="cascadeStages(3)">
          <span class="text-xs text-gray-300">③ ニュース取得</span>
        </label>
        <label class="flex items-center gap-2 cursor-pointer pl-9">
          <input type="checkbox" id="stage4" checked class="accent-blue-500" onchange="cascadeStages(4)">
          <span class="text-xs text-gray-300">④ AI問診</span>
        </label>
      </div>
      <input type="date" id="pipeline-date"
             class="w-full bg-gray-800 border border-gray-700 rounded px-1.5 py-1 text-xs text-center
                    focus:outline-none focus:border-blue-500 text-gray-200">
      <input type="hidden" id="pipeline-max-stage" name="max_stage" value="4">
      <button
        hx-post="/settings/run-pipeline"
        hx-include="#pipeline-date,#pipeline-max-stage"
        hx-target="#pipeline-status-panel"
        hx-swap="outerHTML"
        hx-indicator="#run-spinner"
        class="w-full bg-gray-700 hover:bg-gray-600 text-white text-xs font-medium py-1.5 rounded-lg transition-colors flex items-center justify-center gap-2">
        <span id="run-spinner" class="htmx-indicator">
          <svg class="animate-spin h-3 w-3 text-white" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
          </svg>
        </span>
        実行
      </button>
      <button
        hx-post="/settings/run-news-refresh"
        hx-target="#news-status-panel"
        hx-swap="outerHTML"
        hx-indicator="#news-spinner"
        class="w-full bg-gray-700 hover:bg-gray-600 text-white text-xs font-medium py-1.5 rounded-lg transition-colors flex items-center justify-center gap-2">
        <span id="news-spinner" class="htmx-indicator">
          <svg class="animate-spin h-3 w-3 text-white" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
          </svg>
        </span>
        ニュース更新
      </button>
    </div>
```

- [ ] **Step 2: cascadeStages JS 関数を追加**

`app/templates/dashboard.html` の末尾 `{% endblock %}` の直前にある `<script>` ブロック（`updateLLMVisibility` を含むブロック）に `cascadeStages` 関数を追加する:

```javascript
function cascadeStages(n) {
  const checked = document.getElementById('stage' + n).checked;
  for (let i = 1; i <= 4; i++) {
    if (checked && i < n) document.getElementById('stage' + i).checked = true;
    if (!checked && i > n) document.getElementById('stage' + i).checked = false;
  }
  let max = 0;
  for (let i = 1; i <= 4; i++) {
    if (document.getElementById('stage' + i).checked) max = i;
  }
  document.getElementById('pipeline-max-stage').value = max || 1;
}
```

- [ ] **Step 3: ブラウザで動作確認**

`uv run uvicorn app.main:app --reload` でサーバーを起動し、`http://localhost:8000` を開いて以下を確認:

1. 手動実行セクションにチェックボックスが4つ表示され、全てチェック済み
2. ④ のチェックをはずす → ③④ がはずれる（②以上は変わらない）
   - 確認ポイント: ④のみはずしても②③は影響なし。ただし③をはずすと④もはずれる
3. ① をはずす → ①②③④ 全てはずれる
4. ③ をチェック → ①② が自動でチェックされる
5. 「実行」ボタンをクリック → `#pipeline-status-panel` が更新される（ネットワーク接続不要、エラーでも status panel が返ってくればOK）
6. 「ニュース更新」ボタンをクリック → `#news-status-panel` が更新される

- [ ] **Step 4: 全テストが通ることを確認**

```
uv run pytest -v
```

Expected: 全テスト PASS。

- [ ] **Step 5: コミット**

```bash
git add app/templates/dashboard.html
git commit -m "feat: replace pipeline/news buttons with cascading stage checkboxes"
```

---

## 検証チェックリスト（完了後）

- [ ] デフォルト（全チェック）で実行 → 従来と同じ全ステージ動作
- [ ] ①のみチェックで実行 → 株価取得・急落検知のみで早期リターン
- [ ] ①②チェックで実行 → 数値分析まで完了して早期リターン
- [ ] ②のチェックボックスをクリック → ①が自動チェック、③④は変わらない
- [ ] ①をはずす → ①②③④ 全てはずれる
- [ ] ニュース更新ボタンは引き続き動作する
