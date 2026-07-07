import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import json
from app.intelligence.interview import build_prompt, parse_llm_response, _derive_class


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
        assert "situation_summary" in prompt
        assert "intentional" in prompt

    def test_volume_ratio_included_when_analysis_provided(self):
        prompt = build_prompt(_event(), _analysis(volume_ratio=4.2), [])
        assert "4.2" in prompt

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
        assert _derive_class(True, True, False) == "incident"


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
        result = parse_llm_response(
            self._json(True, True, False)
        )
        assert result["initial_class"] == "incident"


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

        llm_json = json.dumps({
            "key_facts": "センサー更新によるシステム障害。",
            "intentional": False,
            "recoverable": True,
            "company_specific": None,
            "situation_summary": "ソフトウェア障害。",
        })
        with patch("app.intelligence.interview.generate", new=AsyncMock(return_value=(llm_json, 1.5))):
            briefing = await run_interview(session, event, None, [article])

    assert briefing is not None
    assert briefing.initial_class == "accident"
    assert briefing.initial_class_jp == "事故型"
    assert "ソフトウェア障害" in briefing.situation_summary
    assert "[判断]" in briefing.situation_summary
    assert briefing.briefing_type == "interview"
    assert briefing.generation_sec == pytest.approx(1.5)

    async with Session() as session2:
        from sqlalchemy import select as sa_select
        result = await session2.execute(sa_select(DipEvent).where(DipEvent.id == event.id))
        refreshed = result.scalar_one()
        assert refreshed.status == "interviewed"

    await engine.dispose()


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
