import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.intelligence.interview import build_prompt, parse_llm_response


def _event(symbol="CRWD", trigger_date="2024-07-19", change_1d=-11.2, change_5d=-8.7):
    e = MagicMock()
    e.symbol = symbol
    e.trigger_date = trigger_date
    e.change_pct_1d = change_1d
    e.change_pct_5d = change_5d
    return e


def _analysis(volume_ratio=4.2, sector_relative=-10.8, is_idiosyncratic=1):
    a = MagicMock()
    a.volume_ratio_20d = volume_ratio
    a.sector_relative = sector_relative
    a.is_idiosyncratic = is_idiosyncratic
    return a


def _article(title="CrowdStrike outage", before_trigger=1):
    art = MagicMock()
    art.title = title
    art.before_trigger = before_trigger
    art.published_at = "2024-07-19T10:00:00+00:00"
    return art


class TestBuildPrompt:
    def test_contains_analysis_instruction(self):
        assert "分析してください" in build_prompt(_event(), None, [])

    def test_contains_symbol(self):
        assert "CRWD" in build_prompt(_event(symbol="CRWD"), None, [])

    def test_contains_change_pct_1d(self):
        assert "-11.2" in build_prompt(_event(change_1d=-11.2), None, [])

    def test_contains_article_title(self):
        arts = [_article("Falcon sensor update causes BSOD", before_trigger=1)]
        assert "Falcon sensor update causes BSOD" in build_prompt(_event(), None, arts)

    def test_before_trigger_article_has_mae_label(self):
        arts = [_article("pre-event news", before_trigger=1)]
        prompt = build_prompt(_event(), None, arts)
        assert "[前]" in prompt

    def test_after_trigger_article_has_ato_label(self):
        arts = [_article("post-event news", before_trigger=0)]
        prompt = build_prompt(_event(), None, arts)
        assert "[後]" in prompt

    def test_contains_json_instruction(self):
        prompt = build_prompt(_event(), None, [])
        assert "initial_class" in prompt
        assert "situation_summary" in prompt

    def test_volume_ratio_included_when_analysis_provided(self):
        prompt = build_prompt(_event(), _analysis(volume_ratio=4.2), [])
        assert "4.2" in prompt


class TestParseLlmResponse:
    def test_parses_valid_json(self):
        text = '{"situation_summary": "障害発生。", "initial_class": "accident"}'
        result = parse_llm_response(text)
        assert result["situation_summary"] == "障害発生。"
        assert result["initial_class"] == "accident"

    def test_parses_json_embedded_in_surrounding_text(self):
        text = 'preamble\n{"situation_summary": "ok", "initial_class": "incident"}\nsuffix'
        assert parse_llm_response(text)["initial_class"] == "incident"

    def test_returns_fallback_for_invalid_json(self):
        result = parse_llm_response("not json at all")
        assert result["initial_class"] == "unknown"
        assert "解析失敗" in result["situation_summary"]

    def test_normalizes_unknown_class_value(self):
        text = '{"situation_summary": "unclear", "initial_class": "maybe"}'
        assert parse_llm_response(text)["initial_class"] == "unknown"

    def test_handles_empty_string(self):
        result = parse_llm_response("")
        assert result["initial_class"] == "unknown"

    def test_accepts_incident_class(self):
        text = '{"situation_summary": "粉飾決算。", "initial_class": "incident"}'
        assert parse_llm_response(text)["initial_class"] == "incident"


# ── 統合テスト ──────────────────────────────────────────────────────

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.models import Base, Briefing, DipEvent, NewsArticle
from app.intelligence.interview import run_interview


async def _setup_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_run_interview_saves_briefing_on_success():
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

        article = NewsArticle(
            dip_event_id=event.id, symbol="CRWD",
            title="CrowdStrike update causes outage", url="http://example.com/a1",
            priority=4, fetched_at=now, is_duplicate=0, before_trigger=1,
        )
        session.add(article)
        await session.commit()

        llm_json = '{"situation_summary": "ソフトウェア障害。", "initial_class": "accident"}'
        with patch("app.intelligence.interview.generate", new=AsyncMock(return_value=(llm_json, 1.5))):
            briefing = await run_interview(session, event, None, [article])

    assert briefing is not None
    assert briefing.situation_summary == "ソフトウェア障害。"
    assert briefing.initial_class == "accident"
    assert briefing.initial_class_jp == "事故型"
    assert briefing.briefing_type == "interview"
    assert briefing.generation_sec == pytest.approx(1.5)

    async with Session() as session2:
        from sqlalchemy import select as sa_select
        result = await session2.execute(sa_select(DipEvent).where(DipEvent.id == event.id))
        refreshed = result.scalar_one()
        assert refreshed.status == "interviewed"

    await engine.dispose()


async def test_run_interview_returns_none_on_llm_error():
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

        article = NewsArticle(
            dip_event_id=event.id, symbol="CRWD",
            title="test", url="http://example.com/a2",
            priority=5, fetched_at=now, is_duplicate=0,
        )
        session.add(article)
        await session.commit()

        with patch("app.intelligence.interview.generate", new=AsyncMock(side_effect=Exception("Ollama down"))):
            briefing = await run_interview(session, event, None, [article])

    assert briefing is None

    async with Session() as session2:
        from sqlalchemy import select as sa_select
        result = await session2.execute(sa_select(DipEvent).where(DipEvent.id == event.id))
        refreshed = result.scalar_one()
        assert refreshed.status == "analyzed"

    await engine.dispose()
