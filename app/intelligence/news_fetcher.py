"""Stage 3a: Yahoo Finance RSS からニュースを取得し DB に保存する。"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DipEvent, NewsArticle

logger = logging.getLogger(__name__)


def compute_content_hash(title: str, url: str) -> str:
    """重複検出用の sha256 ハッシュを生成する。"""
    return hashlib.sha256(f"{title}||{url}".encode()).hexdigest()


def classify_before_trigger(published_at: str | None, trigger_date: str) -> int | None:
    """
    記事の公開日と急落日を比較し before_trigger を分類する。
    1=急落前（原因記事候補）、0=後追い記事、None=同日または判定不能
    """
    if published_at is None:
        return None
    try:
        try:
            pub_dt = parsedate_to_datetime(published_at)
        except Exception:
            pub_dt = datetime.fromisoformat(published_at)
        if pub_dt.tzinfo is None:
            pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        trigger_dt = datetime.strptime(trigger_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        pub_date = pub_dt.date()
        trig_date = trigger_dt.date()
        if pub_date < trig_date:
            return 1
        elif pub_date > trig_date:
            return 0
        else:
            return None
    except Exception:
        return None


def normalize_published_at(published: str | None) -> str | None:
    """RSS の公開日時を UTC ISO 8601 文字列に正規化する（監査 2-4）。

    文字列ソートで時系列順になることを保証する。変換不能なら None。
    """
    if not published:
        return None
    try:
        try:
            dt = parsedate_to_datetime(published)
        except Exception:
            dt = datetime.fromisoformat(published)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


_RSS_US = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
_RSS_JP = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=JP&lang=ja-JP"
_RSS_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DipTriage/1.0)"}


async def _fetch_bytes(url: str) -> bytes:
    """タイムアウト付きで RSS を取得する（監査 3-2: feedparser 直 fetch はタイムアウト不能）。"""
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=_RSS_HEADERS) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


async def fetch_rss_articles(symbol: str) -> list[dict]:
    """Yahoo Finance RSS から記事リストを取得する。失敗時は空リストを返す。"""
    try:
        url = _RSS_JP.format(symbol=symbol) if symbol.endswith(".T") else _RSS_US.format(symbol=symbol)
        content = await _fetch_bytes(url)
        feed = feedparser.parse(content)
        articles = []
        for entry in feed.entries:
            source = getattr(getattr(entry, "source", None), "title", None)
            articles.append({
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "source": source,
                "published_at": entry.get("published"),
            })
        return articles
    except Exception as e:
        logger.warning("RSS fetch failed for %s: %s", symbol, e)
        return []


async def fetch_and_save_news(session: AsyncSession, event: DipEvent) -> list[NewsArticle]:
    """RSS を取得し、重複排除・before_trigger 分類を行い DB に保存する。"""
    raw_articles = await fetch_rss_articles(event.symbol)
    if not raw_articles:
        return []

    now = datetime.now(timezone.utc).isoformat()
    saved: list[NewsArticle] = []

    for raw in raw_articles:
        url = raw["url"]
        if not url:
            continue

        existing = await session.execute(
            select(NewsArticle)
            .where(NewsArticle.dip_event_id == event.id, NewsArticle.url == url)
            .limit(1)
        )
        if existing.scalar_one_or_none():
            continue

        published = normalize_published_at(raw["published_at"])

        article = NewsArticle(
            dip_event_id=event.id,
            symbol=event.symbol,
            title=raw["title"],
            url=url,
            source=raw["source"],
            source_type="news",
            priority=5,
            published_at=published,
            fetched_at=now,
            content_hash=compute_content_hash(raw["title"], url),
            is_duplicate=0,
            before_trigger=classify_before_trigger(published, event.trigger_date),
        )
        session.add(article)
        saved.append(article)

    await session.commit()
    logger.info("Saved %d news articles for %s", len(saved), event.symbol)
    return saved
