# 2軸決定木による5分類 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** interview.py / diagnosis.py の分類ロジックを「3択選択」から「3軸 Yes/No → Python 導出」に置き換え、accident/incident/structural/macro/unknown の5分類を実現する。

**Architecture:** LLM は intentional / recoverable / company_specific の3軸に Yes/No/null で答えるだけ。分類コード (`initial_class`) は `_derive_class()` がPython側で決定論的に導出する。DB スキーマは変更なし。

**Tech Stack:** Python, SQLAlchemy (async), pytest, Ollama/Groq LLM

---

## 変更ファイル一覧

| ファイル | 変更内容 |
|----------|----------|
| `app/intelligence/interview.py` | `_VALID_CLASSES`・`_CLASS_JP` 更新 / `_derive_class()` 追加 / `build_prompt()` 2軸Q&A形式に変更 / `parse_llm_response()` 軸抽出+導出に変更 |
| `app/intelligence/diagnosis.py` | `build_diagnosis_prompt()` に2軸判断フロー追加・`initial_class` JSON説明更新 |
| `app/routers/dashboard.py` | `_CLASS_ORDER` に structural / macro 追加 |
| `tests/test_intelligence/test_interview.py` | `_derive_class()` テスト追加・既存テスト更新 |
| `tests/test_intelligence/test_diagnosis.py` | プロンプト変更テスト更新 |

---

## Task 1: `_derive_class()` と定数の更新

**Files:**
- Modify: `app/intelligence/interview.py:18-19`（定数）
- Test: `tests/test_intelligence/test_interview.py`

- [ ] **Step 1: `_derive_class()` の失敗テストを書く**

`tests/test_intelligence/test_interview.py` の先頭インポートブロック（`from app.intelligence.interview import build_prompt, parse_llm_response` の行）を以下に変更する:

```python
import json
from app.intelligence.interview import build_prompt, parse_llm_response, _derive_class
```

次に `TestParseLlmResponse` クラスの前に以下のクラスを追加する:

```python
class TestDeriveClass:
    def test_intentional_true_returns_incident(self):
        assert _derive_class(True, None, None) == "incident"

    def test_intentional_none_returns_unknown(self):
        assert _derive_class(None, None, None) == "unknown"

    def test_recoverable_true_returns_accident(self):
        assert _derive_class(False, True, None) == "accident"

    def test_recoverable_none_returns_unknown(self):
        assert _derive_class(False, None, None) == "unknown"

    def test_company_specific_true_returns_structural(self):
        assert _derive_class(False, False, True) == "structural"

    def test_company_specific_false_returns_macro(self):
        assert _derive_class(False, False, False) == "macro"

    def test_company_specific_none_returns_unknown(self):
        assert _derive_class(False, False, None) == "unknown"

    def test_intentional_true_ignores_other_axes(self):
        # Q1=YES → 即 incident、他の軸は無視
        assert _derive_class(True, True, False) == "incident"
```

- [ ] **Step 2: テストが失敗することを確認**

```
pytest tests/test_intelligence/test_interview.py::TestDeriveClass -v
```

Expected: `ImportError: cannot import name '_derive_class'`

- [ ] **Step 3: `interview.py` の定数と `_derive_class()` を実装**

`app/intelligence/interview.py` の `_VALID_CLASSES` と `_CLASS_JP` を置き換え、`_derive_class()` を追加する:

```python
_VALID_CLASSES = {"accident", "incident", "structural", "macro", "unknown"}
_CLASS_JP = {
    "accident": "事故型",
    "incident": "事件型",
    "structural": "構造型",
    "macro": "マクロ型",
    "unknown": "不明",
}


def _derive_class(
    intentional: bool | None,
    recoverable: bool | None,
    company_specific: bool | None,
) -> str:
    if intentional is True:       return "incident"
    if intentional is None:       return "unknown"
    if recoverable is True:       return "accident"
    if recoverable is None:       return "unknown"
    if company_specific is True:  return "structural"
    if company_specific is None:  return "unknown"
    return "macro"
```

- [ ] **Step 4: テストが通ることを確認**

```
pytest tests/test_intelligence/test_interview.py::TestDeriveClass -v
```

Expected: 8 passed

- [ ] **Step 5: コミット**

```bash
git add app/intelligence/interview.py tests/test_intelligence/test_interview.py
git commit -m "feat: add _derive_class() with 5-class taxonomy and update _VALID_CLASSES"
```

---

## Task 2: `build_prompt()` を2軸Q&A形式に更新

**Files:**
- Modify: `app/intelligence/interview.py` — `build_prompt()`
- Test: `tests/test_intelligence/test_interview.py` — `TestBuildPrompt`

- [ ] **Step 1: `TestBuildPrompt` の既存テストを更新・追加**

`TestBuildPrompt` クラス内の以下を変更する:

`test_contains_classification_definition` を更新（旧: 【分類定義】の文字列チェック → 新: Q1/Q2/Q3 構造チェック）:

```python
def test_contains_classification_definition(self):
    prompt = build_prompt(_event(), None, [])
    assert "Q1" in prompt
    assert "Q2" in prompt
    assert "Q3" in prompt
    assert "intentional" in prompt
    assert "recoverable" in prompt
    assert "company_specific" in prompt

def test_contains_key_facts_field(self):
    prompt = build_prompt(_event(), None, [])
    assert "key_facts" in prompt

def test_contains_2axis_flow_header(self):
    prompt = build_prompt(_event(), None, [])
    assert "2軸分類フロー" in prompt
```

`test_contains_few_shot_examples` は削除（新プロンプトには分類例セクションなし）。

- [ ] **Step 2: テストが失敗することを確認**

```
pytest tests/test_intelligence/test_interview.py::TestBuildPrompt -v
```

Expected: `test_contains_classification_definition` と `test_contains_2axis_flow_header` が FAIL、`test_contains_few_shot_examples` が FAIL (KeyError or AttributeError)

- [ ] **Step 3: `build_prompt()` を2軸Q&A形式に更新**

`app/intelligence/interview.py` の `build_prompt()` 内、`parts +=` の分類定義セクション（`【分類定義】` 〜 末尾の `'}'` まで）を以下に置き換える:

```python
    parts += [
        "",
        "【2軸分類フロー】",
        "以下の3つの質問に順番に答えて分類を決定してください:",
        "",
        "Q1. この急落は、会社・経営者による意図的な悪質行為が原因ですか？",
        "    （不正・詐欺・組織ぐるみの情報隠蔽・意図的なガバナンス悪用）",
        "    → YES: 事件型 (incident) — Q2/Q3 は不要（null にする）",
        "    → NO : Q2へ",
        "",
        "Q2. 急落の原因は一時的・回復可能ですか？",
        "    （偶発的なミス・外部イベント・評価調整・自然災害・一時的な決算ミス）",
        "    → YES: 事故型 (accident) — Q3 は不要（null にする）",
        "    → NO : Q3へ",
        "",
        "Q3. 回復が困難な原因は自社の問題ですか？",
        "    （競争力低下・ビジネスモデル劣化・市場シェア喪失）",
        "    → YES: 構造型 (structural)",
        "    → NO : マクロ型 (macro)（金利・地政学・市場全体連動）",
        "",
        "情報が不足して判断できない軸は null にしてください。",
        "",
        "必ず日本語で、以下のJSON形式のみで回答してください（他のテキスト不要）:",
        '{',
        '  "key_facts": "急落の直接原因を1文（判断根拠）",',
        '  "intentional": true または false または null,',
        '  "recoverable": true または false または null（Q1=falseの場合のみ、それ以外はnull）,',
        '  "company_specific": true または false または null（Q2=falseの場合のみ、それ以外はnull）,',
        '  "situation_summary": "日本語で2〜3文で何が起きたかを説明"',
        '}',
    ]
```

- [ ] **Step 4: テストが通ることを確認**

```
pytest tests/test_intelligence/test_interview.py::TestBuildPrompt -v
```

Expected: 9 passed（`test_contains_few_shot_examples` を削除したため）

- [ ] **Step 5: コミット**

```bash
git add app/intelligence/interview.py tests/test_intelligence/test_interview.py
git commit -m "feat: update build_prompt() to 2-axis Q&A decision tree format"
```

---

## Task 3: `parse_llm_response()` を軸抽出+導出に更新

**Files:**
- Modify: `app/intelligence/interview.py` — `parse_llm_response()`
- Test: `tests/test_intelligence/test_interview.py` — `TestParseLlmResponse` + 統合テスト

- [ ] **Step 1: `TestParseLlmResponse` を全面更新・拡充**

`TestParseLlmResponse` クラスを以下に置き換える（旧テストは新フォーマットに合わせて更新、新テスト追加）:

```python
class TestParseLlmResponse:
    def _json(self, intentional, recoverable, company_specific,
              summary="説明。", key_facts="原因。"):
        return json.dumps({
            "key_facts": key_facts,
            "intentional": intentional,
            "recoverable": recoverable,
            "company_specific": company_specific,
            "situation_summary": summary,
        })

    def test_derives_accident(self):
        result = parse_llm_response(
            self._json(False, True, None, "障害発生。", "システム障害。")
        )
        assert result["initial_class"] == "accident"

    def test_derives_incident(self):
        result = parse_llm_response(
            self._json(True, None, None, "不正発覚。", "不正会計。")
        )
        assert result["initial_class"] == "incident"

    def test_derives_structural(self):
        result = parse_llm_response(
            self._json(False, False, True, "業績悪化。", "競争力低下。")
        )
        assert result["initial_class"] == "structural"

    def test_derives_macro(self):
        result = parse_llm_response(
            self._json(False, False, False, "マクロ要因。", "金利上昇。")
        )
        assert result["initial_class"] == "macro"

    def test_derives_unknown_when_intentional_null(self):
        result = parse_llm_response(
            self._json(None, None, None)
        )
        assert result["initial_class"] == "unknown"

    def test_derives_unknown_when_recoverable_null(self):
        result = parse_llm_response(
            self._json(False, None, None)
        )
        assert result["initial_class"] == "unknown"

    def test_axis_judgment_recorded_in_summary(self):
        result = parse_llm_response(
            self._json(False, True, None, "詳細。", "原因。")
        )
        assert "[根拠] 原因。" in result["situation_summary"]
        assert "[判断]" in result["situation_summary"]
        assert "事故型" in result["situation_summary"]
        assert "詳細。" in result["situation_summary"]

    def test_returns_fallback_for_invalid_json(self):
        result = parse_llm_response("not json at all")
        assert result["initial_class"] == "unknown"
        assert "解析失敗" in result["situation_summary"]

    def test_handles_empty_string(self):
        result = parse_llm_response("")
        assert result["initial_class"] == "unknown"

    def test_parses_json_embedded_in_surrounding_text(self):
        inner = self._json(False, True, None, "ok", "原因")
        text = f"preamble\n{inner}\nsuffix"
        assert parse_llm_response(text)["initial_class"] == "accident"

    def test_intentional_true_ignores_other_axes(self):
        # Q1=YES → incident、recoverable/company_specific の値に関係なく
        result = parse_llm_response(
            self._json(True, True, False)
        )
        assert result["initial_class"] == "incident"
```

`test_run_interview_saves_briefing_on_success` の mock JSON と assertion を更新:

```python
llm_json = json.dumps({
    "key_facts": "センサー更新によるシステム障害。",
    "intentional": False,
    "recoverable": True,
    "company_specific": None,
    "situation_summary": "ソフトウェア障害。",
})
# ...（with patch の後）
assert briefing.initial_class == "accident"
assert briefing.initial_class_jp == "事故型"
assert "ソフトウェア障害" in briefing.situation_summary
assert "[判断]" in briefing.situation_summary
```

Task 1 Step 1 でインポート行を更新済みのため、`import json` と `_derive_class` は既に利用可能。

- [ ] **Step 2: テストが失敗することを確認**

```
pytest tests/test_intelligence/test_interview.py::TestParseLlmResponse tests/test_intelligence/test_interview.py::test_run_interview_saves_briefing_on_success -v
```

Expected: 複数 FAIL

- [ ] **Step 3: `parse_llm_response()` を軸抽出+導出に更新**

`app/intelligence/interview.py` の `parse_llm_response()` を以下に置き換える:

```python
def parse_llm_response(text: str) -> dict[str, str]:
    """LLM の応答から JSON を抽出し、3軸から分類を導出する。失敗時はフォールバック値を返す。"""
    _fallback = {"situation_summary": "（解析失敗）", "initial_class": "unknown"}
    match = re.search(r'\{[^{}]+\}', text, re.DOTALL)
    if not match:
        return _fallback
    try:
        data = json.loads(match.group())
        intentional = data.get("intentional")
        recoverable = data.get("recoverable")
        company_specific = data.get("company_specific")
        cls = _derive_class(intentional, recoverable, company_specific)

        def _fmt(v) -> str:
            if v is True:  return "YES"
            if v is False: return "NO"
            return "?"

        key_facts = data.get("key_facts", "")
        summary = data.get("situation_summary", "（解析失敗）")
        axis_line = (
            f"[判断] 意図的={_fmt(intentional)} / 回復可={_fmt(recoverable)}"
            f" / 自社={_fmt(company_specific)} → {_CLASS_JP.get(cls, '不明')}"
        )
        parts = []
        if key_facts:
            parts.append(f"[根拠] {key_facts}")
        parts.append(axis_line)
        parts.append(summary)
        return {
            "situation_summary": "\n".join(parts),
            "initial_class": cls,
        }
    except json.JSONDecodeError:
        return _fallback
```

- [ ] **Step 4: テストが通ることを確認**

```
pytest tests/test_intelligence/test_interview.py -v
```

Expected: 全テスト passed（`TestDeriveClass` 8件 + `TestBuildPrompt` 9件 + `TestParseLlmResponse` 11件 + 統合テスト 2件）

- [ ] **Step 5: コミット**

```bash
git add app/intelligence/interview.py tests/test_intelligence/test_interview.py
git commit -m "feat: update parse_llm_response() to derive class from 3-axis decision tree"
```

---

## Task 4: `build_diagnosis_prompt()` に2軸判断フローを追加

**Files:**
- Modify: `app/intelligence/diagnosis.py` — `build_diagnosis_prompt()`
- Test: `tests/test_intelligence/test_diagnosis.py`

- [ ] **Step 1: `test_build_diagnosis_prompt_includes_classification_definition` を更新**

`tests/test_intelligence/test_diagnosis.py` の既存テストを以下に置き換える:

```python
def test_build_diagnosis_prompt_includes_classification_definition():
    prompt = build_diagnosis_prompt(_make_event(), None, _make_interview(), [])
    assert "Q1" in prompt
    assert "Q2" in prompt
    assert "Q3" in prompt
    assert "意図的な悪質行為" in prompt
    assert "structural" in prompt
    assert "macro" in prompt
```

- [ ] **Step 2: テストが失敗することを確認**

```
pytest tests/test_intelligence/test_diagnosis.py::test_build_diagnosis_prompt_includes_classification_definition -v
```

Expected: FAIL

- [ ] **Step 3: `build_diagnosis_prompt()` の分類セクションを更新**

`app/intelligence/diagnosis.py` の `build_diagnosis_prompt()` 内、`"## 分類判断基準（厳守）\n"` から始まるブロックを以下に置き換える:

```python
        "## 分類判断基準（厳守・2軸決定木）\n"
        "以下の3つの質問に順番に答えて initial_class を決定してください:\n\n"
        "Q1. この急落は、会社・経営者による意図的な悪質行為が原因ですか？\n"
        "    （不正・詐欺・組織ぐるみの情報隠蔽・意図的なガバナンス悪用）\n"
        "    → YES: incident（事件型）\n"
        "    → NO : Q2へ\n\n"
        "Q2. 急落の原因は一時的・回復可能ですか？\n"
        "    （偶発的なミス・外部イベント・評価調整・自然災害・一時的な決算ミス）\n"
        "    → YES: accident（事故型）\n"
        "    → NO : Q3へ\n\n"
        "Q3. 回復が困難な原因は自社の問題ですか？\n"
        "    （競争力低下・ビジネスモデル劣化・市場シェア喪失）\n"
        "    → YES: structural（構造型）\n"
        "    → NO : macro（マクロ型・金利/地政学/市場全体連動）\n\n"
        "判断不能な場合は unknown。\n\n"
```

また、JSON テンプレート内の `initial_class` の説明文を更新する（`'  "initial_class": ...'` の行）:

```python
        '  "initial_class": "accident / incident / structural / macro / unknown — 上記2軸決定木に厳密に従うこと",\n'
```

- [ ] **Step 4: テストが通ることを確認**

```
pytest tests/test_intelligence/test_diagnosis.py -v
```

Expected: 全テスト passed

- [ ] **Step 5: コミット**

```bash
git add app/intelligence/diagnosis.py tests/test_intelligence/test_diagnosis.py
git commit -m "feat: update diagnosis prompt with 2-axis decision tree for 5-class taxonomy"
```

---

## Task 5: `_CLASS_ORDER` を5分類に対応

**Files:**
- Modify: `app/routers/dashboard.py:14`

- [ ] **Step 1: `_CLASS_ORDER` を更新**

`app/routers/dashboard.py` の14行目を以下に置き換える:

```python
_CLASS_ORDER = {"accident": 0, "incident": 1, "structural": 2, "macro": 3, "unknown": 4, None: 5}
```

- [ ] **Step 2: コミット**

```bash
git add app/routers/dashboard.py
git commit -m "feat: add structural and macro to dashboard class order"
```

---

## Task 6: 全テストスイートで回帰チェック

- [ ] **Step 1: 全テストを実行**

```
pytest -q --ignore=tests/test_routers/test_settings.py
```

Expected: 全 passed（`test_settings.py` は market_scope カラム未追加による既存の無関係エラーのため除外）

- [ ] **Step 2: 失敗があれば修正して再実行**

失敗テストのエラーメッセージを確認し、実装かテストのどちらに問題があるかを判断して修正する。

- [ ] **Step 3: 最終コミット（変更があれば）**

```bash
git add -p
git commit -m "fix: address test failures from 2-axis classification rollout"
```
