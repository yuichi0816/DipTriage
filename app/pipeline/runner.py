"""パイプラインオーケストレーター：第0〜2段階を順番に実行する"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.config import INDEX_SYMBOLS
from app.database import AsyncSessionLocal
from app.models import DipEvent, IndexPrice, StockMeta, StockPrice
from app.pipeline.analyzer import analyze_dip_event
from app.pipeline.detector import apply_macro_filter, get_price_changes, save_dip_events, screen_dips
from app.pipeline.fetcher import (
    extract_price_rows,
    fetch_index_price_rows,
    fetch_prices,
    get_nikkei225_symbols,
    get_sp500_symbols,
)

logger = logging.getLogger(__name__)


async def _upsert_stock_meta(session, stock_infos) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for info in stock_infos:
        stmt = sqlite_insert(StockMeta).values(
            symbol=info.symbol,
            name=info.name,
            market=info.market,
            exchange=info.exchange,
            sector=info.sector,
            sector_etf=info.sector_etf,
            index_name=info.index_name,
            is_active=1,
            created_at=now,
            updated_at=now,
        ).on_conflict_do_update(
            index_elements=["symbol"],
            set_={"name": info.name, "sector": info.sector, "updated_at": now},
        )
        await session.execute(stmt)
    await session.commit()


async def _save_prices(session, price_rows) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for row in price_rows:
        stmt = sqlite_insert(StockPrice).values(
            symbol=row.symbol,
            date=row.date,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
            adj_close=row.adj_close,
        ).on_conflict_do_nothing(index_elements=["symbol", "date"])
        await session.execute(stmt)
    await session.commit()


async def _save_index_prices(session, index_rows) -> None:
    for row in index_rows:
        stmt = sqlite_insert(IndexPrice).values(
            symbol=row.symbol,
            date=row.date,
            close=row.close,
            change_pct=row.change_pct,
        ).on_conflict_do_nothing(index_elements=["symbol", "date"])
        await session.execute(stmt)
    await session.commit()


async def run_daily_pipeline(target_date: str | None = None) -> dict:
    """
    第0〜2段階を順番に実行する。
    target_date: "YYYY-MM-DD" 形式。None なら今日。
    """
    if target_date is None:
        target_date = datetime.now().strftime("%Y-%m-%d")

    logger.info("=== Pipeline start: %s ===", target_date)
    stats = {"date": target_date, "dips_detected": 0, "dips_analyzed": 0}

    async with AsyncSessionLocal() as session:
        # ── 第0段階：銘柄マスター更新 ──
        logger.info("Stage 0: Fetching symbol universe")
        sp500 = get_sp500_symbols()
        nikkei = get_nikkei225_symbols()
        all_stocks = sp500 + nikkei
        await _upsert_stock_meta(session, all_stocks)
        logger.info("Universe: %d stocks", len(all_stocks))

        # ── 第0段階：指数データ取得 ──
        index_syms = list(INDEX_SYMBOLS.values())
        index_rows = fetch_index_price_rows(index_syms, end_date=target_date)
        await _save_index_prices(session, index_rows)
        index_changes = {r.symbol: r.change_pct for r in index_rows if r.change_pct is not None}

        # ── 第0段階：株価データ取得 ──
        logger.info("Stage 0: Downloading stock prices (%d symbols)", len(all_stocks))
        all_symbols = [s.symbol for s in all_stocks]

        # セクター ETF も一緒に取得
        sector_etfs = list({s.sector_etf for s in sp500 if s.sector_etf})
        download_symbols = all_symbols + sector_etfs + index_syms

        price_data = fetch_prices(download_symbols, days=2, end_date=target_date)
        price_rows = []
        for sym, df in price_data.items():
            price_rows.extend(extract_price_rows(sym, df, n_days=2))
        await _save_prices(session, price_rows)
        logger.info("Saved %d price rows", len(price_rows))

        # ── 第1段階：急落検知 ──
        logger.info("Stage 1: Detecting dips")
        macro_result = apply_macro_filter(index_changes)
        if macro_result.is_macro_shock:
            logger.warning("MACRO SHOCK detected: %s", macro_result.note)

        candidates = await get_price_changes(session, target_date)
        dip_candidates = screen_dips(candidates, macro_result=macro_result)
        dip_events = await save_dip_events(session, dip_candidates, detected_date=target_date)
        stats["dips_detected"] = len(dip_events)

        # ── 第2段階：数値分析 ──
        logger.info("Stage 2: Analyzing %d dip events", len(dip_events))
        sym_to_meta = {s.symbol: s for s in all_stocks}

        for event in dip_events:
            meta = sym_to_meta.get(event.symbol)
            sector_etf = meta.sector_etf if meta else None
            market_index = INDEX_SYMBOLS.get("JP" if event.symbol.endswith(".T") else "US", "^GSPC")
            try:
                await analyze_dip_event(session, event, sector_etf=sector_etf, market_index=market_index)
                stats["dips_analyzed"] += 1
            except Exception as e:
                logger.error("Analysis failed for %s: %s", event.symbol, e)

        # ── ステータス更新 ──
        await session.execute(
            update(DipEvent)
            .where(DipEvent.detected_date == target_date, DipEvent.status == "detected")
            .values(status="analyzed", updated_at=datetime.now(timezone.utc).isoformat())
        )
        await session.commit()

    logger.info("=== Pipeline done: %s ===", stats)
    return stats
