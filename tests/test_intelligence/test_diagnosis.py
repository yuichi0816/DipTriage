import json
import pytest
from unittest.mock import MagicMock
from app.intelligence.diagnosis import build_diagnosis_prompt


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
    meta.company_name = "CrowdStrike Holdings"
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
