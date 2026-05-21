"""パイプラインオーケストレーター：第0〜2段階を順番に実行する"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import nullslast, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.config import INDEX_SYMBOLS
from app.database import AsyncSessionLocal
from app.intelligence.interview import run_interview
from app.intelligence.news_fetcher import fetch_and_save_news
from app.models import DipEvent, IndexPrice, NewsArticle, NumericalAnalysis, StockMeta, StockPrice
from app.models.settings import AppSettings
from app.models.watchlist import WatchlistEntry, WatchlistSnapshot
from app.pipeline.analyzer import analyze_dip_event
from app.pipeline.detector import apply_macro_filter, get_price_changes, save_dip_events, screen_dips
from app.pipeline.fetcher import (
    StockInfo,
    extract_price_rows,
    fetch_index_price_rows,
    fetch_prices,
    get_nikkei225_symbols,
    get_sp500_symbols,
    get_tse_segment_symbols,
)

logger = logging.getLogger(__name__)


async def _upsert_stock_meta(session, stock_infos) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for info in stock_infos:
        stmt = sqlite_insert(StockMeta).values(
            symbol=info.symbol,
            name=info.name,
            name_ja=info.name_ja,
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
            set_={"name": info.name, "name_ja": info.name_ja, "sector": info.sector, "updated_at": now},
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


async def snapshot_watching_entries(session, today: str) -> None:
    """Stage 4: watching 中エントリの日次スナップショットを保存する。"""
    result = await session.execute(
        select(WatchlistEntry).where(WatchlistEntry.status == "watching")
    )
    entries = result.scalars().all()

    for entry in entries:
        price_r = await session.execute(
            select(StockPrice)
            .where(StockPrice.symbol == entry.symbol)
            .order_by(StockPrice.date.desc())
            .limit(1)
        )
        price_rec = price_r.scalar_one_or_none()
        if not price_rec:
            logger.warning("No price data for watchlist entry %s (%s)", entry.id, entry.symbol)
            continue

        close_price = price_rec.close
        recovery_pct = (
            (close_price - entry.trigger_price) / entry.trigger_price * 100
            if entry.trigger_price
            else 0.0
        )

        stmt = sqlite_insert(WatchlistSnapshot).values(
            watchlist_entry_id=entry.id,
            snapshot_date=today,
            close_price=close_price,
            recovery_pct=recovery_pct,
            new_news_count=0,
        ).on_conflict_do_nothing()
        await session.execute(stmt)

    await session.commit()


async def run_daily_pipeline(
    target_date: str | None = None,
    on_stage: Callable[[str, str, str], None] | None = None,
    max_stage: int = 4,
) -> dict:
    """
    第0〜4段階を順番に実行する。max_stage で深度を制御できる。
    target_date: "YYYY-MM-DD" 形式。None なら今日。
    on_stage: ステージ進捗コールバック (stage, current, total)
    max_stage: 実行する最終ステージ番号 (1=急落検知, 2=数値分析, 3=ニュース取得, 4=AI問診/完全実行)
    """
    def _notify(stage: str, current: str = "", total: str = "") -> None:
        if on_stage:
            on_stage(stage, current, total)

    if target_date is None:
        target_date = datetime.now().strftime("%Y-%m-%d")

    logger.info("=== Pipeline start: %s ===", target_date)
    stats = {"date": target_date, "dips_detected": 0, "dips_analyzed": 0}

    async with AsyncSessionLocal() as session:
        # ── DB から取得対象設定を読み込む ──
        settings_r = await session.execute(select(AppSettings).where(AppSettings.id == 1))
        app_settings = settings_r.scalar_one_or_none()
        include_nikkei225 = bool(getattr(app_settings, "include_nikkei225", 1) if app_settings else 1)
        include_standard  = bool(getattr(app_settings, "include_standard",  0) if app_settings else 0)
        include_growth    = bool(getattr(app_settings, "include_growth",    0) if app_settings else 0)
        include_sp500     = bool(getattr(app_settings, "include_sp500",     1) if app_settings else 1)
        dip_lookback_days = app_settings.dip_lookback_days if app_settings else 2

        # ── 第0段階：銘柄マスター更新 ──
        _notify("Stage 0: シンボル取得")
        logger.info(
            "Stage 0: Fetching symbol universe (nikkei225=%s, standard=%s, growth=%s, sp500=%s)",
            include_nikkei225, include_standard, include_growth, include_sp500,
        )
        all_stocks: list[StockInfo] = []

        if include_nikkei225:
            nikkei = get_nikkei225_symbols()
            if not nikkei:
                cached_r = await session.execute(
                    select(StockMeta).where(StockMeta.index_name == "Nikkei225", StockMeta.is_active == 1)
                )
                nikkei = [
                    StockInfo(
                        symbol=s.symbol,
                        name=s.name or s.symbol,
                        market=s.market or "JP",
                        exchange=s.exchange or "TSE",
                        sector=s.sector,
                        sector_etf=None,
                        index_name="Nikkei225",
                    )
                    for s in cached_r.scalars().all()
                ]
                if nikkei:
                    logger.warning("Nikkei225 web scraping failed; using %d cached symbols from DB.", len(nikkei))
                else:
                    logger.error("No Nikkei225 symbols from web or DB.")
            all_stocks.extend(nikkei)

        if include_standard:
            standard = get_tse_segment_symbols("スタンダード（内国株式）", "TSE Standard")
            if not standard:
                cached_r = await session.execute(
                    select(StockMeta).where(StockMeta.index_name == "TSE Standard", StockMeta.is_active == 1)
                )
                standard = [
                    StockInfo(
                        symbol=s.symbol,
                        name=s.name or s.symbol,
                        market=s.market or "JP",
                        exchange=s.exchange or "TSE",
                        sector=s.sector,
                        sector_etf=None,
                        index_name="TSE Standard",
                    )
                    for s in cached_r.scalars().all()
                ]
                if standard:
                    logger.warning("TSE Standard JPX fetch failed; using %d cached symbols from DB.", len(standard))
                else:
                    logger.error("No TSE Standard symbols from JPX or DB.")
            all_stocks.extend(standard)

        if include_growth:
            growth = get_tse_segment_symbols("グロース（内国株式）", "TSE Growth")
            if not growth:
                cached_r = await session.execute(
                    select(StockMeta).where(StockMeta.index_name == "TSE Growth", StockMeta.is_active == 1)
                )
                growth = [
                    StockInfo(
                        symbol=s.symbol,
                        name=s.name or s.symbol,
                        market=s.market or "JP",
                        exchange=s.exchange or "TSE",
                        sector=s.sector,
                        sector_etf=None,
                        index_name="TSE Growth",
                    )
                    for s in cached_r.scalars().all()
                ]
                if growth:
                    logger.warning("TSE Growth JPX fetch failed; using %d cached symbols from DB.", len(growth))
                else:
                    logger.error("No TSE Growth symbols from JPX or DB.")
            all_stocks.extend(growth)

        if include_sp500:
            all_stocks.extend(get_sp500_symbols())

        await _upsert_stock_meta(session, all_stocks)
        logger.info("Universe: %d stocks", len(all_stocks))

        # ── 第0段階：指数データ取得 ──
        _notify("Stage 0: 指数データ取得")
        has_jp = include_nikkei225 or include_standard or include_growth
        index_syms = (
            ([INDEX_SYMBOLS["JP"]] if has_jp else []) +
            ([INDEX_SYMBOLS["US"]] if include_sp500 else [])
        ) or list(INDEX_SYMBOLS.values())
        index_rows = fetch_index_price_rows(index_syms, end_date=target_date)
        await _save_index_prices(session, index_rows)
        index_changes = {r.symbol: r.change_pct for r in index_rows if r.change_pct is not None}

        # ── 第0段階：株価データ取得 ──
        _notify("Stage 0: 株価データ取得", "0", str(len(all_stocks)))
        logger.info("Stage 0: Downloading stock prices (%d symbols)", len(all_stocks))
        all_symbols = [s.symbol for s in all_stocks]

        # セクター ETF も一緒に取得（S&P500 のみ sector_etf を保持）
        sector_etfs = list({s.sector_etf for s in all_stocks if s.sector_etf})
        download_symbols = all_symbols + sector_etfs + index_syms

        price_data = fetch_prices(download_symbols, days=dip_lookback_days, end_date=target_date)
        price_rows = []
        for sym, df in price_data.items():
            price_rows.extend(extract_price_rows(sym, df, n_days=dip_lookback_days))
        await _save_prices(session, price_rows)
        logger.info("Saved %d price rows", len(price_rows))

        # ── 第1段階：急落検知 ──
        _notify("Stage 1: 急落検知")
        logger.info("Stage 1: Detecting dips")
        macro_result = apply_macro_filter(index_changes)
        if macro_result.is_macro_shock:
            logger.warning("MACRO SHOCK detected: %s", macro_result.note)

        candidates = await get_price_changes(session, target_date)
        dip_candidates = screen_dips(candidates, macro_result=macro_result)
        dip_events = await save_dip_events(session, dip_candidates, detected_date=target_date)
        stats["dips_detected"] = len(dip_events)

        if max_stage < 2:
            return stats

        # ── 第2段階：数値分析 ──
        _notify("Stage 2: 数値分析", "0", str(len(dip_events)))
        logger.info("Stage 2: Analyzing %d dip events", len(dip_events))
        sym_to_meta = {s.symbol: s for s in all_stocks}

        for i, event in enumerate(dip_events, 1):
            _notify("Stage 2: 数値分析", str(i), str(len(dip_events)))
            meta = sym_to_meta.get(event.symbol)
            sector_etf = meta.sector_etf if meta else None
            market_index = INDEX_SYMBOLS.get("JP" if event.symbol.endswith(".T") else "US", "^GSPC")
            try:
                await analyze_dip_event(session, event, sector_etf=sector_etf, market_index=market_index)
                stats["dips_analyzed"] += 1
            except Exception as e:
                logger.error("Analysis failed for %s: %s", event.symbol, e)

        if max_stage < 3:
            return stats

        # ── 第3段階a: ニュース取得 ──
        non_macro_events = [e for e in dip_events if not e.macro_flag]
        _notify("Stage 3a: ニュース取得", "0", str(len(non_macro_events)))
        logger.info("Stage 3a: Fetching news for %d non-macro dips", len(non_macro_events))
        for i, event in enumerate(non_macro_events, 1):
            _notify("Stage 3a: ニュース取得", str(i), str(len(non_macro_events)))
            try:
                articles = await fetch_and_save_news(session, event)
                stats["news_fetched"] = stats.get("news_fetched", 0) + len(articles)
            except Exception as e:
                logger.warning("News fetch failed for %s: %s", event.symbol, e)

        if max_stage < 4:
            return stats

        # ── 第3段階b: LLM 問診 ──
        _notify("Stage 3b: LLM インタビュー", "0", str(len(non_macro_events)))
        logger.info("Stage 3b: Running interview for %d dips", len(non_macro_events))
        stats["dips_interviewed"] = 0
        for i, event in enumerate(non_macro_events, 1):
            _notify("Stage 3b: LLM インタビュー", str(i), str(len(non_macro_events)))
            news_result = await session.execute(
                select(NewsArticle)
                .where(NewsArticle.dip_event_id == event.id, NewsArticle.is_duplicate == 0)
                .order_by(nullslast(NewsArticle.before_trigger.desc()), NewsArticle.published_at.desc())
                .limit(10)
            )
            articles = news_result.scalars().all()
            if not articles:
                logger.warning("No news for %s, skipping interview", event.symbol)
                continue

            ana_result = await session.execute(
                select(NumericalAnalysis).where(NumericalAnalysis.dip_event_id == event.id).limit(1)
            )
            analysis = ana_result.scalar_one_or_none()
            meta = sym_to_meta.get(event.symbol)

            briefing = await run_interview(session, event, analysis, articles, meta=meta)
            if briefing:
                stats["dips_interviewed"] += 1

        # ── ステータス更新（analyzed）: macro_flag を問わず全 dip を analyzed に ──
        await session.execute(
            update(DipEvent)
            .where(DipEvent.detected_date == target_date, DipEvent.status == "detected")
            .values(status="analyzed", updated_at=datetime.now(timezone.utc).isoformat())
        )
        await session.commit()

        # ── 第4段階：ウォッチリスト スナップショット ──
        _notify("Stage 4: ウォッチリスト更新")
        logger.info("Stage 4: Snapshotting watching entries")
        try:
            await snapshot_watching_entries(session, target_date)
        except Exception as e:
            logger.error("Snapshot failed: %s", e)

    logger.info("=== Pipeline done: %s ===", stats)
    return stats


async def run_news_refresh(
    days: int = 5,
    on_stage: Callable[[str, str, str], None] | None = None,
) -> dict:
    """Stage 3a + 3b のみ実行。過去 days 日以内の非マクロ DipEvent を対象とする。"""
    from datetime import date, timedelta

    def _notify(stage: str, current: str = "", total: str = "") -> None:
        if on_stage:
            on_stage(stage, current, total)

    since = (date.today() - timedelta(days=days)).isoformat()
    stats: dict = {"events": 0, "news_fetched": 0, "interviewed": 0}

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(DipEvent)
            .where(DipEvent.macro_flag == 0, DipEvent.detected_date >= since)
            .order_by(DipEvent.detected_date.desc())
        )
        events = result.scalars().all()
        stats["events"] = len(events)

        meta_result = await session.execute(select(StockMeta))
        sym_to_meta = {m.symbol: m for m in meta_result.scalars().all()}

        logger.info("News refresh: %d events since %s", len(events), since)

        for i, event in enumerate(events, 1):
            _notify("Stage 3a: ニュース取得", str(i), str(len(events)))
            try:
                articles = await fetch_and_save_news(session, event)
                stats["news_fetched"] += len(articles)
            except Exception as e:
                logger.warning("News fetch failed for %s: %s", event.symbol, e)

        for i, event in enumerate(events, 1):
            _notify("Stage 3b: LLM インタビュー", str(i), str(len(events)))
            news_r = await session.execute(
                select(NewsArticle)
                .where(NewsArticle.dip_event_id == event.id, NewsArticle.is_duplicate == 0)
                .order_by(nullslast(NewsArticle.before_trigger.desc()), NewsArticle.published_at.desc())
                .limit(10)
            )
            articles = news_r.scalars().all()
            if not articles:
                logger.warning("No news for %s, skipping interview", event.symbol)
                continue

            ana_r = await session.execute(
                select(NumericalAnalysis).where(NumericalAnalysis.dip_event_id == event.id).limit(1)
            )
            analysis = ana_r.scalar_one_or_none()
            meta = sym_to_meta.get(event.symbol)
            briefing = await run_interview(session, event, analysis, articles, meta=meta)
            if briefing:
                stats["interviewed"] += 1

    logger.info("=== News refresh done: %s ===", stats)
    return stats
