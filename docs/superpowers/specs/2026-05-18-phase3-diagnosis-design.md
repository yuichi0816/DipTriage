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
