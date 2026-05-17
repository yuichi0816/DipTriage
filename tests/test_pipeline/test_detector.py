"""急落検知純粋関数のユニットテスト"""
import pytest
from app.pipeline.detector import DipCandidate, MacroFilterResult, apply_macro_filter, screen_dips


class TestApplyMacroFilter:
    def test_no_shock(self):
        result = apply_macro_filter({"^GSPC": -1.0, "^N225": -0.5})
        assert result.is_macro_shock is False

    def test_shock_detected(self):
        result = apply_macro_filter({"^GSPC": -2.5, "^N225": -0.5})
        assert result.is_macro_shock is True
        assert "^GSPC" in result.note

    def test_both_shock(self):
        result = apply_macro_filter({"^GSPC": -3.0, "^N225": -2.1})
        assert result.is_macro_shock is True

    def test_empty_index_changes(self):
        result = apply_macro_filter({})
        assert result.is_macro_shock is False

    def test_custom_threshold(self):
        result = apply_macro_filter({"^GSPC": -1.5}, threshold=-1.0)
        assert result.is_macro_shock is True


class TestScreenDips:
    def _make_candidate(self, symbol: str, change: float) -> DipCandidate:
        return DipCandidate(symbol=symbol, trigger_date="2024-07-19", change_pct_1d=change)

    def test_filters_by_threshold(self):
        candidates = [
            self._make_candidate("CRWD", -11.2),
            self._make_candidate("AAPL", -0.5),
            self._make_candidate("TSLA", -5.1),
        ]
        result = screen_dips(candidates)
        symbols = [c.symbol for c in result]
        assert "CRWD" in symbols
        assert "TSLA" in symbols
        assert "AAPL" not in symbols

    def test_macro_flag_applied(self):
        candidates = [self._make_candidate("CRWD", -11.2)]
        macro = MacroFilterResult(is_macro_shock=True, note="マクロ: -3%")
        result = screen_dips(candidates, macro_result=macro)
        assert result[0].macro_flag == 1
        assert result[0].macro_note == "マクロ: -3%"

    def test_no_macro_flag_when_no_shock(self):
        candidates = [self._make_candidate("CRWD", -11.2)]
        macro = MacroFilterResult(is_macro_shock=False, note="")
        result = screen_dips(candidates, macro_result=macro)
        assert result[0].macro_flag == 0

    def test_empty_candidates(self):
        assert screen_dips([]) == []

    def test_exactly_at_threshold_excluded(self):
        # -5.0% は threshold と同値 → screen_dips は <= なので含まれる
        candidates = [self._make_candidate("X", -5.0)]
        result = screen_dips(candidates, threshold=-5.0)
        assert len(result) == 1
