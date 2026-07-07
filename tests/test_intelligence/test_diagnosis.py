import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.models.stock import Base
from app.intelligence.diagnosis import build_diagnosis_prompt, parse_diagnosis_response, run_diagnosis


# Fixture classes created with __new__ to validate schema at construction time
class _DipEventFixture:
    """Fixture for DipEvent that validates attributes match the model schema"""
    def __init__(self):
        self.symbol = None
        self.trigger_date = None
        self.change_pct_1d = None
        self.change_pct_5d = None
        self.status = None
        self.macro_flag = None


class _NumericalAnalysisFixture:
    """Fixture for NumericalAnalysis that validates attributes match the model schema"""
    def __init__(self):
        self.volume_ratio_20d = None
        self.is_idiosyncratic = None
        self.beta_1y = None
        self.sector_corr_90d = None
        self.per = None
        self.pbr = None


class _BriefingFixture:
    """Fixture for Briefing that validates attributes match the model schema"""
    def __init__(self):
        self.situation_summary = None
        self.initial_class = None
        self.initial_class_jp = None


def _make_event():
    e = _DipEventFixture.__new__(_DipEventFixture)
    e.symbol = "CRWD"
    e.trigger_date = "2024-07-19"
    e.change_pct_1d = -11.2
    e.change_pct_5d = -8.7
    e.status = "interviewed"
    e.macro_flag = 0
    return e


def _make_analysis():
    a = _NumericalAnalysisFixture.__new__(_NumericalAnalysisFixture)
    a.volume_ratio_20d = 4.2
    a.is_idiosyncratic = 1
    a.beta_1y = 1.12
    a.sector_corr_90d = 0.31
    a.per = 68.3
    a.pbr = 25.1
    return a


def _make_interview():
    b = _BriefingFixture.__new__(_BriefingFixture)
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
    a1 = MagicMock()
    a1.title = "CrowdStrike global outage"
    a1.url = "https://example.com/1"
    a1.before_trigger = False
    a2 = MagicMock()
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
    meta = MagicMock()
    meta.name_ja = None
    meta.name = "CrowdStrike Holdings"
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


def test_build_diagnosis_prompt_includes_classification_definition():
    prompt = build_diagnosis_prompt(_make_event(), None, _make_interview(), [])
    assert "Q1" in prompt
    assert "Q2" in prompt
    assert "Q3" in prompt
    assert "意図的な悪質行為" in prompt
    assert "structural" in prompt
    assert "macro" in prompt


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


def test_parse_diagnosis_response_normalizes_invalid_class():
    # LLM がプロンプトの説明文を丸写ししたケース（監査 1-2）
    text = json.dumps({
        "initial_class": "accident / incident / structural / macro / unknown — 上記2軸決定木に厳密に従うこと"
    })
    parsed = parse_diagnosis_response(text)
    assert parsed["initial_class"] == "unknown"


def test_parse_diagnosis_response_accepts_structural_and_macro():
    assert parse_diagnosis_response(json.dumps({"initial_class": "structural"}))["initial_class"] == "structural"
    assert parse_diagnosis_response(json.dumps({"initial_class": "macro"}))["initial_class"] == "macro"


def test_build_diagnosis_prompt_output_example_covers_five_classes():
    prompt = build_diagnosis_prompt(_make_event(), None, _make_interview(), [])
    assert "事故型/事件型/構造型/マクロ型/不明" in prompt
    assert "この分類が誤っている可能性" in prompt
    # 説明文の丸写し事故を防ぐため、値指定は簡潔な列挙のみ
    assert "厳密に従うこと" not in prompt


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _seed_db(session) -> tuple:
    from app.models.dip import DipEvent
    from app.models.briefing import Briefing
    event = DipEvent(
        symbol="CRWD", detected_date="2024-07-19", trigger_date="2024-07-19",
        change_pct_1d=-11.2, change_pct_5d=-8.7,
        status="interviewed", macro_flag=0,
        created_at="2024-07-19T00:00:00", updated_at="2024-07-19T00:00:00",
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
async def test_run_diagnosis_creates_briefing(db_session):
    event, interview = await _seed_db(db_session)

    with patch("app.intelligence.diagnosis.generate", return_value=(_mock_llm_response(), 15.3)):
        result = await run_diagnosis(db_session, event, None, interview, [])

    assert result is not None
    assert result.briefing_type == "diagnosis"
    assert result.initial_class == "accident"
    assert result.accident_subtype == "システム障害"
    assert result.confidence == "medium"
    assert result.generation_sec == pytest.approx(15.3)
    assert result.model_name is not None
    moat = json.loads(result.moat_json)
    assert moat["switching_cost"] == "高"


@pytest.mark.asyncio
async def test_run_diagnosis_updates_event_status(db_session):
    event, interview = await _seed_db(db_session)

    with patch("app.intelligence.diagnosis.generate", return_value=(_mock_llm_response(), 10.0)):
        await run_diagnosis(db_session, event, None, interview, [])

    await db_session.refresh(event)
    assert event.status == "diagnosed"


@pytest.mark.asyncio
async def test_run_diagnosis_ollama_failure_returns_none(db_session):
    event, interview = await _seed_db(db_session)

    with patch("app.intelligence.diagnosis.generate", side_effect=Exception("Connection refused")):
        result = await run_diagnosis(db_session, event, None, interview, [])

    assert result is None
    await db_session.refresh(event)
    assert event.status == "interviewed"


@pytest.mark.asyncio
async def test_run_diagnosis_second_run_updates_is_latest(db_session):
    event, interview = await _seed_db(db_session)

    with patch("app.intelligence.diagnosis.generate", return_value=(_mock_llm_response(), 10.0)):
        first = await run_diagnosis(db_session, event, None, interview, [])
    with patch("app.intelligence.diagnosis.generate", return_value=(_mock_llm_response(), 12.0)):
        second = await run_diagnosis(db_session, event, None, interview, [])

    await db_session.refresh(first)
    assert first.is_latest == 0
    assert second.is_latest == 1


async def test_run_diagnosis_structural_maps_to_jp(db_session):
    from datetime import datetime, timezone
    from app.models.dip import DipEvent
    from app.models.briefing import Briefing

    now = datetime.now(timezone.utc).isoformat()
    event = DipEvent(
        symbol="7203.T", detected_date="2026-07-06", trigger_date="2026-07-06",
        change_pct_1d=-6.5, status="interviewed", macro_flag=0,
        created_at=now, updated_at=now,
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)

    interview = Briefing(
        dip_event_id=event.id, briefing_type="interview",
        initial_class="structural", initial_class_jp="構造型",
        situation_summary="国内販売シェアの継続的低下。",
        created_at=now, is_latest=1,
    )
    db_session.add(interview)
    await db_session.commit()

    llm_json = json.dumps({"initial_class": "structural", "confidence": "high"})
    with patch("app.intelligence.diagnosis.generate", new=AsyncMock(return_value=(llm_json, 2.0))):
        briefing = await run_diagnosis(db_session, event, None, interview, [])

    assert briefing is not None
    assert briefing.initial_class == "structural"
    assert briefing.initial_class_jp == "構造型"
