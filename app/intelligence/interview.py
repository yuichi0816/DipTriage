"""Stage 3b: LLM 問診（プロンプト生成・Qwen3 呼び出し・結果パース・DB 保存）"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import OLLAMA_MODEL_INTERVIEW
from app.intelligence.llm_client import generate
from app.models import Briefing, DipEvent, NewsArticle, NumericalAnalysis

logger = logging.getLogger(__name__)

_VALID_CLASSES = {"accident", "incident", "unknown"}
_CLASS_JP = {"accident": "事故型", "incident": "事件型", "unknown": "不明"}


def build_prompt(
    event: DipEvent,
    analysis: NumericalAnalysis | None,
    articles: list[NewsArticle],
    name: str | None = None,
    sector: str | None = None,
) -> str:
    """問診用プロンプトを組み立てる。"""
    market = "JP" if str(event.symbol).endswith(".T") else "US"
    name_part = f"（{name}）" if name else ""
    sector_part = f" / {sector}" if sector else ""

    change_line = f"【前日比】{event.change_pct_1d:.1f}%"
    if event.change_pct_5d is not None:
        change_line += f"  【週間】{event.change_pct_5d:.1f}%"

    volume_line = ""
    sector_line = ""
    if analysis:
        if analysis.volume_ratio_20d:
            volume_line = f"【出来高】{analysis.volume_ratio_20d:.1f}倍（20日平均比）"
        if analysis.sector_relative is not None:
            label = "銘柄固有" if analysis.is_idiosyncratic else "セクター連動"
            sector_line = f"【セクター超過下落】{analysis.sector_relative:.1f}%（{label}）"

    news_lines = []
    for i, art in enumerate(articles[:10], 1):
        if art.before_trigger == 1:
            lbl = "[前]"
        elif art.before_trigger == 0:
            lbl = "[後]"
        else:
            lbl = "[?]"
        news_lines.append(f"{i}. {lbl} {art.title}")

    news_section = "\n".join(news_lines) if news_lines else "（ニュースなし）"

    parts = [
        "以下の株価急落イベントについて分析してください。",
        "",
        f"【銘柄】{event.symbol}{name_part} / {market}{sector_part}",
        change_line,
    ]
    if volume_line:
        parts.append(volume_line)
    if sector_line:
        parts.append(sector_line)
    parts += [
        "",
        "【関連ニュース（急落前後）】",
        news_section,
        "",
        "必ず日本語で、以下のJSON形式のみで回答してください（他のテキスト不要）:",
        '{',
        '  "situation_summary": "日本語で2〜3文で何が起きたかを説明",',
        '  "initial_class": "accident または incident または unknown"',
        '}',
    ]
    return "\n".join(parts)


def parse_llm_response(text: str) -> dict[str, str]:
    """LLM の応答から JSON を抽出してパースする。失敗時はフォールバック値を返す。"""
    _fallback = {"situation_summary": "（解析失敗）", "initial_class": "unknown"}
    match = re.search(r'\{[^{}]+\}', text, re.DOTALL)
    if not match:
        return _fallback
    try:
        data = json.loads(match.group())
        cls = data.get("initial_class", "unknown")
        if cls not in _VALID_CLASSES:
            cls = "unknown"
        return {
            "situation_summary": data.get("situation_summary", "（解析失敗）"),
            "initial_class": cls,
        }
    except json.JSONDecodeError:
        return _fallback


async def run_interview(
    session: AsyncSession,
    event: DipEvent,
    analysis: NumericalAnalysis | None,
    articles: list[NewsArticle],
    meta=None,
) -> Briefing | None:
    """問診を実行し Briefing を DB に保存する。失敗時は None を返す（status は変えない）。"""
    # LLM 呼び出しは DB に触れないので rollback 不要
    try:
        prompt = build_prompt(
            event, analysis, articles,
            name=meta.name if meta else None,
            sector=meta.sector if meta else None,
        )
        text, elapsed = await generate(prompt, model=OLLAMA_MODEL_INTERVIEW)
        parsed = parse_llm_response(text)
    except Exception as e:
        logger.error("Interview failed for %s: %s", event.symbol, e)
        return None

    # DB 書き込みは別ブロックで rollback を管理
    try:
        now = datetime.now(timezone.utc).isoformat()
        await session.execute(
            update(Briefing)
            .where(Briefing.dip_event_id == event.id, Briefing.briefing_type == "interview")
            .values(is_latest=0)
        )
        briefing = Briefing(
            dip_event_id=event.id,
            briefing_type="interview",
            situation_summary=parsed["situation_summary"],
            initial_class=parsed["initial_class"],
            initial_class_jp=_CLASS_JP.get(parsed["initial_class"], "不明"),
            prompt_used=prompt,
            model_name=OLLAMA_MODEL_INTERVIEW,
            generation_sec=elapsed,
            created_at=now,
            is_latest=1,
        )
        session.add(briefing)

        event.status = "interviewed"
        event.updated_at = now

        await session.commit()
        await session.refresh(briefing)
        logger.info("Interviewed %s: class=%s (%.1fs)", event.symbol, parsed["initial_class"], elapsed)
        return briefing
    except Exception as e:
        logger.error("Failed to save interview for %s: %s", event.symbol, e)
        await session.rollback()
        return None
