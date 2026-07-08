from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.models import Base, DipEvent
from app.intelligence.news_fetcher import (
    classify_before_trigger,
    compute_content_hash,
    fetch_and_save_news,
    normalize_published_at,
)


class TestNormalizePublishedAt:
    def test_rfc2822_to_iso_utc(self):
        assert normalize_published_at("Mon, 06 Jul 2026 12:34:56 +0900") == "2026-07-06T03:34:56+00:00"

    def test_iso_input_normalized_to_utc(self):
        assert normalize_published_at("2026-07-06T03:34:56+00:00") == "2026-07-06T03:34:56+00:00"

    def test_naive_datetime_assumed_utc(self):
        assert normalize_published_at("2026-07-06T03:34:56") == "2026-07-06T03:34:56+00:00"

    def test_none_returns_none(self):
        assert normalize_published_at(None) is None

    def test_garbage_returns_none(self):
        assert normalize_published_at("not a date") is None


class TestComputeContentHash:
    def test_deterministic(self):
        h1 = compute_content_hash("title", "http://example.com")
        h2 = compute_content_hash("title", "http://example.com")
        assert h1 == h2

    def test_different_inputs_give_different_hash(self):
        h1 = compute_content_hash("title A", "http://example.com")
        h2 = compute_content_hash("title B", "http://example.com")
        assert h1 != h2

    def test_returns_64_char_hex_string(self):
        h = compute_content_hash("t", "u")
        assert isinstance(h, str) and len(h) == 64


class TestClassifyBeforeTrigger:
    def test_published_day_before_returns_1(self):
        assert classify_before_trigger("2024-07-18", "2024-07-19") == 1

    def test_published_day_after_returns_0(self):
        assert classify_before_trigger("2024-07-20", "2024-07-19") == 0

    def test_published_same_day_returns_none(self):
        assert classify_before_trigger("2024-07-19", "2024-07-19") is None

    def test_published_at_none_returns_none(self):
        assert classify_before_trigger(None, "2024-07-19") is None

    def test_rfc2822_format_same_day_returns_none(self):
        assert classify_before_trigger("Fri, 19 Jul 2024 10:00:00 GMT", "2024-07-19") is None

    def test_rfc2822_format_day_before_returns_1(self):
        assert classify_before_trigger("Thu, 18 Jul 2024 23:59:00 GMT", "2024-07-19") == 1

    def test_iso_format_before_midnight_returns_1(self):
        assert classify_before_trigger("2024-07-18T23:59:59+00:00", "2024-07-19") == 1

    def test_unparseable_date_returns_none(self):
        assert classify_before_trigger("not a date", "2024-07-19") is None


from unittest.mock import AsyncMock, MagicMock, patch


class TestFetchRssArticles:
    async def test_returns_article_list_on_success(self):
        mock_feed = MagicMock()
        entry = MagicMock()
        entry.get = lambda k, d="": {"title": "CrowdStrike outage", "link": "http://y.com/1", "published": "Fri, 19 Jul 2024 10:00:00 GMT"}.get(k, d)
        entry.source.title = "Reuters"
        mock_feed.entries = [entry]

        with patch("app.intelligence.news_fetcher._fetch_bytes", new=AsyncMock(return_value=b"<rss/>")), \
             patch("app.intelligence.news_fetcher.feedparser.parse", return_value=mock_feed):
            from app.intelligence.news_fetcher import fetch_rss_articles
            articles = await fetch_rss_articles("CRWD")

        assert len(articles) == 1
        assert articles[0]["title"] == "CrowdStrike outage"
        assert articles[0]["url"] == "http://y.com/1"

    async def test_returns_empty_list_on_error(self):
        with patch("app.intelligence.news_fetcher._fetch_bytes", new=AsyncMock(side_effect=Exception("err"))):
            from app.intelligence.news_fetcher import fetch_rss_articles
            assert await fetch_rss_articles("CRWD") == []

    async def test_jp_stock_uses_jp_region_url(self):
        mock_feed = MagicMock()
        mock_feed.entries = []
        with patch("app.intelligence.news_fetcher._fetch_bytes", new=AsyncMock(return_value=b"")) as mock_fetch, \
             patch("app.intelligence.news_fetcher.feedparser.parse", return_value=mock_feed):
            from app.intelligence.news_fetcher import fetch_rss_articles
            await fetch_rss_articles("7203.T")
            called_url = mock_fetch.call_args.args[0]
        assert "region=JP" in called_url


async def _setup_news_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _make_dip(symbol: str, trigger_date: str) -> DipEvent:
    now = datetime.now(timezone.utc).isoformat()
    return DipEvent(
        symbol=symbol, detected_date=trigger_date, trigger_date=trigger_date,
        change_pct_1d=-6.0, macro_flag=0, status="detected",
        created_at=now, updated_at=now,
    )


_ARTICLE = {
    "title": "悪材料の続報",
    "url": "http://example.com/news-1",
    "source": None,
    "published_at": "Mon, 06 Jul 2026 12:00:00 +0000",
}


async def test_same_url_attaches_to_two_different_events():
    # 監査 2-2: 繰り返し急落の2件目にも原因記事候補が付くこと
    engine, Session = await _setup_news_db()
    async with Session() as s:
        e1, e2 = _make_dip("CRWD", "2026-07-01"), _make_dip("CRWD", "2026-07-06")
        s.add_all([e1, e2])
        await s.commit()
        await s.refresh(e1)
        await s.refresh(e2)

        with patch("app.intelligence.news_fetcher.fetch_rss_articles",
                   new=AsyncMock(return_value=[_ARTICLE])):
            saved1 = await fetch_and_save_news(s, e1)
            saved2 = await fetch_and_save_news(s, e2)

    assert len(saved1) == 1
    assert len(saved2) == 1  # 旧実装（URLグローバル一意）だと 0 になる
    await engine.dispose()


async def test_same_url_not_duplicated_within_one_event():
    engine, Session = await _setup_news_db()
    async with Session() as s:
        e1 = _make_dip("CRWD", "2026-07-01")
        s.add(e1)
        await s.commit()
        await s.refresh(e1)

        with patch("app.intelligence.news_fetcher.fetch_rss_articles",
                   new=AsyncMock(return_value=[_ARTICLE])):
            saved_first = await fetch_and_save_news(s, e1)
            saved_again = await fetch_and_save_news(s, e1)

    assert len(saved_first) == 1
    assert saved_again == []
    await engine.dispose()
