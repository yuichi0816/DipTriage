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
        now = datetime.now(timezone.utc).isoformat()
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
            created_at=now,
            is_latest=1,
        )
        session.add(briefing)
        event.status = "diagnosed"
        event.updated_at = now
        await session.commit()
        return briefing
    except Exception as e:
        await session.rollback()
        logger.error("DB save failed for diagnosis %s: %s", event.symbol, e)
        return None
