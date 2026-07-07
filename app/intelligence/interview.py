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

from app.intelligence.taxonomy import CLASS_JP as _CLASS_JP, VALID_CLASSES as _VALID_CLASSES


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
    return "\n".join(parts)


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

        # 診断済みイベントの再問診でステータスを巻き戻さない（監査 2-5）
        if event.status != "diagnosed":
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
