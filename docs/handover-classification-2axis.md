# 引継書：2軸決定木による5分類チューニング

**作成日**: 2026-05-21  
**ブランチ**: main  
**ステータス**: 計画完了・実装待ち

---

## このセッションでやったこと

### Phase 1（完了）: 初回チューニング
- `app/intelligence/interview.py` の `build_prompt()` に【分類定義】【判断の鍵】【分類例】を追加
- `parse_llm_response()` に `key_facts` フィールドを追加（CoT）
- `app/intelligence/diagnosis.py` の `build_diagnosis_prompt()` に分類判断基準セクションを追加
- テスト追加・全通過（89件 passed）

### Phase 2（計画完了・未実装）: 2軸決定木への再設計
- **目的**: 「事故なのに事件と判定」される問題の根本解決
- **設計方針**: LLMに分類を「選ばせる」→「3つのYes/Noに答えさせ、Pythonが導出」

---

## 新しい分類体系

| コード | 日本語 | 定義 | 投資アクション |
|--------|--------|------|--------------|
| `incident` | 事件型 | **意図的な悪質行為**（不正・詐欺・組織ぐるみの隠蔽） | Avoid |
| `accident` | 事故型 | **意図しないミス**・偶発的外部イベント | Buy the dip |
| `structural` | 構造型 | 悪意なし、競争力・ビジネスモデルが本質的劣化中 | Avoid |
| `macro` | マクロ型 | 金利・地政学・市場全体連動、会社固有ダメージ低 | Conditional |
| `unknown` | 不明 | 情報不足・いずれかの軸が判断不能 | Avoid |

### 決定木

```
Q1. 意図的な悪質行為か？
  ├─ YES → incident
  └─ NO  → Q2へ

Q2. 回復可能か？
  ├─ YES → accident
  └─ NO  → Q3へ

Q3. 自社要因か？
  ├─ YES → structural
  └─ NO  → macro

いずれかが null → unknown
```

---

## 実装すべき内容

### 計画書
`docs/superpowers/plans/2026-05-21-classification-2axis.md` に全タスクの詳細コード付き計画書あり。

### タスク一覧（5タスク）

**Task 1**: `_derive_class()` 追加 + 定数更新（`app/intelligence/interview.py`）

```python
# 変更後の定数
_VALID_CLASSES = {"accident", "incident", "structural", "macro", "unknown"}
_CLASS_JP = {
    "accident": "事故型", "incident": "事件型",
    "structural": "構造型", "macro": "マクロ型", "unknown": "不明",
}

def _derive_class(intentional, recoverable, company_specific) -> str:
    if intentional is True:       return "incident"
    if intentional is None:       return "unknown"
    if recoverable is True:       return "accident"
    if recoverable is None:       return "unknown"
    if company_specific is True:  return "structural"
    if company_specific is None:  return "unknown"
    return "macro"
```

**Task 2**: `build_prompt()` を2軸Q&A形式に変更（`app/intelligence/interview.py`）
- 【分類定義】【判断の鍵】【分類例】セクションを削除
- Q1/Q2/Q3 の決定木テキストに置き換え
- JSON フォーマットに `intentional` / `recoverable` / `company_specific` フィールドを追加（`initial_class` フィールドは削除）

**Task 3**: `parse_llm_response()` を軸抽出+導出に変更（`app/intelligence/interview.py`）
- 旧: `data.get("initial_class")` を検証
- 新: 3軸を抽出 → `_derive_class()` で導出 → `situation_summary` に `[判断]` 行を記録

```python
# 新しい situation_summary の形式
# [根拠] センサー更新によるシステム障害。
# [判断] 意図的=NO / 回復可=YES / 自社=? → 事故型
# 詳細な説明テキスト...
```

**Task 4**: `build_diagnosis_prompt()` の分類セクションを2軸フローに更新（`app/intelligence/diagnosis.py`）
- `## 分類判断基準（厳守）` セクションを Q1/Q2/Q3 形式に置き換え
- `initial_class` JSON説明文を5分類対応に更新

**Task 5**: `_CLASS_ORDER` を5分類対応に更新（`app/routers/dashboard.py`）

```python
_CLASS_ORDER = {"accident": 0, "incident": 1, "structural": 2, "macro": 3, "unknown": 4, None: 5}
```

---

## 注意事項

### テスト更新が必要
`tests/test_intelligence/test_interview.py` の以下が旧フォーマット前提のため更新が必要:
- `TestParseLlmResponse` クラス全体（旧: `initial_class` フィールド検証 → 新: 3軸ベース）
- `test_run_interview_saves_briefing_on_success` の mock JSON
- `test_contains_classification_definition`（旧: 【分類定義】→ 新: Q1/Q2/Q3）
- `test_contains_few_shot_examples` は削除（新プロンプトに分類例セクションなし）

詳細なテストコードは計画書に全部記載済み。

### DBスキーマ変更なし
`app/models/briefing.py` は変更不要。`initial_class` は String カラムのまま。

### 既存の無関係なテスト失敗
`tests/test_routers/test_settings.py` の13件は `market_scope` カラム未追加による既存失敗。今回の変更と無関係。`--ignore=tests/test_routers/test_settings.py` で除外して実行。

---

## 確認コマンド

```bash
# 実装後の確認
pytest -q --ignore=tests/test_routers/test_settings.py
# Expected: 全 passed
```

---

## 関連ファイル

| ファイル | 用途 |
|----------|------|
| `docs/superpowers/specs/2026-05-21-classification-2axis-design.md` | 設計仕様書 |
| `docs/superpowers/plans/2026-05-21-classification-2axis.md` | 実装計画書（コード全記載） |
| `app/intelligence/interview.py` | 主要変更対象 |
| `app/intelligence/diagnosis.py` | 変更対象 |
| `app/routers/dashboard.py` | `_CLASS_ORDER` のみ変更 |
