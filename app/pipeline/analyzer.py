"""第2段階：数値分析（出来高異常度、ボラティリティ、β値、セクター相対等）"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import numpy as np
import yfinance as yf
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DipEvent, NumericalAnalysis, StockPrice

logger = logging.getLogger(__name__)


def _get_closes(df_prices: list[float]) -> np.ndarray:
    return np.array(df_prices, dtype=float)


async def _fetch_close_series(session: AsyncSession, symbol: str, end_date: str, days: int) -> list[float]:
    """DB から直近 days 日分の終値を取得する（新しい順）。"""
    result = await session.execute(
        select(StockPrice.close)
        .where(StockPrice.symbol == symbol, StockPrice.date <= end_date)
        .order_by(StockPrice.date.desc())
        .limit(days)
    )
    return [row[0] for row in result.fetchall()]


async def _fetch_volume_series(session: AsyncSession, symbol: str, end_date: str, days: int) -> list[float | None]:
    result = await session.execute(
        select(StockPrice.volume)
        .where(StockPrice.symbol == symbol, StockPrice.date <= end_date)
        .order_by(StockPrice.date.desc())
        .limit(days)
    )
    return [row[0] for row in result.fetchall()]


def calculate_volume_ratio(volumes: list[float | None], window: int = 20) -> float | None:
    """当日出来高 / 過去 window 日平均出来高。"""
    if not volumes:
        return None
    today_vol = volumes[0]
    if today_vol is None or today_vol <= 0:
        return None
    historical = [v for v in volumes[1:] if v is not None and v > 0]
    if len(historical) < 2:
        return None
    avg = float(np.mean(historical[:window]))
    if avg == 0:
        return None
    return today_vol / avg


def calculate_volatility(closes: list[float], change_pct_1d: float) -> tuple[float | None, float | None]:
    """
    (年率σ, 今回の下落が何σか) を返す。
    closes は新しい順のリスト。
    """
    if len(closes) < 20:
        return None, None
    prices = np.array(closes[::-1], dtype=float)  # 古い順に並べ替え
    returns = np.diff(np.log(prices))
    sigma_daily = float(np.std(returns, ddof=1))
    sigma_annual = sigma_daily * np.sqrt(252)
    if sigma_daily == 0:
        return sigma_annual, None
    daily_return = change_pct_1d / 100
    deviation = abs(daily_return) / sigma_daily
    return sigma_annual, deviation


def calculate_beta(stock_closes: list[float], market_closes: list[float]) -> float | None:
    """過去 252 日のβ値を計算する。"""
    n = min(len(stock_closes), len(market_closes), 252)
    if n < 20:
        return None
    s = np.array(stock_closes[:n][::-1], dtype=float)
    m = np.array(market_closes[:n][::-1], dtype=float)
    sr = np.diff(np.log(s))
    mr = np.diff(np.log(m))
    if len(sr) < 10 or np.var(mr) == 0:
        return None
    cov = np.cov(sr, mr)[0, 1]
    var_m = np.var(mr, ddof=1)
    return float(cov / var_m)


def calculate_sector_metrics(
    stock_closes: list[float],
    sector_closes: list[float],
    change_pct_1d: float,
    sector_change_pct: float,
) -> dict[str, float | None]:
    """セクター相対パフォーマンスと90日相関係数を計算する。"""
    sector_relative = change_pct_1d - sector_change_pct

    n = min(len(stock_closes), len(sector_closes), 90)
    corr_90d = None
    if n >= 20:
        s = np.array(stock_closes[:n][::-1], dtype=float)
        sec = np.array(sector_closes[:n][::-1], dtype=float)
        sr = np.diff(np.log(s + 1e-9))
        secr = np.diff(np.log(sec + 1e-9))
        if np.std(sr) > 0 and np.std(secr) > 0:
            corr_90d = float(np.corrcoef(sr, secr)[0, 1])

    return {
        "sector_relative": sector_relative,
        "sector_corr_90d": corr_90d,
    }


def score_idiosyncratic(
    sector_relative: float | None,
    sector_corr_90d: float | None,
    beta: float | None,
) -> tuple[int | None, float | None]:
    """
    銘柄固有性スコア（0〜1）を算出する。
    sector_relative が大きく負 → 固有
    sector_corr が低い → 固有
    β が低い → マクロ連動しにくい
    """
    scores = []
    if sector_relative is not None:
        # -5% 以上の超過下落 → スコア 1.0
        scores.append(min(1.0, max(0.0, -sector_relative / 5.0)))
    if sector_corr_90d is not None:
        # 相関が低いほどスコアが高い（1 - corr）
        scores.append(max(0.0, 1.0 - abs(sector_corr_90d)))
    if beta is not None:
        # beta <= 0.5 → マクロ連動が低い → 銘柄固有性が高い（0〜1 にクリップ）
        scores.append(max(0.0, min(1.0, 1.0 - beta / 2.0)))
    if not scores:
        return None, None
    score = float(np.mean(scores))
    is_idiosyncratic = 1 if score >= 0.4 else 0
    return is_idiosyncratic, score


def fetch_fundamentals(symbol: str) -> dict[str, float | None]:
    """yfinance.Ticker.info から PER、PBR、自己資本比率、時価総額を取得する。"""
    try:
        info = yf.Ticker(symbol).info
        per = info.get("trailingPE") or info.get("forwardPE")
        pbr = info.get("priceToBook")
        market_cap = info.get("marketCap")
        total_equity = info.get("totalStockholderEquity") or info.get("bookValue")
        total_assets = info.get("totalAssets")
        equity_ratio = None
        if total_equity and total_assets and total_assets > 0:
            equity_ratio = total_equity / total_assets * 100
        return {
            "per": float(per) if per else None,
            "pbr": float(pbr) if pbr else None,
            "market_cap": float(market_cap) if market_cap else None,
            "equity_ratio": float(equity_ratio) if equity_ratio else None,
        }
    except Exception as e:
        logger.warning("Failed to fetch fundamentals for %s: %s", symbol, e)
        return {"per": None, "pbr": None, "market_cap": None, "equity_ratio": None}


async def analyze_dip_event(
    session: AsyncSession,
    event: DipEvent,
    sector_etf: str | None = None,
    market_index: str = "^GSPC",
) -> NumericalAnalysis | None:
    """1件の DipEvent に対して数値分析を実行し NumericalAnalysis を保存する。"""
    existing_result = await session.execute(
        select(NumericalAnalysis).where(NumericalAnalysis.dip_event_id == event.id).limit(1)
    )
    if existing_result.scalar_one_or_none():
        logger.debug("Analysis already exists for dip_event_id=%d, skipping", event.id)
        return None

    trigger_date = event.trigger_date

    # 出来高
    volumes = await _fetch_volume_series(session, event.symbol, trigger_date, 25)
    vol_ratio = calculate_volume_ratio(volumes, window=20)

    # ボラティリティ
    closes = await _fetch_close_series(session, event.symbol, trigger_date, 260)
    sigma_annual, vol_dev = calculate_volatility(closes, event.change_pct_1d)

    # β値（市場指数との相関）
    market_sym = market_index
    market_closes = await _fetch_close_series(session, market_sym, trigger_date, 260)
    beta = calculate_beta(closes, market_closes) if market_closes else None

    # セクター相対
    sector_change_pct = None
    sector_relative = None
    sector_corr_90d = None
    if sector_etf:
        sector_closes = await _fetch_close_series(session, sector_etf, trigger_date, 95)
        if len(sector_closes) >= 2:
            sector_change_pct = (sector_closes[0] - sector_closes[1]) / sector_closes[1] * 100 if sector_closes[1] else None
            if sector_change_pct is not None:
                metrics = calculate_sector_metrics(closes, sector_closes, event.change_pct_1d, sector_change_pct)
                sector_relative = metrics["sector_relative"]
                sector_corr_90d = metrics["sector_corr_90d"]

    # 銘柄固有性スコア
    is_idiosyncratic, idiosyncratic_score = score_idiosyncratic(sector_relative, sector_corr_90d, beta)

    # ファンダメンタルズ（同期 API をスレッドで実行してイベントループをブロックしない）
    fundamentals = await asyncio.to_thread(fetch_fundamentals, event.symbol)

    now = datetime.now(timezone.utc).isoformat()
    analysis = NumericalAnalysis(
        dip_event_id=event.id,
        volume_ratio_20d=vol_ratio,
        volatility_1y_sigma=sigma_annual,
        vol_deviation=vol_dev,
        beta_1y=beta,
        sector_change_pct=sector_change_pct,
        sector_relative=sector_relative,
        sector_corr_90d=sector_corr_90d,
        per=fundamentals["per"],
        pbr=fundamentals["pbr"],
        market_cap=fundamentals["market_cap"],
        equity_ratio=fundamentals["equity_ratio"],
        is_idiosyncratic=is_idiosyncratic,
        idiosyncratic_score=idiosyncratic_score,
        created_at=now,
    )
    session.add(analysis)
    await session.commit()
    await session.refresh(analysis)
    logger.info("Analyzed %s: vol_ratio=%.1f, vol_dev=%.1f, idiosyncratic=%s",
                event.symbol,
                vol_ratio or 0,
                vol_dev or 0,
                is_idiosyncratic)
    return analysis
