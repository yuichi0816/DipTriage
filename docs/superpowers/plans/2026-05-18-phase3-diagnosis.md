# Phase 3 — Diagnosis (反証・moat 評価) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 問診済み急落イベントに対し、Qwen3 35b + think=True でオンデマンド診断（事故サブ分類・moat 評価・反証3件）を実行し、結果を診断ブリーフィングとして Web UI に表示する。

**Architecture:** `app/intelligence/diagnosis.py` が純粋関数（`build_diagnosis_prompt`, `parse_diagnosis_response`）と非同期関数（`run_diagnosis`）を提供する。`app/routers/dip_detail.py` に POST `/dip/{id}/diagnose` を追加し HTMX から呼び出す。結果は `Briefing`（briefing_type="diagnosis"）として SQLite に保存する。マイグレーション不要（診断用フィールドは Phase 1 で定義済み）。

**Tech Stack:** FastAPI + SQLAlchemy 2.x async + Jinja2 + HTMX + Ollama (qwen3.6:35b, think=True) + pytest + aiosqlite

---

## File Structure

| ファイル | 操作 | 責務 |
|---|---|---|
| `docs/superpowers/specs/2026-05-18-phase3-diagnosis-design.md` | 新規 | 診断機能の設計書 |
| `app/intelligence/diagnosis.py` | 新規 | プロンプト生成・レスポンスパース・診断実行 |
| `tests/test_intelligence/test_diagnosis.py` | 新規 | diagnosis.py の単体・統合テスト（16件以上） |
| `app/routers/dip_detail.py` | 修正 | POST `/dip/{id}/diagnose` エンドポイント追加 |
| `app/templates/partials/diagnosis_result.html` | 新規 | HTMX レスポンス用の診断結果パーシャル |
| `app/templates/dip_detail.html` | 修正 | HTMX 診断ボタン有効化 + `#diagnosis-container` 追加 |

---

### Task 0: 設計書を作成する

**Files:**
- Create: `docs/superpowers/specs/2026-05-18-phase3-diagnosis-design.md`
- Create: `docs/superpowers/plans/2026-05-18-phase3-diagnosis.md` (このファイル自身のコピー)

- [ ] **Step 1: 設計書を書く**

`docs/superpowers/specs/2026-05-18-phase3-diagnosis-design.md` を以下の内容で作成する：

```markdown
# Phase 3 設計書 — 診断（反証・moat 評価）

**日付**: 2026-05-18
**対象フェーズ**: Phase 3（第4段階：診断）
**前提**: Phase 2（問診・LLM 統合）実装完了済み

---

## 概要

Phase 2 で「事故型か事件型か」の初期分類が完了した後、ユーザーがオンデマンドで深い分析を行う段階。
Qwen3 35b + think=True を使用し、事故のサブ分類・moat 評価・反証（事件である可能性3件）を含む
診断ブリーフィングを生成する。日次自動実行ではなく、ユーザーが詳細画面の「診断を実行」ボタンを
押すことで起動する。

---

## スコープ

| 対象 | 内容 |
|---|---|
| LLM 呼び出し | qwen3.6:35b + think=True によるフル診断 |
| 事故サブ分類 | システム障害 / 一時的決算ミス / 製品リコール・品質問題 / 経営発言・炎上 / 自然災害・外的要因 |
| moat 評価 | スイッチングコスト / ネットワーク効果 / 規制参入障壁 / ブランド依存度 |
| 反証ステップ | 「事件である可能性」を3件列挙 |
| Web UI | HTMX 経由のオンデマンド診断ボタン + 結果表示 |

---

## ファイル構成

```
app/
  intelligence/
    diagnosis.py          — build_diagnosis_prompt / parse_diagnosis_response / run_diagnosis
  routers/
    dip_detail.py         — POST /dip/{id}/diagnose エンドポイント追加
  templates/
    dip_detail.html       — 診断ボタン（HTMX）+ diagnosis-container
    partials/
      diagnosis_result.html — HTMX レスポンス用パーシャル
tests/
  test_intelligence/
    test_diagnosis.py     — 単体テスト + 統合テスト
```

---

## アーキテクチャ

### 各モジュールの責務

| モジュール | 責務 |
|---|---|
| `build_diagnosis_prompt()` | event・analysis・interview・articles・meta を組み合わせてプロンプトを生成（純粋関数） |
| `parse_diagnosis_response()` | LLM の JSON レスポンスから診断フィールドを抽出（純粋関数） |
| `run_diagnosis()` | LLM 呼び出し + Briefing 保存 + status 更新を行う非同期関数 |
| POST `/dip/{id}/diagnose` | HTMX エンドポイント。run_diagnosis() を呼び出しパーシャル HTML を返す |

---

## データフロー

```
dip_detail.html（ブラウザ）
  └─ HTMX POST /dip/{id}/diagnose
       └─ dip_detail.py router
            ├─ DB: DipEvent, NumericalAnalysis, Briefing(interview), NewsArticle を取得
            ├─ diagnosis.run_diagnosis()
            │    ├─ build_diagnosis_prompt()
            │    ├─ ollama_client.generate(prompt, model=OLLAMA_MODEL_DIAGNOSIS, think=True)
            │    └─ parse_diagnosis_response() → Briefing(diagnosis) を DB に保存
            └─ TemplateResponse(request, "partials/diagnosis_result.html", {...})
```

---

## プロンプト設計

### 入力フォーマット

プロンプトは以下のセクションで構成する：

1. **銘柄情報**: symbol, company_name, exchange, sector, trigger_date
2. **数値サマリー**: change_pct_1d/5d, volume_ratio_20d, is_idiosyncratic, beta_1y, sector_corr_90d, per, pbr
3. **問診結果**: initial_class_jp, situation_summary（Phase 2 の出力を再利用）
4. **関連ニュース**: articles[:10]（[急落前]/[急落後] ラベル付き、最大10件）
5. **出力フォーマット例**: 診断ブリーフィングの期待フォーマットを示す（数値を事前埋め込み）
6. **JSON 出力指示**: 構造化フィールドを JSON で返させる

### JSON レスポンス形式

```json
{
  "initial_class": "accident|incident|unknown",
  "accident_subtype": "システム障害|一時的決算ミス|製品リコール・品質問題|経営発言・炎上|自然災害・外的要因|null",
  "moat_switching_cost": "高|中|低",
  "moat_network_effect": "有|無",
  "moat_regulatory_barrier": "高|中|低",
  "moat_brand_dependency": "高|中|低",
  "moat_summary": "moat総合評価（毀損度を含む1〜2文）",
  "similar_cases": "類似ケース1〜2件（フリーテキスト）",
  "counterarguments": "1. 反証1\n2. 反証2\n3. 反証3",
  "oversight_risks": "見落としリスク",
  "confidence": "high|medium|low",
  "confidence_reason": "確信度の根拠（1文）",
  "full_text": "━━ 診断ブリーフィング ━━\n..."
}
```

### moat_json の格納形式

`parse_diagnosis_response()` が上記 JSON から以下を生成して `Briefing.moat_json` に格納：

```json
{
  "switching_cost": "高",
  "network_effect": "有",
  "regulatory_barrier": "中",
  "brand_dependency": "中",
  "summary": "毀損度 低。障害では顧客が容易に離脱しない構造。"
}
```

---

## エラーハンドリング

| 状況 | 挙動 |
|---|---|
| 問診未完了（status が interviewed/diagnosed 以外） | 400 を返し「問診が完了していません」を表示 |
| Ollama 未起動 | generate() 例外をキャッチ。run_diagnosis() は None を返す。UI に「Ollama が起動していません」を表示 |
| JSON パース失敗 | _FALLBACK 値で Briefing を作成。full_text は空文字列 |
| 既に診断済み（diagnosis Briefing 存在） | 既存を is_latest=0 に更新し新規レコードを is_latest=1 で作成 |
| session.rollback() 問題 | LLM 呼び出しと DB 書き込みを別の try/except に分割。LLM 失敗時は rollback せず return None |

---

## UI 変更

### dip_detail.html — HTMX 診断ボタン

```html
<div id="diagnosis-container" class="mb-4">
  {% if diagnosis %}
  <!-- 診断結果表示（Phase 3 実装後） -->
  <section class="bg-gray-900 border border-gray-800 rounded-xl p-4">
    <pre class="text-xs text-gray-300 whitespace-pre-wrap font-sans leading-relaxed">
      {{ diagnosis.full_text }}
    </pre>
  </section>
  {% elif event.status in ["interviewed", "diagnosed"] %}
  <button
    hx-post="/dip/{{ event.id }}/diagnose"
    hx-target="#diagnosis-container"
    hx-swap="outerHTML"
    hx-indicator="#diagnosis-spinner"
    class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg"
  >診断を実行</button>
  <span id="diagnosis-spinner" class="htmx-indicator ml-2 text-sm text-gray-400">
    分析中（数分かかります）...
  </span>
  {% endif %}
</div>
```

### partials/diagnosis_result.html — HTMX レスポンス

HTMX POST の返り値として `#diagnosis-container` 全体を置き換えるパーシャル。
エラー時は「再試行」ボタンを表示。

---

## 既存設計との整合性

- `Briefing` モデルに診断用フィールドが Phase 1 で定義済み → **マイグレーション不要**
- `DipEvent.status = "diagnosed"` は Phase 1 で定義済み → **変更不要**
- `ollama_client.generate(prompt, model, think)` — `think=True` を渡すだけ
- `OLLAMA_MODEL_DIAGNOSIS` は `app/config.py` で定義済み
- `TemplateResponse(request, ...)` 形式（第1引数が request）— Phase 2 で確認済み

---

## スコープ外（将来フェーズ）

- TDnet 適時開示の取得（日本株）
- 再診断ボタン（is_latest の管理が必要）
- 診断履歴の一覧表示
- 確信度メトリクスのダッシュボード集計
```

- [ ] **Step 2: 計画書（このファイル）を docs/ にコピーする**

```bash
cp "C:/Users/yuich/.claude/plans/phase-3-docs-handover-phase3-md-quirky-glade.md" \
   "docs/superpowers/plans/2026-05-18-phase3-diagnosis.md"
```

- [ ] **Step 3: コミット**

```bash
git add docs/superpowers/specs/2026-05-18-phase3-diagnosis-design.md \
        docs/superpowers/plans/2026-05-18-phase3-diagnosis.md
git commit -m "docs: add Phase 3 diagnosis design spec and implementation plan"
```

---

### Task 1: `build_diagnosis_prompt()` を TDD で実装する

**Files:**
- Create: `app/intelligence/diagnosis.py`
- Create: `tests/test_intelligence/test_diagnosis.py`

- [ ] **Step 1: テストを書く**

`tests/test_intelligence/test_diagnosis.py` を新規作成：

```python
import json
import pytest
from app.intelligence.diagnosis import build_diagnosis_prompt
from app.models.analysis import NumericalAnalysis
from app.models.briefing import Briefing
from app.models.dip import DipEvent
from app.models.news import NewsArticle
from app.models.stock import StockMeta


def _make_event():
    e = DipEvent.__new__(DipEvent)
    e.symbol = "CRWD"
    e.trigger_date = "2024-07-19"
    e.change_pct_1d = -11.2
    e.change_pct_5d = -8.7
    e.status = "interviewed"
    e.macro_flag = 0
    return e


def _make_analysis():
    a = NumericalAnalysis.__new__(NumericalAnalysis)
    a.volume_ratio_20d = 4.2
    a.is_idiosyncratic = 1
    a.beta_1y = 1.12
    a.sector_corr_90d = 0.31
    a.per = 68.3
    a.pbr = 25.1
    return a


def _make_interview():
    b = Briefing.__new__(Briefing)
    b.situation_summary = "Falcon センサーの定義ファイル更新が原因の BSOD 障害"
    b.initial_class = "accident"
    b.initial_class_jp = "事故型"
    return b


def test_build_diagnosis_prompt_contains_symbol():
    prompt = build_diagnosis_prompt(_make_event(), _make_analysis(), _make_interview(), [])
    assert "CRWD" in prompt
    assert "2024-07-19" in prompt


def test_build_diagnosis_prompt_contains_numeric_data():
    prompt = build_diagnosis_prompt(_make_event(), _make_analysis(), _make_interview(), [])
    assert "-11.2%" in prompt
    assert "4.2倍" in prompt
    assert "銘柄固有" in prompt
    assert "1.12" in prompt


def test_build_diagnosis_prompt_contains_interview_result():
    prompt = build_diagnosis_prompt(_make_event(), _make_analysis(), _make_interview(), [])
    assert "事故型" in prompt
    assert "Falcon センサーの定義ファイル更新" in prompt


def test_build_diagnosis_prompt_with_articles():
    articles = []
    a1 = NewsArticle.__new__(NewsArticle)
    a1.title = "CrowdStrike global outage"
    a1.url = "https://example.com/1"
    a1.before_trigger = False
    a2 = NewsArticle.__new__(NewsArticle)
    a2.title = "IT 障害の前兆"
    a2.url = "https://example.com/2"
    a2.before_trigger = True
    articles = [a1, a2]

    prompt = build_diagnosis_prompt(_make_event(), None, _make_interview(), articles)
    assert "[急落後] CrowdStrike global outage" in prompt
    assert "[急落前] IT 障害の前兆" in prompt


def test_build_diagnosis_prompt_no_analysis_uses_na():
    prompt = build_diagnosis_prompt(_make_event(), None, _make_interview(), [])
    assert "N/A" in prompt


def test_build_diagnosis_prompt_with_meta():
    meta = StockMeta.__new__(StockMeta)
    meta.company_name = "CrowdStrike Holdings"
    meta.exchange = "NASDAQ"
    meta.sector = "Technology"

    prompt = build_diagnosis_prompt(_make_event(), None, _make_interview(), [], meta)
    assert "CrowdStrike Holdings" in prompt
    assert "NASDAQ" in prompt
    assert "Technology" in prompt


def test_build_diagnosis_prompt_requests_json_output():
    prompt = build_diagnosis_prompt(_make_event(), None, _make_interview(), [])
    assert "initial_class" in prompt
    assert "moat_switching_cost" in prompt
    assert "counterarguments" in prompt
    assert "full_text" in prompt
```

- [ ] **Step 2: テストの失敗を確認する**

```bash
uv run pytest tests/test_intelligence/test_diagnosis.py -v
```

期待結果: `ImportError: cannot import name 'build_diagnosis_prompt' from 'app.intelligence.diagnosis'`（またはファイルが存在しないエラー）

- [ ] **Step 3: `diagnosis.py` の骨格と `build_diagnosis_prompt()` を実装する**

`app/intelligence/diagnosis.py` を新規作成：

```python
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import OLLAMA_MODEL_DIAGNOSIS
from app.intelligence.ollama_client import generate
from app.models.analysis import NumericalAnalysis
from app.models.briefing import Briefing
from app.models.dip import DipEvent
from app.models.news import NewsArticle
from app.models.stock import StockMeta

logger = logging.getLogger(__name__)

_FALLBACK: dict = {
    "initial_class": "unknown",
    "accident_subtype": None,
    "moat_switching_cost": "N/A",
    "moat_network_effect": "N/A",
    "moat_regulatory_barrier": "N/A",
    "moat_brand_dependency": "N/A",
    "moat_summary": "",
    "similar_cases": "",
    "counterarguments": "",
    "oversight_risks": "",
    "confidence": "low",
    "confidence_reason": "",
    "full_text": "",
}

_CLASS_JP = {"accident": "事故型", "incident": "事件型", "unknown": "不明"}


def build_diagnosis_prompt(
    event: DipEvent,
    analysis: NumericalAnalysis | None,
    interview: Briefing,
    articles: list[NewsArticle],
    meta: StockMeta | None = None,
) -> str:
    company = meta.company_name if meta else event.symbol
    exchange = meta.exchange if meta else "N/A"
    sector = meta.sector if meta else "N/A"

    sector_label = "銘柄固有" if (analysis and analysis.is_idiosyncratic) else "セクター全体"
    vol = f"{analysis.volume_ratio_20d:.1f}" if analysis and analysis.volume_ratio_20d else "N/A"
    beta = f"{analysis.beta_1y:.2f}" if analysis and analysis.beta_1y else "N/A"
    corr = f"{analysis.sector_corr_90d:.2f}" if analysis and analysis.sector_corr_90d else "N/A"
    per = f"{analysis.per:.1f}" if analysis and analysis.per else "N/A"
    pbr = f"{analysis.pbr:.1f}" if analysis and analysis.pbr else "N/A"

    news_lines = ""
    for i, a in enumerate(articles[:10], 1):
        label = "[急落前]" if a.before_trigger else "[急落後]"
        news_lines += f"{i}. {label} {a.title}\n   {a.url}\n"
    if not news_lines:
        news_lines = "（記事なし）"

    return (
        "あなたは株式投資アナリストです。以下の情報を元に、株価急落銘柄の診断ブリーフィングをJSON形式で作成してください。\n\n"
        "## 銘柄情報\n"
        f"- シンボル: {event.symbol} / 企業名: {company} / 市場: {exchange} / セクター: {sector}\n"
        f"- 検知日: {event.trigger_date}\n\n"
        "## 数値サマリー\n"
        f"- 前日比: {event.change_pct_1d:.1f}% / 週間: {event.change_pct_5d:.1f}%\n"
        f"- 出来高異常度: {vol}倍 / セクター相対: {sector_label}\n"
        f"- β値: {beta} / ETF相関: {corr}\n"
        f"- PER: {per} / PBR: {pbr}\n\n"
        "## 問診結果\n"
        f"- 分類: {interview.initial_class_jp or '不明'}\n"
        f"- サマリー: {interview.situation_summary or '（なし）'}\n\n"
        f"## 関連ニュース\n{news_lines}\n"
        "## 出力フォーマット例\n\n"
        "━━ 診断ブリーフィング ━━\n"
        f"銘柄: {event.symbol}（{company}）  市場: {exchange}\n"
        f"検知日: {event.trigger_date}\n\n"
        "■ 数値サマリー\n"
        f"  前日比: {event.change_pct_1d:.1f}% / 週間: {event.change_pct_5d:.1f}% / 出来高異常度: {vol}倍\n"
        f"  セクター相対: {sector_label} / β値: {beta} / ETF相関: {corr}\n"
        f"  PER: {per} / PBR: {pbr}\n\n"
        "■ 原因分析\n  分類: [事故型/事件型 — サブタイプ]\n  根拠: [詳細]\n\n"
        "■ moat評価\n"
        "  スイッチングコスト: [高/中/低] / ネットワーク効果: [有/無]\n"
        "  規制参入障壁: [高/中/低] / ブランド依存度: [高/中/低]\n"
        "  → 総合: [評価]\n\n"
        "■ 類似ケース\n  [1〜2件]\n\n"
        "■ 反証（事件である可能性）\n  1. [反証1]\n  2. [反証2]\n  3. [反証3]\n\n"
        "■ 見落としリスク\n  [記入]\n\n"
        "■ 分析の確信度: [high/medium/low]\n  [根拠]\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "## 出力（JSONのみ、他のテキスト不要）\n\n"
        "```json\n"
        "{\n"
        '  "initial_class": "accident か incident か unknown",\n'
        '  "accident_subtype": "システム障害/一時的決算ミス/製品リコール・品質問題/経営発言・炎上/自然災害・外的要因 のいずれか、またはnull",\n'
        '  "moat_switching_cost": "高/中/低",\n'
        '  "moat_network_effect": "有/無",\n'
        '  "moat_regulatory_barrier": "高/中/低",\n'
        '  "moat_brand_dependency": "高/中/低",\n'
        '  "moat_summary": "moat総合評価（毀損度を含む）",\n'
        '  "similar_cases": "類似ケース1〜2件",\n'
        '  "counterarguments": "1. 反証1\\n2. 反証2\\n3. 反証3",\n'
        '  "oversight_risks": "見落としリスク",\n'
        '  "confidence": "high/medium/low",\n'
        '  "confidence_reason": "確信度の根拠（1文）",\n'
        '  "full_text": "上記フォーマット例に従い全セクションを完全に記載（省略なし）"\n'
        "}\n"
        "```"
    )


def parse_diagnosis_response(text: str) -> dict:
    pass  # Task 2 で実装


async def run_diagnosis(
    session: AsyncSession,
    event: DipEvent,
    analysis: NumericalAnalysis | None,
    interview: Briefing,
    articles: list[NewsArticle],
    meta: StockMeta | None = None,
) -> Briefing | None:
    pass  # Task 3 で実装
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
uv run pytest tests/test_intelligence/test_diagnosis.py -v -k "build"
```

期待結果: 7件 PASSED

- [ ] **Step 5: コミット**

```bash
git add app/intelligence/diagnosis.py tests/test_intelligence/test_diagnosis.py
git commit -m "feat: add build_diagnosis_prompt with tests"
```

---

### Task 2: `parse_diagnosis_response()` を TDD で実装する

**Files:**
- Modify: `app/intelligence/diagnosis.py`
- Modify: `tests/test_intelligence/test_diagnosis.py`

- [ ] **Step 1: テストを追加する**

`tests/test_intelligence/test_diagnosis.py` に追記：

```python
from app.intelligence.diagnosis import parse_diagnosis_response


def _make_valid_json() -> str:
    return json.dumps({
        "initial_class": "accident",
        "accident_subtype": "システム障害",
        "moat_switching_cost": "高",
        "moat_network_effect": "有",
        "moat_regulatory_barrier": "中",
        "moat_brand_dependency": "中",
        "moat_summary": "毀損度 低。顧客離脱しにくい構造。",
        "similar_cases": "Meta 2021-10 大規模障害: 数日で回復",
        "counterarguments": "1. 構造的欠陥の可能性\n2. 訴訟リスク\n3. 顧客離脱リスク",
        "oversight_risks": "訴訟規模が想定を超えるリスク",
        "confidence": "medium",
        "confidence_reason": "複数ニュースソースが一致",
        "full_text": "━━ 診断ブリーフィング ━━\n...",
    }, ensure_ascii=False)


def test_parse_diagnosis_response_valid_json():
    result = parse_diagnosis_response(_make_valid_json())
    assert result["initial_class"] == "accident"
    assert result["accident_subtype"] == "システム障害"
    assert result["confidence"] == "medium"
    assert result["full_text"] == "━━ 診断ブリーフィング ━━\n..."


def test_parse_diagnosis_response_builds_moat_json():
    result = parse_diagnosis_response(_make_valid_json())
    moat = json.loads(result["moat_json"])
    assert moat["switching_cost"] == "高"
    assert moat["network_effect"] == "有"
    assert moat["regulatory_barrier"] == "中"
    assert moat["brand_dependency"] == "中"
    assert "毀損度" in moat["summary"]


def test_parse_diagnosis_response_json_in_markdown_fence():
    wrapped = "思考中...\n```json\n" + _make_valid_json() + "\n```\n以上です。"
    result = parse_diagnosis_response(wrapped)
    assert result["initial_class"] == "accident"


def test_parse_diagnosis_response_invalid_json_returns_fallback():
    result = parse_diagnosis_response("これはJSONではありません")
    assert result["initial_class"] == "unknown"
    assert result["full_text"] == ""
    assert result["confidence"] == "low"
    moat = json.loads(result["moat_json"])
    assert moat["switching_cost"] == "N/A"


def test_parse_diagnosis_response_partial_json_fills_fallback():
    partial = json.dumps({"initial_class": "incident", "confidence": "high"})
    result = parse_diagnosis_response(partial)
    assert result["initial_class"] == "incident"
    assert result["confidence"] == "high"
    assert result["accident_subtype"] is None
    assert result["full_text"] == ""
```

- [ ] **Step 2: テストの失敗を確認する**

```bash
uv run pytest tests/test_intelligence/test_diagnosis.py -v -k "parse"
```

期待結果: 5件 FAILED（`parse_diagnosis_response` が `pass` のため）

- [ ] **Step 3: `parse_diagnosis_response()` を実装する**

`app/intelligence/diagnosis.py` の `parse_diagnosis_response` を置き換える：

```python
def parse_diagnosis_response(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        parsed = {}
    else:
        try:
            parsed = json.loads(m.group())
        except json.JSONDecodeError:
            parsed = {}

    result = {**_FALLBACK, **{k: v for k, v in parsed.items() if k in _FALLBACK}}

    moat = json.dumps({
        "switching_cost": result.pop("moat_switching_cost", "N/A"),
        "network_effect": result.pop("moat_network_effect", "N/A"),
        "regulatory_barrier": result.pop("moat_regulatory_barrier", "N/A"),
        "brand_dependency": result.pop("moat_brand_dependency", "N/A"),
        "summary": result.pop("moat_summary", ""),
    }, ensure_ascii=False)
    result["moat_json"] = moat
    return result
```

> **注意**: `_FALLBACK` に `moat_switching_cost` 等の moat サブキーを追加し、`parse` 後に `moat_json` キーに変換する。`_FALLBACK` を以下に更新すること：
>
> ```python
> _FALLBACK: dict = {
>     "initial_class": "unknown",
>     "accident_subtype": None,
>     "moat_switching_cost": "N/A",
>     "moat_network_effect": "N/A",
>     "moat_regulatory_barrier": "N/A",
>     "moat_brand_dependency": "N/A",
>     "moat_summary": "",
>     "similar_cases": "",
>     "counterarguments": "",
>     "oversight_risks": "",
>     "confidence": "low",
>     "confidence_reason": "",
>     "full_text": "",
> }
> ```

- [ ] **Step 4: テストが通ることを確認する**

```bash
uv run pytest tests/test_intelligence/test_diagnosis.py -v
```

期待結果: 12件 PASSED（build 7件 + parse 5件）

- [ ] **Step 5: コミット**

```bash
git add app/intelligence/diagnosis.py tests/test_intelligence/test_diagnosis.py
git commit -m "feat: add parse_diagnosis_response with moat_json packing"
```

---

### Task 3: `run_diagnosis()` を TDD で実装する

**Files:**
- Modify: `app/intelligence/diagnosis.py`
- Modify: `tests/test_intelligence/test_diagnosis.py`

- [ ] **Step 1: テストを追加する**

`tests/test_intelligence/test_diagnosis.py` に追記（既存の conftest.py `async_session` fixture を使用）：

```python
import pytest
from unittest.mock import patch
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.models.stock import Base, StockMeta
from app.models.dip import DipEvent
from app.models.analysis import NumericalAnalysis
from app.models.briefing import Briefing
from app.models.news import NewsArticle
from app.intelligence.diagnosis import run_diagnosis


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        yield s
    await engine.dispose()


async def _seed(session) -> tuple[DipEvent, Briefing]:
    event = DipEvent(
        symbol="CRWD", trigger_date="2024-07-19",
        change_pct_1d=-11.2, change_pct_5d=-8.7,
        status="interviewed", macro_flag=0,
    )
    session.add(event)
    await session.flush()
    interview = Briefing(
        dip_event_id=event.id, briefing_type="interview",
        situation_summary="BSOD障害", initial_class="accident",
        initial_class_jp="事故型", is_latest=1,
        created_at="2024-07-20T00:00:00",
    )
    session.add(interview)
    await session.commit()
    return event, interview


def _mock_llm_response() -> str:
    return json.dumps({
        "initial_class": "accident",
        "accident_subtype": "システム障害",
        "moat_switching_cost": "高",
        "moat_network_effect": "有",
        "moat_regulatory_barrier": "中",
        "moat_brand_dependency": "中",
        "moat_summary": "毀損度 低",
        "similar_cases": "Meta 2021",
        "counterarguments": "1. a\n2. b\n3. c",
        "oversight_risks": "訴訟リスク",
        "confidence": "medium",
        "confidence_reason": "複数一致",
        "full_text": "━━ 診断ブリーフィング ━━\n...",
    }, ensure_ascii=False)


@pytest.mark.asyncio
async def test_run_diagnosis_creates_briefing(session):
    event, interview = await _seed(session)

    with patch("app.intelligence.diagnosis.generate", return_value=(_mock_llm_response(), 15.3)):
        result = await run_diagnosis(session, event, None, interview, [])

    assert result is not None
    assert result.briefing_type == "diagnosis"
    assert result.initial_class == "accident"
    assert result.accident_subtype == "システム障害"
    assert result.confidence == "medium"
    assert result.generation_sec == pytest.approx(15.3)
    assert result.model_name == "qwen3.6:35b"
    moat = json.loads(result.moat_json)
    assert moat["switching_cost"] == "高"


@pytest.mark.asyncio
async def test_run_diagnosis_updates_event_status(session):
    event, interview = await _seed(session)

    with patch("app.intelligence.diagnosis.generate", return_value=(_mock_llm_response(), 10.0)):
        await run_diagnosis(session, event, None, interview, [])

    await session.refresh(event)
    assert event.status == "diagnosed"


@pytest.mark.asyncio
async def test_run_diagnosis_ollama_failure_returns_none(session):
    event, interview = await _seed(session)

    with patch("app.intelligence.diagnosis.generate", side_effect=Exception("Connection refused")):
        result = await run_diagnosis(session, event, None, interview, [])

    assert result is None
    await session.refresh(event)
    assert event.status == "interviewed"  # status 変更なし


@pytest.mark.asyncio
async def test_run_diagnosis_second_run_updates_is_latest(session):
    event, interview = await _seed(session)

    with patch("app.intelligence.diagnosis.generate", return_value=(_mock_llm_response(), 10.0)):
        first = await run_diagnosis(session, event, None, interview, [])
    with patch("app.intelligence.diagnosis.generate", return_value=(_mock_llm_response(), 12.0)):
        second = await run_diagnosis(session, event, None, interview, [])

    await session.refresh(first)
    assert first.is_latest == 0
    assert second.is_latest == 1
```

- [ ] **Step 2: テストの失敗を確認する**

```bash
uv run pytest tests/test_intelligence/test_diagnosis.py -v -k "run_diagnosis"
```

期待結果: 4件 FAILED（`run_diagnosis` が `pass` のため）

- [ ] **Step 3: `run_diagnosis()` を実装する**

`app/intelligence/diagnosis.py` の `run_diagnosis` を置き換える：

```python
async def run_diagnosis(
    session: AsyncSession,
    event: DipEvent,
    analysis: NumericalAnalysis | None,
    interview: Briefing,
    articles: list[NewsArticle],
    meta: StockMeta | None = None,
) -> Briefing | None:
    prompt = build_diagnosis_prompt(event, analysis, interview, articles, meta)

    try:
        text, elapsed = await generate(prompt, model=OLLAMA_MODEL_DIAGNOSIS, think=True)
    except Exception as e:
        logger.error("Ollama diagnosis failed for %s: %s", event.symbol, e)
        return None

    parsed = parse_diagnosis_response(text)

    try:
        await session.execute(
            update(Briefing)
            .where(Briefing.dip_event_id == event.id, Briefing.briefing_type == "diagnosis")
            .values(is_latest=0)
        )

        briefing = Briefing(
            dip_event_id=event.id,
            briefing_type="diagnosis",
            situation_summary=interview.situation_summary,
            initial_class=parsed.get("initial_class", "unknown"),
            initial_class_jp=_CLASS_JP.get(parsed.get("initial_class", ""), "不明"),
            accident_subtype=parsed.get("accident_subtype"),
            moat_json=parsed.get("moat_json"),
            counterarguments=parsed.get("counterarguments", ""),
            confidence=parsed.get("confidence", "low"),
            full_text=parsed.get("full_text", ""),
            prompt_used=prompt,
            model_name=OLLAMA_MODEL_DIAGNOSIS,
            generation_sec=elapsed,
            created_at=datetime.now(timezone.utc).isoformat(),
            is_latest=1,
        )
        session.add(briefing)
        event.status = "diagnosed"
        await session.commit()
        return briefing
    except Exception as e:
        await session.rollback()
        logger.error("DB save failed for diagnosis %s: %s", event.symbol, e)
        return None
```

- [ ] **Step 4: 全テストが通ることを確認する**

```bash
uv run pytest tests/test_intelligence/test_diagnosis.py -v
```

期待結果: 16件以上 PASSED

- [ ] **Step 5: 既存テストも壊れていないことを確認する**

```bash
uv run pytest -v
```

期待結果: 75件以上 PASSED（既存 59件 + 診断テスト）

- [ ] **Step 6: コミット**

```bash
git add app/intelligence/diagnosis.py tests/test_intelligence/test_diagnosis.py
git commit -m "feat: implement run_diagnosis with DB persistence and status update"
```

---

### Task 4: Router エンドポイントとパーシャルテンプレートを実装する

**Files:**
- Modify: `app/routers/dip_detail.py`
- Create: `app/templates/partials/diagnosis_result.html`

- [ ] **Step 1: パーシャルテンプレートを作成する**

`app/templates/partials/diagnosis_result.html` を新規作成：

```html
<div id="diagnosis-container">
  {% if error %}
  <p class="text-red-400 text-sm py-2">{{ error }}</p>
  <button
    hx-post="/dip/{{ dip_id }}/diagnose"
    hx-target="#diagnosis-container"
    hx-swap="outerHTML"
    hx-indicator="#diagnosis-spinner"
    class="mt-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg"
  >再試行</button>
  <span id="diagnosis-spinner" class="htmx-indicator ml-2 text-sm text-gray-400">分析中...</span>
  {% else %}
  <section class="bg-gray-900 border border-gray-800 rounded-xl p-4">
    <div class="flex justify-between items-center mb-3">
      <h2 class="text-sm font-semibold text-gray-400">診断ブリーフィング</h2>
      <span class="text-xs text-gray-500">
        {{ diagnosis.model_name }} / {{ "%.1f"|format(diagnosis.generation_sec or 0) }}s
      </span>
    </div>
    <pre class="text-xs text-gray-300 whitespace-pre-wrap font-sans leading-relaxed">{{ diagnosis.full_text }}</pre>
  </section>
  {% endif %}
</div>
```

- [ ] **Step 2: Router に POST `/dip/{id}/diagnose` を追加する**

`app/routers/dip_detail.py` を読んでから、既존の `@router.get("/dip/{dip_id}", ...)` の下に以下を추가：

```python
from sqlalchemy import select
from app.intelligence.diagnosis import run_diagnosis
from app.models.news import NewsArticle

@router.post("/dip/{dip_id}/diagnose", response_class=HTMLResponse)
async def diagnose_dip(
    dip_id: int,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    result = await session.execute(select(DipEvent).where(DipEvent.id == dip_id))
    event = result.scalar_one_or_none()
    if not event or event.status not in ("interviewed", "diagnosed"):
        return templates.TemplateResponse(
            request, "partials/diagnosis_result.html",
            {"dip_id": dip_id, "diagnosis": None, "error": "문진이 완료되지 않았습니다"},
            status_code=400,
        )

    ana_r = await session.execute(
        select(NumericalAnalysis).where(NumericalAnalysis.dip_event_id == dip_id)
    )
    analysis = ana_r.scalar_one_or_none()

    iw_r = await session.execute(
        select(Briefing).where(
            Briefing.dip_event_id == dip_id,
            Briefing.briefing_type == "interview",
            Briefing.is_latest == 1,
        )
    )
    interview = iw_r.scalar_one_or_none()
    if not interview:
        return templates.TemplateResponse(
            request, "partials/diagnosis_result.html",
            {"dip_id": dip_id, "diagnosis": None, "error": "문진 데이터를 찾을 수 없습니다"},
            status_code=400,
        )

    art_r = await session.execute(
        select(NewsArticle).where(NewsArticle.dip_event_id == dip_id)
    )
    articles = list(art_r.scalars().all())

    meta_r = await session.execute(select(StockMeta).where(StockMeta.symbol == event.symbol))
    meta = meta_r.scalar_one_or_none()

    diagnosis = await run_diagnosis(session, event, analysis, interview, articles, meta)

    return templates.TemplateResponse(
        request, "partials/diagnosis_result.html",
        {
            "dip_id": dip_id,
            "diagnosis": diagnosis,
            "error": None if diagnosis else "진단에 실패했습니다. Ollama가 실행 중인지 확인하십시오.",
        },
    )
```

> **注意**: `dip_detail.py` の既存 import を確認し、`NumericalAnalysis`, `NewsArticle`, `StockMeta`, `run_diagnosis` の import が不足していれば추가する。

- [ ] **Step 3: サーバーを起動してエンドポイントの存在を確認する（手動テスト）**

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

別ターミナルで：

```bash
curl -X POST http://localhost:8000/dip/1/diagnose -H "HX-Request: true"
```

期待結果: 200 または 400（問診未完了時）、HTML 断片が返る

- [ ] **Step 4: コミット**

```bash
git add app/routers/dip_detail.py app/templates/partials/diagnosis_result.html
git commit -m "feat: add POST /dip/{id}/diagnose HTMX endpoint and partial template"
```

---

### Task 5: `dip_detail.html` の診断ボタンを HTMX に更新する

**Files:**
- Modify: `app/templates/dip_detail.html`

- [ ] **Step 1: 既存のテンプレートを読む**

`app/templates/dip_detail.html` を Read ツールで読み、以下の2箇所を特定する：

1. `disabled` 属性付きの診断ボタン（「Phase 3 で実装予定」テキスト）
2. `{% if diagnosis %}` で診断結果を表示しているセクション

- [ ] **Step 2: 診断セクションを `#diagnosis-container` に置き換える**

既存の `{% if diagnosis %}...{% endif %}` セクション **と** 既存の disabled ボタンを、以下の一つのブロックに置き換える：

```html
<div id="diagnosis-container" class="mb-4">
  {% if diagnosis %}
  <section class="bg-gray-900 border border-gray-800 rounded-xl p-4">
    <div class="flex justify-between items-center mb-3">
      <h2 class="text-sm font-semibold text-gray-400">診断ブリーフィング</h2>
      <span class="text-xs text-gray-500">
        {{ diagnosis.model_name }} / {{ "%.1f"|format(diagnosis.generation_sec or 0) }}s
      </span>
    </div>
    <pre class="text-xs text-gray-300 whitespace-pre-wrap font-sans leading-relaxed">{{ diagnosis.full_text }}</pre>
  </section>
  {% elif event.status in ["interviewed", "diagnosed"] %}
  <button
    hx-post="/dip/{{ event.id }}/diagnose"
    hx-target="#diagnosis-container"
    hx-swap="outerHTML"
    hx-indicator="#diagnosis-spinner"
    class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm rounded-lg"
  >診断を実行</button>
  <span id="diagnosis-spinner" class="htmx-indicator ml-2 text-sm text-gray-400">
    分析中（数分かかります）...
  </span>
  {% endif %}
</div>
```

> **htmx-indicator の CSS**: Tailwind CDN では `htmx-indicator` の `display:none` が自動適用されない場合がある。`base.html` に以下を추가すること（既に추가済みであればスキップ）：
>
> ```html
> <style>.htmx-indicator { display: none; } .htmx-request .htmx-indicator { display: inline; }</style>
> ```

- [ ] **Step 3: ブラウザで動作確認する**

```
1. http://localhost:8000 を開く
2. status=interviewed のイベントをクリック
3. 「診断を実行」ボタンが表示されることを確認
4. ボタンをクリック → 「分析中...」表示 → 診断結果が表示されることを確認
5. ページリロード後も診断結果が残ることを確認（DB 保存済みのため）
```

> **Ollama 未起動テスト**: Ollama を停止した状態でボタンを押し、「診断に失敗しました」エラーメッセージと「再試行」ボタンが表示されることを確認。

- [ ] **Step 4: 全テストが通ることを最終確認する**

```bash
uv run pytest -v
```

期待結果: 75件以上 PASSED

- [ ] **Step 5: 最終コミット**

```bash
git add app/templates/dip_detail.html
git commit -m "feat: enable HTMX diagnosis button in dip_detail.html"
```

---

## Verification

### エンドツーエンドテスト手順

```bash
# 1. Ollama が起動していることを確認
curl http://localhost:11434/api/tags | python -m json.tool | grep qwen3.6

# 2. バックフィル（CrowdStrike 2024-07-19）
uv run python scripts/backfill.py 2024-07-19

# 3. サーバー起動
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 4. ブラウザで http://localhost:8000 を開く
# 5. CRWD イベントをクリック → 詳細画面へ
# 6. 「診断を実行」ボタンをクリック
# 7. 数分後に診断ブリーフィングが表示されることを確認
# 8. ページリロードで診断結果が保持されていることを確認

# 9. DB を直接確認
uv run python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import select
from app.models.briefing import Briefing

async def check():
    engine = create_async_engine('sqlite+aiosqlite:///diptriage.db')
    async with AsyncSession(engine) as s:
        r = await s.execute(select(Briefing).where(Briefing.briefing_type=='diagnosis'))
        b = r.scalar_one_or_none()
        if b:
            print('initial_class:', b.initial_class)
            print('confidence:', b.confidence)
            print('full_text[:200]:', b.full_text[:200])
        else:
            print('No diagnosis found')

asyncio.run(check())
"
```

### 期待する最終状態

- `uv run pytest -v` → 75件以上 PASSED
- `/dip/{id}` 詳細画面に「診断を実行」ボタンが表示される（status=interviewed の場合）
- ボタン押下後、診断ブリーフィングが表示される（qwen3.6:35b の出力）
- `Briefing` テーブルに `briefing_type="diagnosis"` のレコードが保存される
- `DipEvent.status` が `"diagnosed"` に更新される
