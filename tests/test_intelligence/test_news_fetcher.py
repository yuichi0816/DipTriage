from app.intelligence.news_fetcher import (
    classify_before_trigger,
    compute_content_hash,
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


from unittest.mock import MagicMock, patch


class TestFetchRssArticles:
    def test_returns_article_list_on_success(self):
        mock_feed = MagicMock()
        entry = MagicMock()
        entry.get = lambda k, d="": {"title": "CrowdStrike outage", "link": "http://y.com/1", "published": "Fri, 19 Jul 2024 10:00:00 GMT"}.get(k, d)
        entry.source.title = "Reuters"
        mock_feed.entries = [entry]

        with patch("app.intelligence.news_fetcher.feedparser.parse", return_value=mock_feed):
            from app.intelligence.news_fetcher import fetch_rss_articles
            articles = fetch_rss_articles("CRWD")

        assert len(articles) == 1
        assert articles[0]["title"] == "CrowdStrike outage"
        assert articles[0]["url"] == "http://y.com/1"

    def test_returns_empty_list_on_error(self):
        with patch("app.intelligence.news_fetcher.feedparser.parse", side_effect=Exception("err")):
            from app.intelligence.news_fetcher import fetch_rss_articles
            assert fetch_rss_articles("CRWD") == []

    def test_jp_stock_uses_jp_region_url(self):
        mock_feed = MagicMock()
        mock_feed.entries = []
        with patch("app.intelligence.news_fetcher.feedparser.parse", return_value=mock_feed) as mock_parse:
            from app.intelligence.news_fetcher import fetch_rss_articles
            fetch_rss_articles("7203.T")
            called_url = mock_parse.call_args[0][0]
        assert "region=JP" in called_url
