# 分類精度チューニング：2軸決定木による5分類設計

**日付**: 2026-05-21  
**ステータス**: 承認済み

---

## 背景・目的

現在の事件/事故/unknown の3分類では、以下の問題があった：

1. **定義がプロンプトにない** → LLMが独自解釈して誤分類
2. **事件の定義が広すぎる** → 「意図しないミス」まで事件と判定される
3. **グレーゾーンの分類先がない** → 構造的業績悪化・マクロ連動を事故/事件に無理やり押し込んでいた

本設計では「事件 = 会社の意図的な悪質性」に定義を絞り込み、2軸の決定木で5分類に拡張する。LLMに分類を「選ばせる」のではなく「Yes/No に答えさせ」、最終的な分類はPythonが論理的に導出する。

---

## 分類体系（5 + unknown）

| コード | 日本語 | 定義 | 投資アクション |
|--------|--------|------|--------------|
| `incident` | 事件型 | **意図的な悪質行為**・組織的不正（詐欺、会計改ざん、情報隠蔽）。会社の体質に由来 | Avoid |
| `accident` | 事故型 | **意図しないミス**・偶発的外部イベント（システム障害、自然災害、一時的決算ミス、評価調整） | Buy the dip |
| `structural` | 構造型 | 悪意はないが、競争力・ビジネスモデルが本質的に劣化中。回復困難かつ自社要因 | Avoid |
| `macro` | マクロ型 | 金利・地政学・市場全体連動。会社固有ダメージは低い | Conditional |
| `unknown` | 不明 | いずれかの軸が判断不能・情報不足 | Avoid（保守的） |

---

## 2軸決定木

```
Q1. 意図的な悪質行為か？
    （不正・詐欺・意図的な情報隠蔽・組織ぐるみの悪意）
      ├─ YES / null → incident / unknown
      └─ NO  → Q2へ

Q2. 急落原因は回復可能か？
    （偶発的・一時的・評価調整・外部偶発事象）
      ├─ YES / null → accident / unknown
      └─ NO  → Q3へ

Q3. 回復困難な原因は自社要因か？
    （競争力低下・ビジネスモデル劣化・市場シェア喪失）
      ├─ YES / null → structural / unknown
      └─ NO  → macro
```

---

## LLM出力フォーマット（interview）

LLMには3つの軸への回答と根拠を出力させる。分類コードはLLMに選ばせない。

```json
{
  "key_facts": "急落の直接原因を1文（判断根拠）",
  "intentional": true / false / null,
  "recoverable": true / false / null,
  "company_specific": true / false / null,
  "situation_summary": "日本語で2〜3文で何が起きたかを説明"
}
```

**軸の入力ルール（プロンプトに明記）：**
- `intentional`: Q1の答え。情報不足で判断できない場合は null
- `recoverable`: `intentional=false` の場合のみ回答。それ以外は null
- `company_specific`: `recoverable=false` の場合のみ回答。それ以外は null

---

## Python側の導出ロジック

```python
def _derive_class(intentional, recoverable, company_specific) -> str:
    if intentional is True:       return "incident"
    if intentional is None:       return "unknown"
    # intentional is False
    if recoverable is True:       return "accident"
    if recoverable is None:       return "unknown"
    # recoverable is False
    if company_specific is True:  return "structural"
    if company_specific is None:  return "unknown"
    # company_specific is False
    return "macro"
```

LLMが整合性のない値を返した場合（例: `intentional=true` なのに `recoverable=true`）は、Q1優先で `incident` に確定する。

---

## situation_summary の保存フォーマット

軸の判断過程を `situation_summary` に記録する（DBスキーマ変更なし）：

```
[根拠] <key_facts の内容>
[判断] 意図的=<true/false/null> → 回復可=<...> → 自社=<...> → <class>
<situation_summary の内容>
```

例：
```
[根拠] 経営者が財務諸表を意図的に改ざんしたと報道。
[判断] 意図的=true → 事件型
株価は前日比-15%。同社CFOが会計不正を指示していたと複数メディアが報道。
```

---

## diagnosis.py への反映

diagnosis プロンプトにも同じ2軸分類フローを追加し、interview と独立して再評価させる。interview との分類差異が出た場合、diagnosis の判定を優先（より詳細な分析）。

---

## 変更ファイル一覧

| ファイル | 変更内容 |
|----------|----------|
| `app/intelligence/interview.py` | `build_prompt()`: 2軸Q&A形式プロンプト / `parse_llm_response()`: 軸抽出 + `_derive_class()` 導出 / `_VALID_CLASSES`, `_CLASS_JP` 更新 |
| `app/intelligence/diagnosis.py` | `build_diagnosis_prompt()`: 2軸判断フロー追加 |
| `app/routers/dashboard.py` | `_CLASS_ORDER` に `structural`, `macro` 追加 |
| `tests/test_intelligence/test_interview.py` | 新フォーマット・導出ロジック・新分類値のテスト |
| `tests/test_intelligence/test_diagnosis.py` | プロンプト変更のテスト追加 |
| **`app/models/briefing.py`** | **変更なし** — `initial_class` は既存Stringカラムで対応 |

---

## 検証方法

1. `pytest tests/test_intelligence/ -v` — 全テスト通過
2. `pytest -q --ignore=tests/test_routers/test_settings.py` — 既存テスト群への回帰なし（test_settings.py は既存の無関係な失敗）
3. 手動確認: 各分類軸の組み合わせで `parse_llm_response()` が正しい class を返すことを確認
