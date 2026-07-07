"""急落検知純粋関数のユニットテスト"""
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, StockPrice
from app.pipeline.detector import DipCandidate, MacroFilterResult, apply_macro_filter, get_price_changes, resolve_target_date, screen_dips
from app.pipeline.fetcher import PriceRow


def _price_row(sym: str, date: str) -> PriceRow:
    return PriceRow(symbol=sym, date=date, open=None, high=None, low=None,
                    close=100.0, volume=None, adj_close=None)


async def _setup_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def test_get_price_changes_filters_to_universe():
    # ETF (XLE) が stock_prices にあってもユニバース指定で除外される（監査 2-3）
    engine, Session = await _setup_db()
    async with Session() as session:
        for sym in ("AAA", "XLE"):
            session.add(StockPrice(symbol=sym, date="2026-07-03", close=100.0))
            session.add(StockPrice(symbol=sym, date="2026-07-06", close=90.0))
        await session.commit()

        candidates = await get_price_changes(session, "2026-07-06", symbols=["AAA"])

    assert [c.symbol for c in candidates] == ["AAA"]
    await engine.dispose()


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


class TestResolveTargetDate:
    def test_requested_date_passthrough(self):
        # 手動バックフィル指定はそのまま尊重する
        rows = [_price_row("A", "2026-07-06")]
        assert resolve_target_date(rows, "2026-07-01", "2026-07-07") == "2026-07-01"

    def test_auto_mode_uses_latest_available_bar(self):
        # 07:00 JST 実行: 当日バーはまだ無い → 前営業日に解決される（監査 2-1）
        rows = [_price_row("A", "2026-07-03"), _price_row("B", "2026-07-06")]
        assert resolve_target_date(rows, None, "2026-07-07") == "2026-07-06"

    def test_auto_mode_no_rows_falls_back_to_today(self):
        assert resolve_target_date([], None, "2026-07-07") == "2026-07-07"
