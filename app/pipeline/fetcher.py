"""第0段階：yfinance からの株価データ取得"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import NamedTuple

import io
import requests
import pandas as pd
import yfinance as yf

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DipTriage/1.0; +https://github.com/DipTriage)"}

logger = logging.getLogger(__name__)

US_SECTOR_ETF_MAP: dict[str, str] = {
    "Information Technology": "XLK",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Consumer Discretionary": "XLY",
    "Communication Services": "XLC",
    "Industrials": "XLI",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Materials": "XLB",
}


class PriceRow(NamedTuple):
    symbol: str
    date: str
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume: float | None
    adj_close: float | None


class IndexPriceRow(NamedTuple):
    symbol: str
    date: str
    close: float
    change_pct: float | None


class StockInfo(NamedTuple):
    symbol: str
    name: str
    market: str
    exchange: str | None
    sector: str | None
    sector_etf: str | None
    index_name: str


def get_sp500_symbols() -> list[StockInfo]:
    try:
        html = requests.get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers=_HEADERS, timeout=15,
        ).text
        tables = pd.read_html(io.StringIO(html), attrs={"id": "constituents"})
        df = tables[0]
        result = []
        for _, row in df.iterrows():
            symbol = str(row["Symbol"]).replace(".", "-")
            sector = str(row.get("GICS Sector", ""))
            result.append(StockInfo(
                symbol=symbol,
                name=str(row.get("Security", symbol)),
                market="US",
                exchange=str(row.get("Exchange", None)),
                sector=sector if sector else None,
                sector_etf=US_SECTOR_ETF_MAP.get(sector),
                index_name="S&P500",
            ))
        logger.info("S&P 500: %d symbols fetched", len(result))
        return result
    except Exception as e:
        logger.error("Failed to fetch S&P 500 symbols: %s", e)
        return []


def get_nikkei225_symbols() -> list[StockInfo]:
    try:
        html = requests.get(
            "https://en.wikipedia.org/wiki/Nikkei_225",
            headers=_HEADERS, timeout=15,
        ).text
        tables = pd.read_html(io.StringIO(html))
        # Nikkei 225 の表は複数あるので、Code 列を持つものを探す
        for df in tables:
            code_col = None
            for c in df.columns:
                if "code" in str(c).lower():
                    code_col = c
                    break
            if code_col is None:
                continue

            name_col = None
            for c in df.columns:
                if "name" in str(c).lower() or "company" in str(c).lower():
                    name_col = c
                    break

            result = []
            for _, row in df.iterrows():
                code = str(row[code_col]).strip().zfill(4)
                if not code.isdigit():
                    continue
                symbol = f"{code}.T"
                name = str(row[name_col]) if name_col else symbol
                result.append(StockInfo(
                    symbol=symbol,
                    name=name,
                    market="JP",
                    exchange="TSE",
                    sector=None,
                    sector_etf=None,
                    index_name="Nikkei225",
                ))
            if result:
                logger.info("Nikkei 225: %d symbols fetched", len(result))
                return result
    except Exception as e:
        logger.error("Failed to fetch Nikkei 225 symbols: %s", e)
    return []


def fetch_prices(symbols: list[str], days: int = 2, end_date: str | None = None) -> dict[str, pd.DataFrame]:
    """複数銘柄の株価を一括取得。{symbol: DataFrame} を返す。
    end_date: "YYYY-MM-DD" 形式。省略時は今日。バックフィル時に指定する。
    """
    if not symbols:
        return {}

    period_days = max(days + 5, 10)  # 休場日を考慮して余分に取得
    if end_date:
        end = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    else:
        end = datetime.now()
    start = end - timedelta(days=period_days)

    try:
        raw = yf.download(
            symbols,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            auto_adjust=True,
            progress=False,
            group_by="ticker",
            threads=True,
        )
    except Exception as e:
        logger.error("yf.download failed: %s", e)
        return {}

    result: dict[str, pd.DataFrame] = {}

    if len(symbols) == 1:
        sym = symbols[0]
        if not raw.empty:
            result[sym] = raw
    else:
        for sym in symbols:
            try:
                df = raw[sym].dropna(how="all")
                if not df.empty:
                    result[sym] = df
            except KeyError:
                pass

    return result


def extract_price_rows(sym: str, df: pd.DataFrame, n_days: int = 2) -> list[PriceRow]:
    """DataFrame から直近 n_days 日分の PriceRow を抽出する。"""
    rows = []
    for dt, row in df.tail(n_days).iterrows():
        date_str = pd.Timestamp(dt).strftime("%Y-%m-%d")
        close = float(row["Close"]) if "Close" in row and not pd.isna(row["Close"]) else None
        if close is None:
            continue
        vol = float(row["Volume"]) if "Volume" in row and not pd.isna(row["Volume"]) else None
        if vol == 0.0:
            vol = None
        rows.append(PriceRow(
            symbol=sym,
            date=date_str,
            open=float(row["Open"]) if "Open" in row and not pd.isna(row["Open"]) else None,
            high=float(row["High"]) if "High" in row and not pd.isna(row["High"]) else None,
            low=float(row["Low"]) if "Low" in row and not pd.isna(row["Low"]) else None,
            close=close,
            volume=vol,
            adj_close=None,  # auto_adjust=True のため Close = Adj Close
        ))
    return rows


def fetch_index_price_rows(index_symbols: list[str], end_date: str | None = None) -> list[IndexPriceRow]:
    """指数（^GSPC, ^N225 等）の直近2日分を取得し変化率を計算する。"""
    prices = fetch_prices(index_symbols, days=5, end_date=end_date)
    rows = []
    for sym, df in prices.items():
        df = df.sort_index()
        closes = df["Close"].dropna().tail(2)
        if len(closes) < 2:
            continue
        prev_close, today_close = float(closes.iloc[-2]), float(closes.iloc[-1])
        change_pct = (today_close - prev_close) / prev_close * 100
        date_str = pd.Timestamp(closes.index[-1]).strftime("%Y-%m-%d")
        rows.append(IndexPriceRow(
            symbol=sym,
            date=date_str,
            close=today_close,
            change_pct=change_pct,
        ))
    return rows
