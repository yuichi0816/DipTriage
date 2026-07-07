# 監査指摘改修（P0+P1）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `docs/audit-2026-07-07.md` の監査指摘のうち P0（T1〜T4, T6, T18）と P1（T5, T7〜T10）を解消し、「自動実行が実際に検知する・分類が再現する・失敗に気づける・LAN に無防備でない」状態にする。

**Architecture:** 既存の FastAPI + SQLAlchemy(async) + SQLite + APScheduler 構成は変えない。横断的な変更は (1) 分類タクソノミーを `app/intelligence/taxonomy.py` に集約、(2) アクセス制御を `app/security.py` の ASGI ミドルウェア2つで追加、(3) 実行履歴を `pipeline_runs` テーブルに記録、の3点。スキーマ変更はすべて Alembic マイグレーションで行う（既存 DB は `uv run alembic upgrade head`、新規 DB は起動時 `create_all` が全カラムを作る）。

**Tech Stack:** Python 3.12+ / uv / FastAPI / SQLAlchemy 2 (async) / aiosqlite / Alembic / APScheduler / httpx / pytest (asyncio_mode=auto)

**スコープ外（後続計画）:** 監査 P2（T11〜T17: インジェクション対策・記事マスタ分離・WAL/ロック・Alembic一本化・APIキー .env 移行・β日付整列・リファクタ）は本計画の完了後に別計画書を作成する。

## Global Constraints

- テスト実行コマンドは `uv run pytest -q`（`asyncio_mode = "auto"` のため `@pytest.mark.asyncio` は不要）
- テンプレート応答は Starlette 1.0 形式 `templates.TemplateResponse(request, "name.html", context)`（request が第1引数）
- 日時は ISO 8601 **文字列**で String カラムに保存、真偽値は Integer 0/1（既存規約）
- LLM 呼び出しは必ず `app.intelligence.llm_client.generate` 経由（ollama/groq を直接呼ばない）
- コミットメッセージは既存規約 `feat:` / `fix:` / `test:` / `refactor:` プレフィックス
- UI 文言・コード内コメントは日本語（既存規約）
- **計画開始時のベースライン**: `uv run pytest -q` → `1 failed, 99 passed, 13 errors`（Task 0 で修復する。Task 0 完了までは新規タスクに着手しない）

---

### Task 0: テストベースライン修復（既存の failed/errors をゼロにする）

現状、`tests/test_routers/test_settings.py` が旧モデルのカラム `market_scope`（現在は `include_nikkei225` 等4フラグに分割済み）を参照して 13 errors、`tests/test_intelligence/test_diagnosis.py::test_build_diagnosis_prompt_with_meta` が旧属性 `meta.company_name`（現在は `name_ja` / `name`）を参照して 1 failed。TDD の前提となる緑のベースラインを作る。

**Files:**
- Modify: `tests/test_routers/test_settings.py`
- Modify: `tests/test_intelligence/test_diagnosis.py`

**Interfaces:**
- Consumes: `AppSettings`（`app/models/settings.py` — `include_nikkei225` / `include_standard` / `include_growth` / `include_sp500` 各 Integer 0/1）、`StockMeta.name_ja` / `.name`
- Produces: なし（テストのみ）

- [ ] **Step 1: 失敗を確認する**

Run: `uv run pytest tests/test_routers/test_settings.py tests/test_intelligence/test_diagnosis.py -q`
Expected: `TypeError: 'market_scope' is an invalid keyword argument` による 13 errors と、`test_build_diagnosis_prompt_with_meta` の 1 failed

- [ ] **Step 2: test_settings.py の fixture を現行モデルに合わせる**

`tests/test_routers/test_settings.py` の `db_session` fixture 内、

```python
        s.add(AppSettings(id=1, auto_fetch_enabled=1, market_scope="japan_and_sp500",
                          pipeline_hour=7, pipeline_minute=0))
```

を以下に置換:

```python
        s.add(AppSettings(id=1, auto_fetch_enabled=1,
                          include_nikkei225=1, include_sp500=1,
                          include_standard=0, include_growth=0,
                          pipeline_hour=7, pipeline_minute=0))
```

- [ ] **Step 3: test_settings.py 内の残りの market_scope 参照を全置換する**

`grep -n "market_scope" tests/test_routers/test_settings.py` で残箇所を列挙し、次の対応表で機械的に置換する（POST フォームは `save_settings` の現行シグネチャに準拠。チェックボックスは "on" 送信＝1、未送信＝0）:

| 旧コード | 新コード |
|---------|---------|
| `"market_scope": "japan_and_sp500",` | `"include_nikkei225": "on", "include_sp500": "on",` |
| `"market_scope": "japan_only",` | `"include_nikkei225": "on",` |
| `assert settings.market_scope == "japan_only"` | `assert settings.include_nikkei225 == 1`（次行に）`assert settings.include_sp500 == 0` |
| `assert settings.market_scope == "japan_and_sp500"` | `assert settings.include_nikkei225 == 1`（次行に）`assert settings.include_sp500 == 1` |

- [ ] **Step 4: test_diagnosis.py の meta 属性を現行モデルに合わせる**

`test_build_diagnosis_prompt_with_meta` を以下に置換（`build_diagnosis_prompt` は `meta.name_ja or meta.name` を使う。MagicMock のままだと `name_ja` が truthy な Mock になるため明示的に None を入れる）:

```python
def test_build_diagnosis_prompt_with_meta():
    meta = MagicMock()
    meta.name_ja = None
    meta.name = "CrowdStrike Holdings"
    meta.exchange = "NASDAQ"
    meta.sector = "Technology"

    prompt = build_diagnosis_prompt(_make_event(), None, _make_interview(), [], meta)
    assert "CrowdStrike Holdings" in prompt
    assert "NASDAQ" in prompt
    assert "Technology" in prompt
```

- [ ] **Step 5: 全テストが緑になることを確認する**

Run: `uv run pytest -q`
Expected: `113 passed`（failed / errors ゼロ）

- [ ] **Step 6: Commit**

```bash
git add tests/test_routers/test_settings.py tests/test_intelligence/test_diagnosis.py
git commit -m "test: fix stale references to market_scope and meta.company_name"
```

---

### Task 1: リポジトリ衛生（監査 T18）

**Files:**
- Delete: `gcm-diagnose.log`（Git Credential Manager の診断ログ。リポジトリに不要）
- Modify: `.gitignore`

- [ ] **Step 1: ログ削除と .gitignore 追記**

```bash
rm gcm-diagnose.log
```

`.gitignore` の末尾に追記:

```
*.log
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: remove stray gcm-diagnose.log and ignore *.log"
```

---

### Task 2: LLM 生成パラメータ固定 + タイムアウト（監査 T4 / 指摘 1-1, 3-3）

分類の再現性のため temperature=0.0 / seed=42 を固定し、ハング防止のためタイムアウト（interview 120s / diagnosis 600s）と出力上限（interview 1024 / diagnosis 4096 トークン）を設定する。

**Files:**
- Modify: `app/intelligence/ollama_client.py`
- Modify: `app/intelligence/groq_client.py`
- Modify: `app/intelligence/llm_client.py`
- Test: `tests/test_intelligence/test_ollama_client.py`
- Test: Create `tests/test_intelligence/test_groq_client.py`

**Interfaces:**
- Consumes: なし
- Produces: `ollama_client.generate(prompt: str, model: str, think: bool = False) -> tuple[str, float]`（シグネチャ不変）、`groq_client.generate(prompt: str, model: str, api_key: str = "", think: bool = False) -> tuple[str, float]`（**think 引数を追加**）。`llm_client.generate` のシグネチャは不変。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_intelligence/test_ollama_client.py` の末尾に追加:

```python
async def test_generate_sets_deterministic_options():
    mock_response = MagicMock()
    mock_response.message.content = "ok"

    with patch("app.intelligence.ollama_client.AsyncClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.chat = AsyncMock(return_value=mock_response)

        from app.intelligence.ollama_client import generate
        await generate("p", model="m")

        options = mock_instance.chat.call_args.kwargs["options"]
        assert options["temperature"] == 0.0
        assert options["seed"] == 42
        assert options["num_predict"] == 1024
        # think=False → 短いタイムアウト
        assert MockClient.call_args.kwargs["timeout"] == 120.0


async def test_generate_think_mode_uses_long_timeout_and_budget():
    mock_response = MagicMock()
    mock_response.message.content = "ok"

    with patch("app.intelligence.ollama_client.AsyncClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.chat = AsyncMock(return_value=mock_response)

        from app.intelligence.ollama_client import generate
        await generate("p", model="m", think=True)

        assert MockClient.call_args.kwargs["timeout"] == 600.0
        assert mock_instance.chat.call_args.kwargs["options"]["num_predict"] == 4096
```

`tests/test_intelligence/test_groq_client.py` を新規作成:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


async def test_generate_sets_deterministic_params():
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "ok"

    with patch("app.intelligence.groq_client.AsyncGroq") as MockGroq:
        instance = MockGroq.return_value
        instance.chat.completions.create = AsyncMock(return_value=mock_response)

        from app.intelligence.groq_client import generate
        text, elapsed = await generate("p", model="m", api_key="k")

    kwargs = instance.chat.completions.create.call_args.kwargs
    assert kwargs["temperature"] == 0.0
    assert kwargs["seed"] == 42
    assert kwargs["max_tokens"] == 1024
    assert MockGroq.call_args.kwargs["timeout"] == 120.0
    assert text == "ok"
    assert elapsed >= 0.0


async def test_generate_think_mode_uses_long_timeout_and_budget():
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "ok"

    with patch("app.intelligence.groq_client.AsyncGroq") as MockGroq:
        instance = MockGroq.return_value
        instance.chat.completions.create = AsyncMock(return_value=mock_response)

        from app.intelligence.groq_client import generate
        await generate("p", model="m", api_key="k", think=True)

    assert MockGroq.call_args.kwargs["timeout"] == 600.0
    assert instance.chat.completions.create.call_args.kwargs["max_tokens"] == 4096
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_intelligence/test_ollama_client.py tests/test_intelligence/test_groq_client.py -q`
Expected: FAIL（`KeyError: 'options'` / `TypeError: generate() got an unexpected keyword argument 'think'` 等）

- [ ] **Step 3: ollama_client.py を実装する**

`app/intelligence/ollama_client.py` 全体を以下に置換:

```python
"""Ollama AsyncClient の薄いラッパー。"""
from __future__ import annotations

import time

from ollama import AsyncClient

from app.config import OLLAMA_HOST, OLLAMA_MODEL_INTERVIEW

# 分類の再現性のため生成パラメータを固定する（監査 1-1）
_BASE_OPTIONS = {"temperature": 0.0, "seed": 42}


async def generate(
    prompt: str,
    model: str = OLLAMA_MODEL_INTERVIEW,
    think: bool = False,
) -> tuple[str, float]:
    """Ollama にプロンプトを送り (response_text, elapsed_seconds) を返す。

    think=False で Qwen3 の thinking mode を無効化し高速化する（問診用）。
    think=True は診断など深い推論が必要な場合に使う。
    """
    timeout = 600.0 if think else 120.0
    num_predict = 4096 if think else 1024
    client = AsyncClient(host=OLLAMA_HOST, timeout=timeout)
    t0 = time.monotonic()
    response = await client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        think=think,
        options={**_BASE_OPTIONS, "num_predict": num_predict},
    )
    elapsed = time.monotonic() - t0
    return response.message.content, elapsed
```

- [ ] **Step 4: groq_client.py を実装する**

`app/intelligence/groq_client.py` 全体を以下に置換:

```python
"""Groq API の薄いラッパー。ollama_client と同じインターフェース。"""
from __future__ import annotations

import time

from groq import AsyncGroq


async def generate(
    prompt: str,
    model: str,
    api_key: str = "",
    think: bool = False,
) -> tuple[str, float]:
    """Groq にプロンプトを送り (response_text, elapsed_seconds) を返す。

    分類の再現性のため temperature=0 / seed 固定（監査 1-1）。
    """
    client = AsyncGroq(api_key=api_key, timeout=600.0 if think else 120.0)
    t0 = time.monotonic()
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        seed=42,
        max_tokens=4096 if think else 1024,
    )
    elapsed = time.monotonic() - t0
    return response.choices[0].message.content, elapsed
```

- [ ] **Step 5: llm_client.py の groq 呼び出しに think を渡す**

`app/intelligence/llm_client.py` の

```python
        return await groq_client.generate(
            prompt, model=groq_model, api_key=settings.groq_api_key or ""
        )
```

を以下に置換:

```python
        return await groq_client.generate(
            prompt, model=groq_model, api_key=settings.groq_api_key or "", think=think
        )
```

- [ ] **Step 6: テストが通ることを確認する**

Run: `uv run pytest tests/test_intelligence/ -q`
Expected: PASS（全件）

- [ ] **Step 7: Commit**

```bash
git add app/intelligence/ollama_client.py app/intelligence/groq_client.py app/intelligence/llm_client.py tests/test_intelligence/test_ollama_client.py tests/test_intelligence/test_groq_client.py
git commit -m "feat: fix LLM generation params (temperature=0, seed) and add timeouts"
```

---

### Task 3: 分類タクソノミー集約 + diagnosis 5クラス対応（監査 T3 / 指摘 1-2, 5-3, 5-4）

**Files:**
- Create: `app/intelligence/taxonomy.py`
- Modify: `app/intelligence/interview.py:18-25`
- Modify: `app/intelligence/diagnosis.py:37, 102, 108, 115, 133-153`
- Modify: `app/routers/dashboard.py:17, 163`
- Modify: `app/models/briefing.py`（コメントのみ）
- Test: `tests/test_intelligence/test_diagnosis.py`

**Interfaces:**
- Consumes: なし
- Produces: `taxonomy.VALID_CLASSES: set[str]`、`taxonomy.CLASS_JP: dict[str, str]`、`taxonomy.CLASS_ORDER: dict[str | None, int]`、`taxonomy.normalize_class(value: object) -> str`（無効値は "unknown" に落とす）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_intelligence/test_diagnosis.py` に追加（ファイル冒頭の import に `from unittest.mock import AsyncMock` が無ければ追加。`DipEvent`, `Briefing`, `datetime` も同様）:

```python
def test_parse_diagnosis_response_normalizes_invalid_class():
    # LLM がプロンプトの説明文を丸写ししたケース（監査 1-2）
    text = json.dumps({
        "initial_class": "accident / incident / structural / macro / unknown — 上記2軸決定木に厳密に従うこと"
    })
    parsed = parse_diagnosis_response(text)
    assert parsed["initial_class"] == "unknown"


def test_parse_diagnosis_response_accepts_structural_and_macro():
    assert parse_diagnosis_response(json.dumps({"initial_class": "structural"}))["initial_class"] == "structural"
    assert parse_diagnosis_response(json.dumps({"initial_class": "macro"}))["initial_class"] == "macro"


def test_build_diagnosis_prompt_output_example_covers_five_classes():
    prompt = build_diagnosis_prompt(_make_event(), None, _make_interview(), [])
    assert "事故型/事件型/構造型/マクロ型/不明" in prompt
    assert "この分類が誤っている可能性" in prompt
    # 説明文の丸写し事故を防ぐため、値指定は簡潔な列挙のみ
    assert "厳密に従うこと" not in prompt
```

さらに DB 保存テスト（同ファイルの既存 `db_session` fixture / `test_run_diagnosis_creates_briefing` と同じ構成で書く）:

```python
async def test_run_diagnosis_structural_maps_to_jp(db_session):
    from datetime import datetime, timezone
    from app.models.dip import DipEvent
    from app.models.briefing import Briefing

    now = datetime.now(timezone.utc).isoformat()
    event = DipEvent(
        symbol="7203.T", detected_date="2026-07-06", trigger_date="2026-07-06",
        change_pct_1d=-6.5, status="interviewed", macro_flag=0,
        created_at=now, updated_at=now,
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)

    interview = Briefing(
        dip_event_id=event.id, briefing_type="interview",
        initial_class="structural", initial_class_jp="構造型",
        situation_summary="国内販売シェアの継続的低下。",
        created_at=now, is_latest=1,
    )
    db_session.add(interview)
    await db_session.commit()

    llm_json = json.dumps({"initial_class": "structural", "confidence": "high"})
    with patch("app.intelligence.diagnosis.generate", new=AsyncMock(return_value=(llm_json, 2.0))):
        briefing = await run_diagnosis(db_session, event, None, interview, [])

    assert briefing is not None
    assert briefing.initial_class == "structural"
    assert briefing.initial_class_jp == "構造型"
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_intelligence/test_diagnosis.py -q`
Expected: FAIL（invalid class がそのまま返る / "構造型" でなく "不明" になる / プロンプト文言不一致）

- [ ] **Step 3: taxonomy.py を作成する**

```python
"""5クラス分類タクソノミーの単一情報源（監査 5-3）。"""
from __future__ import annotations

VALID_CLASSES = {"accident", "incident", "structural", "macro", "unknown"}

CLASS_JP = {
    "accident": "事故型",
    "incident": "事件型",
    "structural": "構造型",
    "macro": "マクロ型",
    "unknown": "不明",
}

# ダッシュボードの分類順ソート用（None = 問診未実施）
CLASS_ORDER = {"accident": 0, "incident": 1, "structural": 2, "macro": 3, "unknown": 4, None: 5}


def normalize_class(value: object) -> str:
    """LLM が返した分類値を検証し、無効なら unknown に落とす（監査 1-2）。"""
    return value if isinstance(value, str) and value in VALID_CLASSES else "unknown"
```

- [ ] **Step 4: interview.py の重複定義を taxonomy 参照に置換する**

`app/intelligence/interview.py` の

```python
_VALID_CLASSES = {"accident", "incident", "structural", "macro", "unknown"}
_CLASS_JP = {
    "accident": "事故型",
    "incident": "事件型",
    "structural": "構造型",
    "macro": "マクロ型",
    "unknown": "不明",
}
```

を以下に置換:

```python
from app.intelligence.taxonomy import CLASS_JP as _CLASS_JP, VALID_CLASSES as _VALID_CLASSES
```

- [ ] **Step 5: diagnosis.py を修正する**

(a) `_CLASS_JP = {"accident": "事故型", "incident": "事件型", "unknown": "不明"}` を削除し、import に追加:

```python
from app.intelligence.taxonomy import CLASS_JP as _CLASS_JP, normalize_class
```

(b) プロンプトの出力例（旧: `"■ 原因分析\n  分類: [事故型/事件型 — サブタイプ]\n  根拠: [詳細]\n\n"`）を置換:

```python
        "■ 原因分析\n  分類: [事故型/事件型/構造型/マクロ型/不明 — 事故型の場合はサブタイプも]\n  根拠: [詳細]\n\n"
```

(c) 反証見出し（旧: `"■ 反証（事件である可能性）\n  1. [反証1]\n  2. [反証2]\n  3. [反証3]\n\n"`）を置換:

```python
        "■ 反証（この分類が誤っている可能性）\n  1. [反証1]\n  2. [反証2]\n  3. [反証3]\n\n"
```

(d) JSON 例の initial_class 行（旧: `'  "initial_class": "accident / incident / structural / macro / unknown — 上記2軸決定木に厳密に従うこと",\n'`）を置換:

```python
        '  "initial_class": "accident | incident | structural | macro | unknown のいずれか1語",\n'
```

(e) `parse_diagnosis_response` の `result["moat_json"] = moat` の直後・`return result` の前に追加:

```python
    result["initial_class"] = normalize_class(result.get("initial_class"))
```

- [ ] **Step 6: dashboard.py の重複定義を置換する**

`app/routers/dashboard.py:17` の

```python
_CLASS_ORDER = {"accident": 0, "incident": 1, "structural": 2, "macro": 3, "unknown": 4, None: 5}
```

を以下に置換:

```python
from app.intelligence.taxonomy import CLASS_ORDER as _CLASS_ORDER
```

`dashboard.py:163` の `.get(..., 3)` のデフォルト値を辞書と整合させる（旧 `, 3)` → `, 5)`）:

```python
        events.sort(key=lambda e: _CLASS_ORDER.get(interviews[e.id].initial_class if e.id in interviews else None, 5))
```

- [ ] **Step 7: briefing.py の古いコメントを更新する**

`app/models/briefing.py` の

```python
    initial_class: Mapped[str | None] = mapped_column(String)     # accident | incident | unknown
    initial_class_jp: Mapped[str | None] = mapped_column(String)  # 事故型 | 事件型 | 不明
```

を以下に置換:

```python
    initial_class: Mapped[str | None] = mapped_column(String)     # accident | incident | structural | macro | unknown
    initial_class_jp: Mapped[str | None] = mapped_column(String)  # 事故型 | 事件型 | 構造型 | マクロ型 | 不明
```

- [ ] **Step 8: 全テストが通ることを確認する**

Run: `uv run pytest -q`
Expected: PASS 全件（既存の diagnosis プロンプトテストが (b)〜(d) の文言変更で落ちた場合は、そのテストのアサーションを新文言に更新する — 判断基準: 新文言が5クラスを列挙していれば正）

- [ ] **Step 9: Commit**

```bash
git add app/intelligence/taxonomy.py app/intelligence/interview.py app/intelligence/diagnosis.py app/routers/dashboard.py app/models/briefing.py tests/test_intelligence/test_diagnosis.py
git commit -m "feat: centralize 5-class taxonomy and validate diagnosis class output"
```

---

### Task 4: 自動実行の target_date 営業日解決（監査 T1 / 指摘 2-1）

07:00 JST の自動実行では JP/US とも「当日」のバーが存在せず検知が常に0件になる。自動実行時（target_date 未指定時）は「取得できたバーの最新日付」を対象日として解決する。

**Files:**
- Modify: `app/pipeline/detector.py`（純粋関数 `resolve_target_date` を追加）
- Modify: `app/pipeline/runner.py:180-181, 304-309`
- Test: `tests/test_pipeline/test_detector.py`

**Interfaces:**
- Consumes: `fetcher.PriceRow`（`.date: str` 属性を持つ NamedTuple）
- Produces: `detector.resolve_target_date(price_rows: list, requested: str | None, today: str) -> str`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_pipeline/test_detector.py` に追加:

```python
from app.pipeline.detector import resolve_target_date
from app.pipeline.fetcher import PriceRow


def _price_row(sym: str, date: str) -> PriceRow:
    return PriceRow(symbol=sym, date=date, open=None, high=None, low=None,
                    close=100.0, volume=None, adj_close=None)


class TestResolveTargetDate:
    def test_requested_date_passthrough(self):
        # 手動バックフィル指定はそのまま尊重する
        rows = [_price_row("A", "2026-07-06")]
        assert resolve_target_date(rows, "2026-07-01", "2026-07-07") == "2026-07-01"

    def test_auto_mode_uses_latest_available_bar(self):
        # 07:00 JST 実行: 当日バーはまだ無い → 前営業日に解決される（監査 2-1）
        rows = [_price_row("A", "2026-07-03"), _price_row("B", "2026-07-06")]
        assert resolve_target_date(rows, None, "2026-07-07") == "2026-07-06"

    def test_auto_mode_no_rows_falls_back_to_today(self):
        assert resolve_target_date([], None, "2026-07-07") == "2026-07-07"
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_pipeline/test_detector.py -q`
Expected: FAIL with `ImportError: cannot import name 'resolve_target_date'`

- [ ] **Step 3: detector.py に純粋関数を実装する**

`app/pipeline/detector.py` の `apply_macro_filter` の直前に追加:

```python
def resolve_target_date(price_rows: list, requested: str | None, today: str) -> str:
    """自動実行時の対象日を「取得済みバーの最新日付」に解決する（監査 2-1）。

    07:00 JST 時点では JP/US とも当日バーが存在しないため、
    requested が None（自動実行）のときは実データの最新日付を対象日とする。
    requested 指定時（手動バックフィル）はそのまま返す。
    """
    if requested:
        return requested
    dates = [r.date for r in price_rows]
    return max(dates) if dates else today
```

- [ ] **Step 4: runner.py に配線する**

(a) `run_daily_pipeline` の冒頭（旧コード）:

```python
    if target_date is None:
        target_date = datetime.now().strftime("%Y-%m-%d")
```

を以下に置換:

```python
    requested_date = target_date
    if target_date is None:
        target_date = datetime.now().strftime("%Y-%m-%d")
```

(b) detector からの import に `resolve_target_date` を追加:

```python
from app.pipeline.detector import apply_macro_filter, get_price_changes, resolve_target_date, save_dip_events, screen_dips
```

(c) `await _save_prices(session, price_rows)` と `logger.info("Saved %d price rows", ...)` の直後に追加:

```python
        # 自動実行時は対象日を実データの最新バー日付に解決する（監査 2-1）
        resolved = resolve_target_date(price_rows, requested_date, target_date)
        if resolved != target_date:
            logger.info("Auto mode: resolved target_date %s -> %s (latest bar)", target_date, resolved)
            target_date = resolved
            stats["date"] = target_date
```

- [ ] **Step 5: 全テストが通ることを確認する**

Run: `uv run pytest -q`
Expected: PASS 全件

- [ ] **Step 6: Commit**

```bash
git add app/pipeline/detector.py app/pipeline/runner.py tests/test_pipeline/test_detector.py
git commit -m "feat: resolve auto-run target_date to latest available bar date"
```

---

### Task 5: 急落判定をユニバースに限定する（監査 T6 / 指摘 2-3）

セクターETF（XLE 等）や指数（^GSPC）も stock_prices に保存されるため、現在は急落判定の対象になってしまう。`get_price_changes` の既存 `symbols` 引数に監視銘柄リストを渡す。

**Files:**
- Modify: `app/pipeline/runner.py:318`
- Test: `tests/test_pipeline/test_detector.py`

**Interfaces:**
- Consumes: `get_price_changes(session, target_date, symbols: list[str] | None)`（既存シグネチャ）
- Produces: なし

- [ ] **Step 1: detector の symbols 絞り込み契約をテストで固定する**

`tests/test_pipeline/test_detector.py` に追加:

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, StockPrice
from app.pipeline.detector import get_price_changes


async def _setup_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_get_price_changes_filters_to_universe():
    # ETF (XLE) が stock_prices にあってもユニバース指定で除外される（監査 2-3）
    engine, Session = await _setup_db()
    async with Session() as session:
        for sym in ("AAA", "XLE"):
            session.add(StockPrice(symbol=sym, date="2026-07-03", close=100.0))
            session.add(StockPrice(symbol=sym, date="2026-07-06", close=90.0))
        await session.commit()

        candidates = await get_price_changes(session, "2026-07-06", symbols=["AAA"])

    assert [c.symbol for c in candidates] == ["AAA"]
    await engine.dispose()
```

- [ ] **Step 2: テストを実行する**

Run: `uv run pytest tests/test_pipeline/test_detector.py -q`
Expected: PASS（detector の `symbols` 引数は実装済み。このテストは契約の固定）

- [ ] **Step 3: runner.py の呼び出しを修正する**

`app/pipeline/runner.py` の

```python
        candidates = await get_price_changes(session, target_date)
```

を以下に置換（`all_symbols` は同関数内で定義済みのユニバース銘柄リスト。ETF・指数を含まない）:

```python
        candidates = await get_price_changes(session, target_date, symbols=all_symbols)
```

- [ ] **Step 4: 全テストが通ることを確認する**

Run: `uv run pytest -q`
Expected: PASS 全件

- [ ] **Step 5: Commit**

```bash
git add app/pipeline/runner.py tests/test_pipeline/test_detector.py
git commit -m "fix: limit dip detection to stock universe, excluding ETFs and indices"
```

---

### Task 6: Basic 認証 + クロスオリジン POST 拒否 + バインド変更（監査 T2 / 指摘 4-1, 4-2）

**Files:**
- Create: `app/security.py`
- Modify: `app/main.py`
- Modify: `docs/manual.md:27`
- Modify: `.env.example`
- Test: Create `tests/test_routers/test_security.py`

**Interfaces:**
- Consumes: 環境変数 `DIPTRIAGE_USER`（デフォルト "diptriage"）/ `DIPTRIAGE_PASSWORD`（未設定なら認証無効 = 既存挙動維持。既存ルーターテストはこのため無変更で通る）
- Produces: `BasicAuthMiddleware(app, username: str, password: str)`、`OriginCheckMiddleware(app)`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_routers/test_security.py` を新規作成:

```python
import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from app.security import BasicAuthMiddleware, OriginCheckMiddleware


def _make_app(password: str | None = None) -> FastAPI:
    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    @app.post("/ping")
    async def ping_post():
        return {"ok": True}

    app.add_middleware(OriginCheckMiddleware)
    if password is not None:
        app.add_middleware(BasicAuthMiddleware, username="user", password=password)
    return app


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_basic_auth_rejects_without_credentials():
    async with _client(_make_app(password="pw")) as c:
        r = await c.get("/ping")
    assert r.status_code == 401
    assert "www-authenticate" in {k.lower() for k in r.headers}


async def test_basic_auth_accepts_correct_credentials():
    async with _client(_make_app(password="pw")) as c:
        r = await c.get("/ping", auth=("user", "pw"))
    assert r.status_code == 200


async def test_basic_auth_rejects_wrong_password():
    async with _client(_make_app(password="pw")) as c:
        r = await c.get("/ping", auth=("user", "WRONG"))
    assert r.status_code == 401


async def test_no_auth_when_password_not_configured():
    async with _client(_make_app(password=None)) as c:
        r = await c.get("/ping")
    assert r.status_code == 200


async def test_origin_check_blocks_cross_origin_post():
    async with _client(_make_app()) as c:
        r = await c.post("/ping", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


async def test_origin_check_allows_same_origin_post():
    async with _client(_make_app()) as c:
        r = await c.post("/ping", headers={"Origin": "http://test"})
    assert r.status_code == 200


async def test_origin_check_allows_post_without_origin_header():
    async with _client(_make_app()) as c:
        r = await c.post("/ping")
    assert r.status_code == 200
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_routers/test_security.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.security'`

- [ ] **Step 3: app/security.py を実装する**

```python
"""アクセス制御ミドルウェア（監査 4-1, 4-2）。

- BasicAuthMiddleware: DIPTRIAGE_PASSWORD 設定時のみ main.py で有効化される全ルート Basic 認証。
- OriginCheckMiddleware: Origin ヘッダ付き POST が自ホスト以外から来た場合に拒否（CSRF 対策）。
"""
from __future__ import annotations

import base64
import secrets
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class BasicAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, username: str, password: str):
        super().__init__(app)
        self._username = username
        self._password = password

    async def dispatch(self, request: Request, call_next):
        header = request.headers.get("authorization", "")
        if header.lower().startswith("basic "):
            try:
                decoded = base64.b64decode(header[6:]).decode("utf-8")
            except Exception:
                decoded = ""
            user, _, password = decoded.partition(":")
            if secrets.compare_digest(user, self._username) and secrets.compare_digest(
                password, self._password
            ):
                return await call_next(request)
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="DipTriage"'},
        )


class OriginCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "POST":
            origin = request.headers.get("origin")
            if origin:
                origin_host = urlparse(origin).netloc
                if origin_host and origin_host != request.headers.get("host", ""):
                    return Response("Forbidden: cross-origin POST", status_code=403)
        return await call_next(request)
```

- [ ] **Step 4: main.py に配線する**

`app/main.py` の import に追加:

```python
import os

from app.security import BasicAuthMiddleware, OriginCheckMiddleware
```

`app = FastAPI(title="DipTriage", lifespan=lifespan)` の直後に追加:

```python
app.add_middleware(OriginCheckMiddleware)

_AUTH_PASSWORD = os.getenv("DIPTRIAGE_PASSWORD", "")
if _AUTH_PASSWORD:
    app.add_middleware(
        BasicAuthMiddleware,
        username=os.getenv("DIPTRIAGE_USER", "diptriage"),
        password=_AUTH_PASSWORD,
    )
else:
    logger.warning(
        "DIPTRIAGE_PASSWORD が未設定のため認証なしで起動します。"
        "Tailscale IP または 127.0.0.1 へのバインドを必ず併用してください。"
    )
```

- [ ] **Step 5: manual.md と .env.example を更新する**

`docs/manual.md` の起動コマンド（旧）:

```
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-exclude ".claude" --reload-exclude "*.log" --reload-exclude "data"
```

を以下に置換:

```
# 通常運用（同一PCからのみアクセス。Tailscale 経由は `tailscale serve 8000` を併用）
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

# 開発時（コード編集の自動リロード付き）
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload --reload-exclude ".claude" --reload-exclude "*.log" --reload-exclude "data"
```

さらにその直後に注意書きを追加:

```
> **セキュリティ注意**: `--host 0.0.0.0` は LAN 全体に無認証で公開されるため使用しないこと。
> LAN 内の他端末からアクセスしたい場合は `.env` に `DIPTRIAGE_PASSWORD` を設定して
> Basic 認証を有効化した上で、Tailscale IP（100.x.x.x）にバインドする。
```

`.env.example` の末尾に追加:

```
# アクセス制御（DIPTRIAGE_PASSWORD を設定すると全ページに Basic 認証がかかる）
DIPTRIAGE_USER=diptriage
DIPTRIAGE_PASSWORD=
```

- [ ] **Step 6: 全テストが通ることを確認する**

Run: `uv run pytest -q`
Expected: PASS 全件（既存ルーターテストは DIPTRIAGE_PASSWORD 未設定のため認証の影響を受けない。ASGITransport のリクエストは Origin ヘッダを送らないため OriginCheck の影響も受けない）

- [ ] **Step 7: Commit**

```bash
git add app/security.py app/main.py docs/manual.md .env.example tests/test_routers/test_security.py
git commit -m "feat: add basic auth and cross-origin POST protection, bind to localhost"
```

---

### Task 7: pipeline_runs 実行履歴テーブル + runner 記録（監査 T5a / 指摘 3-1, 6-1, 6-2）

**Files:**
- Create: `app/models/pipeline_run.py`
- Modify: `app/models/__init__.py`
- Create: `alembic/versions/b7c8d9e0f1a2_add_pipeline_runs.py`
- Modify: `app/pipeline/runner.py`（`run_daily_pipeline` を記録ラッパー化、既存本体は `_run_pipeline_stages` に改名）
- Test: Create `tests/test_pipeline/test_runner.py`

**Interfaces:**
- Consumes: `app.database.AsyncSessionLocal`（runner が既に import 済み）
- Produces: `PipelineRun`（id / trigger: "manual"|"schedule"|"schedule-retry" / status: "running"|"done"|"error" / target_date / stats_json / error / started_at / finished_at）、`run_daily_pipeline(target_date=None, on_stage=None, max_stage=4, trigger="manual") -> dict`（**trigger 引数を追加**。既存呼び出し元は無変更で互換）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_pipeline/test_runner.py` を新規作成:

```python
"""run_daily_pipeline の実行履歴記録（pipeline_runs）のテスト"""
import pytest
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, PipelineRun


async def _setup_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_run_recorded_on_success():
    engine, Session = await _setup_db()
    fake_stats = {"date": "2026-07-06", "dips_detected": 3}

    with patch("app.pipeline.runner.AsyncSessionLocal", Session), \
         patch("app.pipeline.runner._run_pipeline_stages", new=AsyncMock(return_value=fake_stats)):
        from app.pipeline.runner import run_daily_pipeline
        stats = await run_daily_pipeline(trigger="schedule")

    assert stats == fake_stats
    async with Session() as s:
        run = (await s.execute(select(PipelineRun))).scalar_one()
    assert run.status == "done"
    assert run.trigger == "schedule"
    assert run.target_date == "2026-07-06"
    assert '"dips_detected": 3' in run.stats_json
    assert run.finished_at is not None
    await engine.dispose()


async def test_run_recorded_on_failure():
    engine, Session = await _setup_db()

    with patch("app.pipeline.runner.AsyncSessionLocal", Session), \
         patch("app.pipeline.runner._run_pipeline_stages", new=AsyncMock(side_effect=RuntimeError("boom"))):
        from app.pipeline.runner import run_daily_pipeline
        with pytest.raises(RuntimeError):
            await run_daily_pipeline()

    async with Session() as s:
        run = (await s.execute(select(PipelineRun))).scalar_one()
    assert run.status == "error"
    assert run.trigger == "manual"
    assert "boom" in run.error
    await engine.dispose()
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_pipeline/test_runner.py -q`
Expected: FAIL with `ImportError: cannot import name 'PipelineRun'`

- [ ] **Step 3: モデルを作成する**

`app/models/pipeline_run.py`:

```python
from sqlalchemy import String, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.models.stock import Base


class PipelineRun(Base):
    """パイプライン実行履歴（監査 3-1, 6-1）。"""
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trigger: Mapped[str] = mapped_column(String, nullable=False)   # manual | schedule | schedule-retry
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")  # running | done | error
    target_date: Mapped[str | None] = mapped_column(String)
    stats_json: Mapped[str | None] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(String)
    started_at: Mapped[str] = mapped_column(String, nullable=False)
    finished_at: Mapped[str | None] = mapped_column(String)
```

`app/models/__init__.py` に追記（import 群に1行 + `__all__` に `"PipelineRun",`）:

```python
from app.models.pipeline_run import PipelineRun
```

- [ ] **Step 4: Alembic マイグレーションを作成する**

`alembic/versions/b7c8d9e0f1a2_add_pipeline_runs.py`:

```python
"""add_pipeline_runs

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-07-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("target_date", sa.String(), nullable=True),
        sa.Column("stats_json", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("started_at", sa.String(), nullable=False),
        sa.Column("finished_at", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("pipeline_runs")
```

- [ ] **Step 5: runner.py をラッパー構造にする**

(a) import に追加: `import json`、models import 行に `PipelineRun` を追加（`from app.models import DipEvent, IndexPrice, NewsArticle, NumericalAnalysis, PipelineRun, StockMeta, StockPrice`）。

(b) 既存の `async def run_daily_pipeline(` を `async def _run_pipeline_stages(` に改名する（docstring・本体・引数は不変。`trigger` 引数は付けない）。

(c) `_run_pipeline_stages` の直前に記録ヘルパーと新しい公開関数を追加する:

```python
async def _record_run_start(trigger: str, target_date: str | None) -> int:
    async with AsyncSessionLocal() as session:
        run = PipelineRun(
            trigger=trigger,
            status="running",
            target_date=target_date,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run.id


async def _record_run_end(
    run_id: int, status: str, stats: dict | None = None, error: str | None = None
) -> None:
    async with AsyncSessionLocal() as session:
        run = await session.get(PipelineRun, run_id)
        if run is None:
            return
        run.status = status
        run.finished_at = datetime.now(timezone.utc).isoformat()
        if stats is not None:
            run.stats_json = json.dumps(stats, ensure_ascii=False)
            run.target_date = stats.get("date", run.target_date)
        if error is not None:
            run.error = error[:2000]
        await session.commit()


async def run_daily_pipeline(
    target_date: str | None = None,
    on_stage: Callable[[str, str, str], None] | None = None,
    max_stage: int = 4,
    trigger: str = "manual",
) -> dict:
    """パイプラインを実行し、pipeline_runs に実行履歴を記録する（監査 3-1）。"""
    run_id = await _record_run_start(trigger, target_date)
    try:
        stats = await _run_pipeline_stages(
            target_date=target_date, on_stage=on_stage, max_stage=max_stage
        )
    except Exception as e:
        await _record_run_end(run_id, "error", error=f"{type(e).__name__}: {e}")
        raise
    await _record_run_end(run_id, "done", stats=stats)
    return stats
```

- [ ] **Step 6: テストが通ることを確認する**

Run: `uv run pytest -q`
Expected: PASS 全件

- [ ] **Step 7: 既存 DB にマイグレーションを適用する**

Run: `uv run alembic upgrade head`
Expected: `Running upgrade a1b2c3d4e5f6 -> b7c8d9e0f1a2, add_pipeline_runs`

- [ ] **Step 8: Commit**

```bash
git add app/models/pipeline_run.py app/models/__init__.py alembic/versions/b7c8d9e0f1a2_add_pipeline_runs.py app/pipeline/runner.py tests/test_pipeline/test_runner.py
git commit -m "feat: record pipeline run history in pipeline_runs table"
```

---

### Task 8: スケジューラーラッパー（失敗リトライ + misfire 設定）（監査 T5b / 指摘 3-1）

**Files:**
- Modify: `app/scheduler.py`
- Test: Create `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `run_daily_pipeline(trigger=...)`（Task 7）
- Produces: `scheduled_pipeline_run() -> None`（cron 登録対象）、`retry_pipeline_run() -> None`、`reschedule_pipeline(scheduler, settings)`（シグネチャ不変・内部で `_scheduler_ref` を保持）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_scheduler.py` を新規作成:

```python
"""スケジュール実行の失敗リトライと misfire 設定のテスト"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app import scheduler as sched_mod


async def test_scheduled_run_success_does_not_schedule_retry():
    fake_scheduler = MagicMock()
    sched_mod._scheduler_ref = fake_scheduler
    with patch("app.pipeline.runner.run_daily_pipeline", new=AsyncMock(return_value={})):
        await sched_mod.scheduled_pipeline_run()
    fake_scheduler.add_job.assert_not_called()


async def test_scheduled_run_failure_schedules_one_retry():
    fake_scheduler = MagicMock()
    fake_scheduler.get_job.return_value = None
    sched_mod._scheduler_ref = fake_scheduler
    with patch("app.pipeline.runner.run_daily_pipeline", new=AsyncMock(side_effect=RuntimeError("boom"))):
        await sched_mod.scheduled_pipeline_run()  # 例外を外に漏らさない
    assert fake_scheduler.add_job.called
    assert fake_scheduler.add_job.call_args.kwargs["id"] == "daily_pipeline_retry"


async def test_retry_run_swallows_exception():
    with patch("app.pipeline.runner.run_daily_pipeline", new=AsyncMock(side_effect=RuntimeError("boom"))):
        await sched_mod.retry_pipeline_run()  # raise しないこと


async def test_reschedule_sets_misfire_grace_and_coalesce():
    fake_scheduler = MagicMock()
    fake_scheduler.get_job.return_value = None
    settings = MagicMock(auto_fetch_enabled=1, pipeline_hour=7, pipeline_minute=0)
    await sched_mod.reschedule_pipeline(fake_scheduler, settings)
    kwargs = fake_scheduler.add_job.call_args.kwargs
    assert kwargs["misfire_grace_time"] == 3600
    assert kwargs["coalesce"] is True
    assert fake_scheduler.add_job.call_args.args[0] is sched_mod.scheduled_pipeline_run
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_scheduler.py -q`
Expected: FAIL with `AttributeError: module 'app.scheduler' has no attribute '_scheduler_ref'`

- [ ] **Step 3: scheduler.py を実装する**

`app/scheduler.py` 全体を以下に置換（`PipelineStatus` は不変）:

```python
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

logger = logging.getLogger(__name__)

# reschedule_pipeline で保持し、失敗時のリトライ予約に使う
_scheduler_ref: AsyncIOScheduler | None = None

RETRY_DELAY_MINUTES = 30


@dataclass
class PipelineStatus:
    status: str = "idle"       # idle | running | done | error
    stage: str = ""
    progress: str = ""
    message: str = ""
    updated_at: datetime | None = None


async def scheduled_pipeline_run() -> None:
    """cron からの実行。失敗時は RETRY_DELAY_MINUTES 後に1回だけリトライを予約する（監査 3-1）。"""
    from app.pipeline.runner import run_daily_pipeline

    try:
        await run_daily_pipeline(trigger="schedule")
    except Exception:
        logger.exception("Scheduled pipeline failed; retrying once in %d min", RETRY_DELAY_MINUTES)
        if _scheduler_ref is not None and _scheduler_ref.get_job("daily_pipeline_retry") is None:
            _scheduler_ref.add_job(
                retry_pipeline_run,
                DateTrigger(run_date=datetime.now() + timedelta(minutes=RETRY_DELAY_MINUTES)),
                id="daily_pipeline_retry",
            )


async def retry_pipeline_run() -> None:
    """1回限りのリトライ。再失敗しても次のスケジュールまで諦める。"""
    from app.pipeline.runner import run_daily_pipeline

    try:
        await run_daily_pipeline(trigger="schedule-retry")
    except Exception:
        logger.exception("Pipeline retry failed; giving up until next schedule")


async def reschedule_pipeline(scheduler: AsyncIOScheduler, settings) -> None:
    """DB設定に基づいてスケジューラーを再設定する。"""
    global _scheduler_ref
    _scheduler_ref = scheduler

    if scheduler.get_job("daily_pipeline"):
        scheduler.remove_job("daily_pipeline")
    if settings.auto_fetch_enabled:
        scheduler.add_job(
            scheduled_pipeline_run,
            CronTrigger(hour=settings.pipeline_hour, minute=settings.pipeline_minute, timezone="Asia/Tokyo"),
            id="daily_pipeline",
            misfire_grace_time=3600,
            coalesce=True,
        )
        logger.info("Pipeline scheduled at %02d:%02d JST", settings.pipeline_hour, settings.pipeline_minute)
    else:
        logger.info("Auto-fetch disabled; no pipeline scheduled")
```

- [ ] **Step 4: 全テストが通ることを確認する**

Run: `uv run pytest -q`
Expected: PASS 全件

- [ ] **Step 5: Commit**

```bash
git add app/scheduler.py tests/test_scheduler.py
git commit -m "feat: wrap scheduled pipeline with error handling, one-shot retry, misfire grace"
```

---

### Task 9: ダッシュボードに最終実行結果を表示（監査 T5c / 指摘 3-1, 6-3）

**Files:**
- Modify: `app/routers/dashboard.py`
- Modify: `app/templates/dashboard.html`
- Test: Create `tests/test_routers/test_dashboard.py`

**Interfaces:**
- Consumes: `PipelineRun`（Task 7）
- Produces: テンプレートコンテキスト `last_run: PipelineRun | None`、`last_run_stats: dict`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_routers/test_dashboard.py` を新規作成（fixture 構成は `tests/test_routers/test_settings.py` と同型）:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from unittest.mock import MagicMock

from app.models.stock import Base
from app.models.settings import AppSettings
from app.models.pipeline_run import PipelineRun
from app.main import app
from app.database import get_db
from app.scheduler import PipelineStatus


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        s.add(AppSettings(id=1))
        s.add(PipelineRun(
            trigger="schedule", status="done", target_date="2026-07-06",
            stats_json='{"date": "2026-07-06", "dips_detected": 2}',
            started_at="2026-07-06T22:00:00+00:00",
            finished_at="2026-07-06T22:15:00+00:00",
        ))
        await s.commit()
        yield s
    await engine.dispose()


@pytest.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.state.pipeline_status = PipelineStatus()
    app.state.news_status = PipelineStatus()
    app.state.scheduler = MagicMock()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_dashboard_shows_last_run_summary(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert "最終実行" in response.text
    assert "検知 2 件" in response.text
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_routers/test_dashboard.py -q`
Expected: FAIL（"最終実行" がレスポンスに含まれない）

- [ ] **Step 3: dashboard.py に最終実行の取得を追加する**

(a) import に追加: `import json`、`from app.models.pipeline_run import PipelineRun`

(b) 設定取得ブロック（`# 設定` コメントの前）に追加:

```python
    # 最終パイプライン実行（監査 3-1: 失敗・0件検知の可視化）
    run_r = await session.execute(
        select(PipelineRun).order_by(desc(PipelineRun.id)).limit(1)
    )
    last_run = run_r.scalar_one_or_none()
    last_run_stats: dict = {}
    if last_run and last_run.stats_json:
        try:
            last_run_stats = json.loads(last_run.stats_json)
        except ValueError:
            last_run_stats = {}
```

(c) `templates.TemplateResponse` のコンテキスト辞書に追加:

```python
        "last_run": last_run,
        "last_run_stats": last_run_stats,
```

- [ ] **Step 4: dashboard.html にパネルを追加する**

`app/templates/dashboard.html` で `hx-get="/settings/pipeline-status"` を持つ要素（409行付近）を探し、その**直前**に挿入:

```html
      <!-- 最終実行結果（監査 3-1） -->
      <div class="mb-2 text-xs rounded border px-3 py-2
                  {% if last_run and (last_run.status == 'error' or last_run_stats.get('dips_detected', -1) == 0) %}border-amber-600 text-amber-300{% else %}border-gray-700 text-gray-400{% endif %}">
        {% if last_run %}
          最終実行: {{ last_run.started_at[:16].replace('T', ' ') }} UTC /
          {{ {'manual': '手動', 'schedule': '自動', 'schedule-retry': '自動(再試行)'}.get(last_run.trigger, last_run.trigger) }} /
          {% if last_run.status == 'running' %}
            実行中
          {% elif last_run.status == 'error' %}
            ⚠ 失敗: {{ last_run.error }}
          {% else %}
            完了 — 検知 {{ last_run_stats.get('dips_detected', '?') }} 件
            {% if last_run_stats.get('dips_detected') == 0 %}（⚠ 0件 — 対象日にデータがあるか確認）{% endif %}
          {% endif %}
        {% else %}
          パイプラインはまだ実行されていません
        {% endif %}
      </div>
```

- [ ] **Step 5: テストが通ることを確認する**

Run: `uv run pytest -q`
Expected: PASS 全件

- [ ] **Step 6: Commit**

```bash
git add app/routers/dashboard.py app/templates/dashboard.html tests/test_routers/test_dashboard.py
git commit -m "feat: show last pipeline run result on dashboard with 0-hit warning"
```

---

### Task 10: published_at の ISO 8601 正規化（監査 T7 / 指摘 2-4）

RFC 2822 文字列（"Mon, 06 Jul 2026 …"）のまま保存すると `ORDER BY published_at DESC` が時系列にならず「最新10件」の選択が壊れる。保存時に UTC ISO 8601 に正規化し、既存レコードをデータマイグレーションで変換する。

**Files:**
- Modify: `app/intelligence/news_fetcher.py`
- Create: `alembic/versions/c8d9e0f1a2b3_normalize_published_at.py`
- Test: `tests/test_intelligence/test_news_fetcher.py`

**Interfaces:**
- Consumes: なし
- Produces: `news_fetcher.normalize_published_at(published: str | None) -> str | None`（RFC 2822 / ISO → UTC ISO 8601、変換不能は None）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_intelligence/test_news_fetcher.py` に追加:

```python
from app.intelligence.news_fetcher import normalize_published_at


class TestNormalizePublishedAt:
    def test_rfc2822_to_iso_utc(self):
        assert normalize_published_at("Mon, 06 Jul 2026 12:34:56 +0900") == "2026-07-06T03:34:56+00:00"

    def test_iso_input_normalized_to_utc(self):
        assert normalize_published_at("2026-07-06T03:34:56+00:00") == "2026-07-06T03:34:56+00:00"

    def test_naive_datetime_assumed_utc(self):
        assert normalize_published_at("2026-07-06T03:34:56") == "2026-07-06T03:34:56+00:00"

    def test_none_returns_none(self):
        assert normalize_published_at(None) is None

    def test_garbage_returns_none(self):
        assert normalize_published_at("not a date") is None
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_intelligence/test_news_fetcher.py -q`
Expected: FAIL with `ImportError: cannot import name 'normalize_published_at'`

- [ ] **Step 3: news_fetcher.py に実装する**

(a) `classify_before_trigger` の直前に追加:

```python
def normalize_published_at(published: str | None) -> str | None:
    """RSS の公開日時を UTC ISO 8601 文字列に正規化する（監査 2-4）。

    文字列ソートで時系列順になることを保証する。変換不能なら None。
    """
    if not published:
        return None
    try:
        try:
            dt = parsedate_to_datetime(published)
        except Exception:
            dt = datetime.fromisoformat(published)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return None
```

(b) `fetch_and_save_news` の NewsArticle 生成部で published_at を正規化する。旧:

```python
            published_at=raw["published_at"],
            fetched_at=now,
            content_hash=compute_content_hash(raw["title"], url),
            is_duplicate=0,
            before_trigger=classify_before_trigger(raw["published_at"], event.trigger_date),
```

新（`published` 変数を for ループ内・NewsArticle 生成の直前で定義）:

```python
            published_at=published,
            fetched_at=now,
            content_hash=compute_content_hash(raw["title"], url),
            is_duplicate=0,
            before_trigger=classify_before_trigger(published, event.trigger_date),
```

直前に:

```python
        published = normalize_published_at(raw["published_at"])
```

- [ ] **Step 4: データマイグレーションを作成する**

`alembic/versions/c8d9e0f1a2b3_normalize_published_at.py`:

```python
"""normalize_published_at

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-07-07 00:00:00.000000

既存 news_articles.published_at（RFC 2822 文字列）を UTC ISO 8601 に変換する。
"""
from datetime import timezone
from email.utils import parsedate_to_datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c8d9e0f1a2b3"
down_revision: Union[str, None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, published_at FROM news_articles WHERE published_at IS NOT NULL")
    ).fetchall()
    for row_id, published in rows:
        try:
            dt = parsedate_to_datetime(published)
        except Exception:
            continue  # 既に ISO 形式など、RFC 2822 でないものはそのまま
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        conn.execute(
            sa.text("UPDATE news_articles SET published_at = :p WHERE id = :i"),
            {"p": dt.astimezone(timezone.utc).isoformat(), "i": row_id},
        )


def downgrade() -> None:
    pass  # 表記の正規化のため不可逆（実害なし）
```

- [ ] **Step 5: テストとマイグレーションを実行する**

Run: `uv run pytest -q`
Expected: PASS 全件

Run: `uv run alembic upgrade head`
Expected: `Running upgrade b7c8d9e0f1a2 -> c8d9e0f1a2b3, normalize_published_at`

- [ ] **Step 6: Commit**

```bash
git add app/intelligence/news_fetcher.py alembic/versions/c8d9e0f1a2b3_normalize_published_at.py tests/test_intelligence/test_news_fetcher.py
git commit -m "fix: store published_at as UTC ISO 8601 so date ordering works"
```

---

### Task 11: ステータス巻き戻し防止 + 新着記事がある場合のみ再問診（監査 T8 / 指摘 2-5, 7-1）

**Files:**
- Modify: `app/intelligence/interview.py`（status 遷移の前進制限）
- Modify: `app/pipeline/runner.py`（`run_news_refresh` の再問診条件）
- Test: `tests/test_intelligence/test_interview.py`
- Test: `tests/test_pipeline/test_runner.py`

**Interfaces:**
- Consumes: `Briefing`、`run_interview`（既存）
- Produces: `run_news_refresh` の stats に `skipped_no_new_news: int` を追加

- [ ] **Step 1: 失敗するテストを書く（interview 側）**

`tests/test_intelligence/test_interview.py` に追加（同ファイル既存の `_setup_db` / `test_run_interview_saves_briefing_on_success` と同型）:

```python
async def test_run_interview_does_not_downgrade_diagnosed_status():
    engine, Session = await _setup_db()
    now = datetime.now(timezone.utc).isoformat()

    async with Session() as session:
        event = DipEvent(
            symbol="CRWD", detected_date="2024-07-19", trigger_date="2024-07-19",
            change_pct_1d=-11.2, status="diagnosed", macro_flag=0,
            created_at=now, updated_at=now,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)

        llm_json = json.dumps({
            "key_facts": "新着記事による再問診。",
            "intentional": False, "recoverable": True, "company_specific": None,
            "situation_summary": "続報あり。",
        })
        with patch("app.intelligence.interview.generate", new=AsyncMock(return_value=(llm_json, 1.0))):
            briefing = await run_interview(session, event, None, [])

    assert briefing is not None  # 問診結果は更新される
    async with Session() as s2:
        from sqlalchemy import select as sa_select
        refreshed = (await s2.execute(sa_select(DipEvent).where(DipEvent.id == event.id))).scalar_one()
        assert refreshed.status == "diagnosed"  # 巻き戻らない（監査 2-5）
    await engine.dispose()
```

- [ ] **Step 2: 失敗するテストを書く（runner 側）**

`tests/test_pipeline/test_runner.py` に追加:

```python
from datetime import date, datetime, timezone

from app.models import Briefing, DipEvent


async def test_news_refresh_skips_interview_when_no_new_articles():
    engine, Session = await _setup_db()
    now = datetime.now(timezone.utc).isoformat()
    today = date.today().isoformat()

    async with Session() as s:
        event = DipEvent(
            symbol="CRWD", detected_date=today, trigger_date=today,
            change_pct_1d=-8.0, macro_flag=0, status="interviewed",
            created_at=now, updated_at=now,
        )
        s.add(event)
        await s.commit()
        await s.refresh(event)
        s.add(Briefing(dip_event_id=event.id, briefing_type="interview",
                       initial_class="accident", created_at=now, is_latest=1))
        await s.commit()
        event_id = event.id

    with patch("app.pipeline.runner.AsyncSessionLocal", Session), \
         patch("app.pipeline.runner.fetch_and_save_news", new=AsyncMock(return_value=[])), \
         patch("app.pipeline.runner.run_interview", new=AsyncMock()) as mock_interview:
        from app.pipeline.runner import run_news_refresh
        stats = await run_news_refresh(days=5)

    mock_interview.assert_not_called()  # 新着ゼロ + 問診済み → スキップ（監査 7-1）
    assert stats["skipped_no_new_news"] == 1
    await engine.dispose()
```

- [ ] **Step 3: テストが失敗することを確認する**

Run: `uv run pytest tests/test_intelligence/test_interview.py tests/test_pipeline/test_runner.py -q`
Expected: FAIL（status が "interviewed" に巻き戻る / run_interview が呼ばれてしまう）

- [ ] **Step 4: interview.py の status 遷移を制限する**

`app/intelligence/interview.py` の

```python
        event.status = "interviewed"
        event.updated_at = now
```

を以下に置換:

```python
        # 診断済みイベントの再問診でステータスを巻き戻さない（監査 2-5）
        if event.status != "diagnosed":
            event.status = "interviewed"
        event.updated_at = now
```

- [ ] **Step 5: runner.py の run_news_refresh を修正する**

(a) models import 行に `Briefing` を追加（`from app.models import Briefing, DipEvent, ...`）。

(b) stats 初期化を拡張:

```python
    stats: dict = {"events": 0, "news_fetched": 0, "interviewed": 0, "skipped_no_new_news": 0}
```

(c) ステップ1（ニュース取得ループ）で新着件数を記録する。旧:

```python
            try:
                articles = await fetch_and_save_news(session, event)
                stats["news_fetched"] += len(articles)
            except Exception as e:
                logger.warning("News fetch failed for %s: %s", event.symbol, e)
```

新（ループ前に `new_counts: dict[int, int] = {}` を定義）:

```python
            try:
                articles = await fetch_and_save_news(session, event)
                stats["news_fetched"] += len(articles)
                new_counts[event.id] = len(articles)
            except Exception as e:
                logger.warning("News fetch failed for %s: %s", event.symbol, e)
```

(d) ステップ2（問診ループ）の先頭、`news_r = await session.execute(` の**前**に追加:

```python
            # 新着記事がなく問診済みならスキップ（監査 7-1: LLM コスト削減）
            if new_counts.get(event.id, 0) == 0:
                iw_r = await session.execute(
                    select(Briefing)
                    .where(
                        Briefing.dip_event_id == event.id,
                        Briefing.briefing_type == "interview",
                        Briefing.is_latest == 1,
                    )
                    .limit(1)
                )
                if iw_r.scalars().first() is not None:
                    stats["skipped_no_new_news"] += 1
                    continue
```

- [ ] **Step 6: 全テストが通ることを確認する**

Run: `uv run pytest -q`
Expected: PASS 全件

- [ ] **Step 7: Commit**

```bash
git add app/intelligence/interview.py app/pipeline/runner.py tests/test_intelligence/test_interview.py tests/test_pipeline/test_runner.py
git commit -m "fix: prevent status downgrade on re-interview and skip refresh without new articles"
```

---

### Task 12: 同期 I/O の非同期化（監査 T9 / 指摘 3-2）

Stage 0 の requests / yf.download と news_fetcher の feedparser がイベントループを塞ぎ、パイプライン実行中 UI が無応答になる。既存の `analyzer.py:215`（`asyncio.to_thread(fetch_fundamentals, ...)`）と同じパターンで統一する。

**Files:**
- Modify: `app/pipeline/runner.py`（`_run_pipeline_stages` 内の同期呼び出し6箇所）
- Modify: `app/intelligence/news_fetcher.py`（httpx + タイムアウト化）
- Test: `tests/test_intelligence/test_news_fetcher.py`（既存3テストの async 化）

**Interfaces:**
- Consumes: `httpx`（依存済み）
- Produces: `news_fetcher._fetch_bytes(url: str) -> bytes`（async・timeout 10s）、`fetch_rss_articles(symbol: str) -> list[dict]`（**async 化**。戻り値の形式は不変）

- [ ] **Step 1: news_fetcher の既存テストを async 版に書き換える（失敗させる）**

`tests/test_intelligence/test_news_fetcher.py` の `TestFetchRssArticles`（または相当のテスト群）を以下に置換（import に `AsyncMock` を追加）:

```python
class TestFetchRssArticles:
    async def test_returns_article_list_on_success(self):
        mock_feed = MagicMock()
        entry = MagicMock()
        entry.get = lambda key, default=None: {
            "title": "CrowdStrike outage", "link": "http://example.com/a",
            "published": "Mon, 06 Jul 2026 12:00:00 +0000",
        }.get(key, default)
        entry.source = None
        mock_feed.entries = [entry]

        with patch("app.intelligence.news_fetcher._fetch_bytes", new=AsyncMock(return_value=b"<rss/>")), \
             patch("app.intelligence.news_fetcher.feedparser.parse", return_value=mock_feed):
            from app.intelligence.news_fetcher import fetch_rss_articles
            articles = await fetch_rss_articles("CRWD")

        assert len(articles) == 1
        assert articles[0]["title"] == "CrowdStrike outage"

    async def test_returns_empty_list_on_error(self):
        with patch("app.intelligence.news_fetcher._fetch_bytes", new=AsyncMock(side_effect=Exception("err"))):
            from app.intelligence.news_fetcher import fetch_rss_articles
            assert await fetch_rss_articles("CRWD") == []

    async def test_jp_stock_uses_jp_region_url(self):
        mock_feed = MagicMock()
        mock_feed.entries = []
        with patch("app.intelligence.news_fetcher._fetch_bytes", new=AsyncMock(return_value=b"")) as mock_fetch, \
             patch("app.intelligence.news_fetcher.feedparser.parse", return_value=mock_feed):
            from app.intelligence.news_fetcher import fetch_rss_articles
            await fetch_rss_articles("7203.T")
        assert "region=JP" in mock_fetch.call_args.args[0]
```

（既存テストの entry モックが上記と異なる作りの場合は、既存のモック構造を維持したまま `patch("...feedparser.parse", ...)` の外側に `_fetch_bytes` の patch を追加し、呼び出しを `await` に変えるだけでもよい。判断基準: sync 呼び出しが残っていないこと）

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_intelligence/test_news_fetcher.py -q`
Expected: FAIL with `ImportError: cannot import name '_fetch_bytes'` 等

- [ ] **Step 3: news_fetcher.py を httpx 化する**

(a) import に追加: `import httpx`

(b) `fetch_rss_articles` を以下に置換:

```python
_RSS_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DipTriage/1.0)"}


async def _fetch_bytes(url: str) -> bytes:
    """タイムアウト付きで RSS を取得する（監査 3-2: feedparser 直 fetch はタイムアウト不能）。"""
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=_RSS_HEADERS) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


async def fetch_rss_articles(symbol: str) -> list[dict]:
    """Yahoo Finance RSS から記事リストを取得する。失敗時は空リストを返す。"""
    try:
        url = _RSS_JP.format(symbol=symbol) if symbol.endswith(".T") else _RSS_US.format(symbol=symbol)
        content = await _fetch_bytes(url)
        feed = feedparser.parse(content)
        articles = []
        for entry in feed.entries:
            source = getattr(getattr(entry, "source", None), "title", None)
            articles.append({
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "source": source,
                "published_at": entry.get("published"),
            })
        return articles
    except Exception as e:
        logger.warning("RSS fetch failed for %s: %s", symbol, e)
        return []
```

(c) `fetch_and_save_news` 内の呼び出しを await 化:

```python
    raw_articles = await fetch_rss_articles(event.symbol)
```

- [ ] **Step 4: runner.py の同期呼び出しを to_thread 化する**

(a) import に追加: `import asyncio`

(b) `_run_pipeline_stages` 内の以下6箇所を置換:

| 旧 | 新 |
|----|----|
| `nikkei = get_nikkei225_symbols()` | `nikkei = await asyncio.to_thread(get_nikkei225_symbols)` |
| `standard = get_tse_segment_symbols("スタンダード（内国株式）", "TSE Standard")` | `standard = await asyncio.to_thread(get_tse_segment_symbols, "スタンダード（内国株式）", "TSE Standard")` |
| `growth = get_tse_segment_symbols("グロース（内国株式）", "TSE Growth")` | `growth = await asyncio.to_thread(get_tse_segment_symbols, "グロース（内国株式）", "TSE Growth")` |
| `all_stocks.extend(get_sp500_symbols())` | `all_stocks.extend(await asyncio.to_thread(get_sp500_symbols))` |
| `index_rows = fetch_index_price_rows(index_syms, end_date=target_date)` | `index_rows = await asyncio.to_thread(fetch_index_price_rows, index_syms, end_date=target_date)` |
| `price_data = fetch_prices(download_symbols, days=dip_lookback_days, end_date=target_date)` | `price_data = await asyncio.to_thread(fetch_prices, download_symbols, days=dip_lookback_days, end_date=target_date)` |

- [ ] **Step 5: 全テストが通ることを確認する**

Run: `uv run pytest -q`
Expected: PASS 全件

- [ ] **Step 6: 実機で UI 応答性を確認する**

Run: `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000` を起動し、設定画面から手動パイプライン実行（ステージ1のみ）を開始。実行中にダッシュボードをリロードして応答が返ることを確認する（旧実装ではダウンロード完了まで無応答）。

- [ ] **Step 7: Commit**

```bash
git add app/pipeline/runner.py app/intelligence/news_fetcher.py tests/test_intelligence/test_news_fetcher.py
git commit -m "fix: run blocking network IO in threads and fetch RSS via httpx with timeout"
```

---

### Task 13: パース失敗の可視化（監査 T10 / 指摘 1-4, 6-4）

LLM 応答のパース失敗が空ブリーフィングとして正常保存される問題。`parse_ok` / `raw_response` カラムを追加し、UI に警告を表示、事後調査用に生応答を保存する。

**Files:**
- Modify: `app/models/briefing.py`
- Create: `alembic/versions/d9e0f1a2b3c4_add_briefing_parse_ok.py`
- Modify: `app/intelligence/diagnosis.py`
- Modify: `app/intelligence/interview.py`
- Modify: `app/templates/dip_detail.html`
- Test: `tests/test_intelligence/test_diagnosis.py`, `tests/test_intelligence/test_interview.py`

**Interfaces:**
- Consumes: `Briefing`（Task 3 までの状態）
- Produces: `Briefing.parse_ok: int`（1=正常, 0=フォールバック）、`Briefing.raw_response: str | None`。`parse_diagnosis_response` / `parse_llm_response` の戻り値 dict に `"parse_ok": int` キーを追加（既存キーは不変）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_intelligence/test_diagnosis.py` に追加:

```python
def test_parse_diagnosis_response_sets_parse_ok_flag():
    ok = parse_diagnosis_response(json.dumps({"initial_class": "accident"}))
    assert ok["parse_ok"] == 1

    broken = parse_diagnosis_response("JSONが含まれない応答テキスト")
    assert broken["parse_ok"] == 0
    assert broken["initial_class"] == "unknown"


async def test_run_diagnosis_records_raw_response_and_parse_ok(db_session):
    from datetime import datetime, timezone
    from app.models.dip import DipEvent
    from app.models.briefing import Briefing

    now = datetime.now(timezone.utc).isoformat()
    event = DipEvent(
        symbol="CRWD", detected_date="2026-07-06", trigger_date="2026-07-06",
        change_pct_1d=-11.2, status="interviewed", macro_flag=0,
        created_at=now, updated_at=now,
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)

    interview = Briefing(
        dip_event_id=event.id, briefing_type="interview",
        initial_class="accident", initial_class_jp="事故型",
        created_at=now, is_latest=1,
    )
    db_session.add(interview)
    await db_session.commit()

    with patch("app.intelligence.diagnosis.generate", new=AsyncMock(return_value=("壊れた応答", 1.0))):
        briefing = await run_diagnosis(db_session, event, None, interview, [])

    assert briefing is not None
    assert briefing.parse_ok == 0
    assert briefing.raw_response == "壊れた応答"
```

`tests/test_intelligence/test_interview.py` に追加:

```python
async def test_run_interview_records_parse_failure():
    engine, Session = await _setup_db()
    now = datetime.now(timezone.utc).isoformat()

    async with Session() as session:
        event = DipEvent(
            symbol="CRWD", detected_date="2024-07-19", trigger_date="2024-07-19",
            change_pct_1d=-11.2, status="analyzed", macro_flag=0,
            created_at=now, updated_at=now,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)

        with patch("app.intelligence.interview.generate", new=AsyncMock(return_value=("JSONなし応答", 1.0))):
            briefing = await run_interview(session, event, None, [])

    assert briefing is not None
    assert briefing.parse_ok == 0
    assert briefing.raw_response == "JSONなし応答"
    assert briefing.initial_class == "unknown"
    await engine.dispose()
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `uv run pytest tests/test_intelligence/test_diagnosis.py tests/test_intelligence/test_interview.py -q`
Expected: FAIL with `KeyError: 'parse_ok'` / `TypeError: 'parse_ok' is an invalid keyword argument`

- [ ] **Step 3: モデルとマイグレーションを追加する**

`app/models/briefing.py` の `is_latest` 行の直後に追加:

```python
    # 1=LLM応答のパース成功, 0=フォールバック値で保存（監査 1-4）
    parse_ok: Mapped[int] = mapped_column(Integer, default=1)
    # パース失敗の事後調査用に LLM 生応答を保存（監査 6-4）
    raw_response: Mapped[str | None] = mapped_column(String)
```

`alembic/versions/d9e0f1a2b3c4_add_briefing_parse_ok.py`:

```python
"""add_briefing_parse_ok

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-07-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("briefings", sa.Column("parse_ok", sa.Integer(), nullable=True))
    op.add_column("briefings", sa.Column("raw_response", sa.String(), nullable=True))
    op.execute("UPDATE briefings SET parse_ok = 1 WHERE parse_ok IS NULL")


def downgrade() -> None:
    op.drop_column("briefings", "raw_response")
    op.drop_column("briefings", "parse_ok")
```

- [ ] **Step 4: diagnosis.py に parse_ok を実装する**

(a) `parse_diagnosis_response` の `result["initial_class"] = normalize_class(...)` の直後に追加:

```python
    result["parse_ok"] = 1 if parsed else 0
```

(b) `run_diagnosis` の `Briefing(` 生成に2フィールド追加（`is_latest=1,` の直前）:

```python
            parse_ok=parsed.get("parse_ok", 1),
            raw_response=text,
```

- [ ] **Step 5: interview.py に parse_ok を実装する**

(a) `parse_llm_response` の戻り値型注釈を `dict[str, str]` から `dict` に変更し、`_fallback` を以下に置換:

```python
    _fallback = {"situation_summary": "（解析失敗）", "initial_class": "unknown", "parse_ok": 0}
```

成功パスの `return { ... }` に追加:

```python
            "parse_ok": 1,
```

(b) `run_interview` の `Briefing(` 生成に2フィールド追加（`is_latest=1,` の直前）:

```python
            parse_ok=parsed.get("parse_ok", 1),
            raw_response=text,
```

- [ ] **Step 6: dip_detail.html に警告バッジを追加する**

`app/templates/dip_detail.html` の診断見出し `<h2 class="text-sm font-semibold text-gray-400">診断ブリーフィング</h2>`（205-210行付近）の直後に追加:

```html
      {% if diagnosis.parse_ok == 0 %}
      <span class="text-xs text-amber-400 border border-amber-600 rounded px-2 py-0.5">
        ⚠ AI応答の解析に失敗（結果は不完全・再実行を推奨）
      </span>
      {% endif %}
```

- [ ] **Step 7: テストとマイグレーションを実行する**

Run: `uv run pytest -q`
Expected: PASS 全件（既存の parse テストが dict 全体比較をしている場合は `parse_ok` キーを期待値に追加する）

Run: `uv run alembic upgrade head`
Expected: `Running upgrade c8d9e0f1a2b3 -> d9e0f1a2b3c4, add_briefing_parse_ok`

- [ ] **Step 8: Commit**

```bash
git add app/models/briefing.py alembic/versions/d9e0f1a2b3c4_add_briefing_parse_ok.py app/intelligence/diagnosis.py app/intelligence/interview.py app/templates/dip_detail.html tests/test_intelligence/test_diagnosis.py tests/test_intelligence/test_interview.py
git commit -m "feat: track LLM parse failures with parse_ok flag and raw response storage"
```

---

## 完了確認（全タスク後）

- [ ] `uv run pytest -q` — 全件 PASS（Task 0 時点の 113 件 + 本計画で追加した約 30 件）
- [ ] `uv run alembic upgrade head` — `d9e0f1a2b3c4` まで適用済み
- [ ] 実機確認: `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000` で起動し、(1) ダッシュボードに「最終実行」パネルが表示される、(2) 手動パイプライン実行中も UI が応答する、(3) `DIPTRIAGE_PASSWORD` を設定して再起動すると Basic 認証が要求される
- [ ] `docs/audit-2026-07-07.md` の P0/P1 チェック — T1〜T10, T6, T18 の各指摘が解消されていることを突き合わせ

## 後続計画（本計画のスコープ外）

監査 P2 の残タスクは本計画完了後に `docs/superpowers/plans/` に別計画書を作成する:
T11 プロンプトインジェクション対策 / T12 記事マスタ・リンクテーブル分離 / T13 並行実行ロック + SQLite WAL / T14 Alembic 一本化（create_all 廃止） / T15 Groq APIキーの .env 移行 + DB の OneDrive 外移動 / T16 β・相関の日付整列と σ の急落日除外 / T17 runner Stage 0 共通化・dashboard N+1 解消
