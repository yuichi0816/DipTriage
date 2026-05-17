# Phase 2 — Interview (LLM Integration) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Yahoo Finance RSS からニュースを取得し、Qwen3 on Ollama で急落イベントを事故型/事件型/不明に初期分類する問診機能を日次パイプラインに追加する。

**Architecture:** ニュース取得（Stage 3a）と LLM 問診（Stage 3b）をステージ分割する。`app/intelligence/` に `ollama_client.py`・`news_fetcher.py`・`interview.py` を追加し、`runner.py` で順に呼び出す。Ollama 障害時は例外をキャッチしてスキップし `status="analyzed"` のまま維持する。`macro_flag=0` のイベントのみ対象。

**Tech Stack:** Python 3.12, ollama SDK (AsyncClient), feedparser, SQLAlchemy 2.x async, pytest-asyncio (STRICT mode), Qwen3:30b on Ollama

---

## File Structure

| ファイル | 操作 | 責務 |
|---|---|---|
| `app/intelligence/ollama_client.py` | 新規 | `generate(prompt, model) -> (text, elapsed_sec)` |
| `app/intelligence/news_fetcher.py` | 新規 | RSS 取得・dedup・before_trigger 分類・DB 保存 |
| `app/intelligence/interview.py` | 新規 | `build_prompt()`・`parse_llm_response()`・`run_interview()` |
| `app/pipeline/runner.py` | 修正 | Stage 3a・3b を追加、stats に news_fetched・dips_interviewed を追加 |
| `app/routers/dashboard.py` | 修正 | Briefing クエリを追加して interviews 辞書をテンプレートに渡す |
| `app/templates/dashboard.html` | 修正 | 事故型/事件型バッジを追加 |
| `tests/test_intelligence/test_ollama_client.py` | 新規 | generate() のユニットテスト |
| `tests/test_intelligence/test_news_fetcher.py` | 新規 | 純粋関数 + fetch_rss_articles のユニットテスト |
| `tests/test_intelligence/test_interview.py` | 新規 | 純粋関数 + run_interview の統合テスト |

---

### Task 1: `ollama_client.py` — Ollama async ラッパー

**Files:**
- Create: `app/intelligence/ollama_client.py`
- Create: `tests/test_intelligence/test_ollama_client.py`

- [ ] **Step 1: テストを書く**

```python
# tests/test_intelligence/test_ollama_client.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_generate_returns_text_and_elapsed():
    mock_response = MagicMock()
    mock_response.message.content = "test output"

    with patch("app.intelligence.ollama_client.AsyncClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.chat = AsyncMock(return_value=mock_response)

        from app.intelligence.ollama_client import generate
        text, elapsed = await generate("hello", model="test-model")

    assert text == "test output"
    assert elapsed >= 0.0


@pytest.mark.asyncio
async def test_generate_passes_prompt_to_chat():
    mock_response = MagicMock()
    mock_response.message.content = "ok"

    with patch("app.intelligence.ollama_client.AsyncClient") as MockClient:
        mock_instance = MockClient.return_value
        mock_instance.chat = AsyncMock(return_value=mock_response)

        from app.intelligence.ollama_client import generate
        await generate("my special prompt", model="qwen3:30b")

        chat_call = mock_instance.chat.call_args
        messages = chat_call.kwargs.get("messages") or chat_call.args[1]
        assert any("my special prompt" in str(m) for m in messages)
```

- [ ] **Step 2: テストの失敗を確認する**

```
uv run pytest tests/test_intelligence/test_ollama_client.py -v
```

Expected: `ImportError` または `ModuleNotFoundError`（ollama_client.py が存在しないため）

- [ ] **Step 3: `ollama_client.py` を実装する**

```python
# app/intelligence/ollama_client.py
"""Ollama AsyncClient の薄いラッパー。"""
from __future__ import annotations

import time

from ollama import AsyncClient

from app.config import OLLAMA_HOST, OLLAMA_MODEL_INTERVIEW


async def generate(prompt: str, model: str = OLLAMA_MODEL_INTERVIEW) -> tuple[str, float]:
    """Ollama にプロンプトを送り (response_text, elapsed_seconds) を返す。"""
    client = AsyncClient(host=OLLAMA_HOST)
    t0 = time.monotonic()
    response = await client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    elapsed = time.monotonic() - t0
    return response.message.content, elapsed
```

- [ ] **Step 4: テストの成功を確認する**

```
uv run pytest tests/test_intelligence/test_ollama_client.py -v
```

Expected: 2 passed

- [ ] **Step 5: コミット**

```bash
git add app/intelligence/ollama_client.py tests/test_intelligence/test_ollama_client.py
git commit -m "feat: add ollama_client async wrapper"
```

---

### Task 2: `news_fetcher.py` — 純粋関数（ハッシュ・before_trigger 分類）

**Files:**
- Create: `app/intelligence/news_fetcher.py`（純粋関数部分）
- Create: `tests/test_intelligence/test_news_fetcher.py`

- [ ] **Step 1: テストを書く**

```python
# tests/test_intelligence/test_news_fetcher.py
from app.intelligence.news_fetcher import classify_before_trigger, compute_content_hash


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
        # feedparser が返す RFC 2822 形式（同日）
        assert classify_before_trigger("Fri, 19 Jul 2024 10:00:00 GMT", "2024-07-19") is None

    def test_rfc2822_format_day_before_returns_1(self):
        assert classify_before_trigger("Thu, 18 Jul 2024 23:59:00 GMT", "2024-07-19") == 1

    def test_iso_format_before_midnight_returns_1(self):
        assert classify_before_trigger("2024-07-18T23:59:59+00:00", "2024-07-19") == 1

    def test_unparseable_date_returns_none(self):
        assert classify_before_trigger("not a date", "2024-07-19") is None
```

- [ ] **Step 2: テストの失敗を確認する**

```
uv run pytest tests/test_intelligence/test_news_fetcher.py -v
```

Expected: `ImportError`

- [ ] **Step 3: 純粋関数を実装する**

```python
# app/intelligence/news_fetcher.py
"""Stage 3a: Yahoo Finance RSS からニュースを取得し DB に保存する。"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

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
            return None  # 同日は不明
    except Exception:
        return None
```

- [ ] **Step 4: テストの成功を確認する**

```
uv run pytest tests/test_intelligence/test_news_fetcher.py -v
```

Expected: 8 passed

- [ ] **Step 5: コミット**

```bash
git add app/intelligence/news_fetcher.py tests/test_intelligence/test_news_fetcher.py
git commit -m "feat: add news_fetcher pure helpers (hash, before_trigger)"
```

---

### Task 3: `news_fetcher.py` — `fetch_rss_articles()` と `fetch_and_save_news()`

**Files:**
- Modify: `app/intelligence/news_fetcher.py`（I/O 関数を追記）
- Modify: `tests/test_intelligence/test_news_fetcher.py`（テストを追記）

- [ ] **Step 1: テストを追加する**

```python
# tests/test_intelligence/test_news_fetcher.py の末尾に追記

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
```

- [ ] **Step 2: テストの失敗を確認する**

```
uv run pytest tests/test_intelligence/test_news_fetcher.py::TestFetchRssArticles -v
```

Expected: `ImportError`（fetch_rss_articles が未定義）

- [ ] **Step 3: `fetch_rss_articles()` と `fetch_and_save_news()` を実装する**

`app/intelligence/news_fetcher.py` の末尾に以下を追記する：

```python
import feedparser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DipEvent, NewsArticle

_RSS_US = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
_RSS_JP = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=JP&lang=ja-JP"


def fetch_rss_articles(symbol: str) -> list[dict]:
    """Yahoo Finance RSS から記事リストを取得する。失敗時は空リストを返す。"""
    try:
        url = _RSS_JP.format(symbol=symbol) if symbol.endswith(".T") else _RSS_US.format(symbol=symbol)
        feed = feedparser.parse(url)
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
    raw_articles = fetch_rss_articles(event.symbol)
    if not raw_articles:
        return []

    now = datetime.now(timezone.utc).isoformat()
    saved: list[NewsArticle] = []

    for raw in raw_articles:
        url = raw["url"]
        if not url:
            continue

        existing = await session.execute(
            select(NewsArticle).where(NewsArticle.url == url).limit(1)
        )
        if existing.scalar_one_or_none():
            continue

        article = NewsArticle(
            dip_event_id=event.id,
            symbol=event.symbol,
            title=raw["title"],
            url=url,
            source=raw["source"],
            source_type="news",
            priority=5,
            published_at=raw["published_at"],
            fetched_at=now,
            content_hash=compute_content_hash(raw["title"], url),
            is_duplicate=0,
            before_trigger=classify_before_trigger(raw["published_at"], event.trigger_date),
        )
        session.add(article)
        saved.append(article)

    await session.commit()
    logger.info("Saved %d news articles for %s", len(saved), event.symbol)
    return saved
```

- [ ] **Step 4: テストの成功を確認する**

```
uv run pytest tests/test_intelligence/test_news_fetcher.py -v
```

Expected: 全テスト passed

- [ ] **Step 5: コミット**

```bash
git add app/intelligence/news_fetcher.py tests/test_intelligence/test_news_fetcher.py
git commit -m "feat: add news_fetcher fetch_rss_articles and fetch_and_save_news"
```

---

### Task 4: `interview.py` — `build_prompt()` と `parse_llm_response()`

**Files:**
- Create: `app/intelligence/interview.py`（純粋関数部分）
- Create: `tests/test_intelligence/test_interview.py`

- [ ] **Step 1: テストを書く**

```python
# tests/test_intelligence/test_interview.py
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.intelligence.interview import build_prompt, parse_llm_response


def _event(symbol="CRWD", trigger_date="2024-07-19", change_1d=-11.2, change_5d=-8.7):
    e = MagicMock()
    e.symbol = symbol
    e.trigger_date = trigger_date
    e.change_pct_1d = change_1d
    e.change_pct_5d = change_5d
    return e


def _analysis(volume_ratio=4.2, sector_relative=-10.8, is_idiosyncratic=1):
    a = MagicMock()
    a.volume_ratio_20d = volume_ratio
    a.sector_relative = sector_relative
    a.is_idiosyncratic = is_idiosyncratic
    return a


def _article(title="CrowdStrike outage", before_trigger=1):
    art = MagicMock()
    art.title = title
    art.before_trigger = before_trigger
    art.published_at = "2024-07-19T10:00:00+00:00"
    return art


class TestBuildPrompt:
    def test_contains_no_think_directive(self):
        assert "/no_think" in build_prompt(_event(), None, [])

    def test_contains_symbol(self):
        assert "CRWD" in build_prompt(_event(symbol="CRWD"), None, [])

    def test_contains_change_pct_1d(self):
        assert "-11.2" in build_prompt(_event(change_1d=-11.2), None, [])

    def test_contains_article_title(self):
        arts = [_article("Falcon sensor update causes BSOD", before_trigger=1)]
        assert "Falcon sensor update causes BSOD" in build_prompt(_event(), None, arts)

    def test_before_trigger_article_has_mae_label(self):
        arts = [_article("pre-event news", before_trigger=1)]
        prompt = build_prompt(_event(), None, arts)
        assert "[前]" in prompt

    def test_after_trigger_article_has_ato_label(self):
        arts = [_article("post-event news", before_trigger=0)]
        prompt = build_prompt(_event(), None, arts)
        assert "[後]" in prompt

    def test_contains_json_instruction(self):
        prompt = build_prompt(_event(), None, [])
        assert "initial_class" in prompt
        assert "situation_summary" in prompt

    def test_volume_ratio_included_when_analysis_provided(self):
        prompt = build_prompt(_event(), _analysis(volume_ratio=4.2), [])
        assert "4.2" in prompt


class TestParseLlmResponse:
    def test_parses_valid_json(self):
        text = '{"situation_summary": "障害発生。", "initial_class": "accident"}'
        result = parse_llm_response(text)
        assert result["situation_summary"] == "障害発生。"
        assert result["initial_class"] == "accident"

    def test_parses_json_embedded_in_surrounding_text(self):
        text = 'preamble\n{"situation_summary": "ok", "initial_class": "incident"}\nsuffix'
        assert parse_llm_response(text)["initial_class"] == "incident"

    def test_returns_fallback_for_invalid_json(self):
        result = parse_llm_response("not json at all")
        assert result["initial_class"] == "unknown"
        assert "解析失敗" in result["situation_summary"]

    def test_normalizes_unknown_class_value(self):
        text = '{"situation_summary": "unclear", "initial_class": "maybe"}'
        assert parse_llm_response(text)["initial_class"] == "unknown"

    def test_handles_empty_string(self):
        result = parse_llm_response("")
        assert result["initial_class"] == "unknown"

    def test_accepts_incident_class(self):
        text = '{"situation_summary": "粉飾決算。", "initial_class": "incident"}'
        assert parse_llm_response(text)["initial_class"] == "incident"
```

- [ ] **Step 2: テストの失敗を確認する**

```
uv run pytest tests/test_intelligence/test_interview.py -v
```

Expected: `ImportError`

- [ ] **Step 3: 純粋関数を実装する**

```python
# app/intelligence/interview.py
"""Stage 3b: LLM 問診（プロンプト生成・Qwen3 呼び出し・結果パース・DB 保存）"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import OLLAMA_MODEL_INTERVIEW
from app.intelligence.ollama_client import generate
from app.models import Briefing, DipEvent, NewsArticle, NumericalAnalysis

logger = logging.getLogger(__name__)

_VALID_CLASSES = {"accident", "incident", "unknown"}
_CLASS_JP = {"accident": "事故型", "incident": "事件型", "unknown": "不明"}


def build_prompt(
    event: DipEvent,
    analysis: NumericalAnalysis | None,
    articles: list[NewsArticle],
    name: str | None = None,
    sector: str | None = None,
) -> str:
    """問診用プロンプトを組み立てる。"""
    market = "JP" if str(event.symbol).endswith(".T") else "US"
    name_part = f"（{name}）" if name else ""
    sector_part = f" / {sector}" if sector else ""

    change_line = f"【前日比】{event.change_pct_1d:.1f}%"
    if event.change_pct_5d is not None:
        change_line += f"  【週間】{event.change_pct_5d:.1f}%"

    volume_line = ""
    sector_line = ""
    if analysis:
        if analysis.volume_ratio_20d:
            volume_line = f"【出来高】{analysis.volume_ratio_20d:.1f}倍（20日平均比）"
        if analysis.sector_relative is not None:
            label = "銘柄固有" if analysis.is_idiosyncratic else "セクター連動"
            sector_line = f"【セクター超過下落】{analysis.sector_relative:.1f}%（{label}）"

    news_lines = []
    for i, art in enumerate(articles[:10], 1):
        if art.before_trigger == 1:
            lbl = "[前]"
        elif art.before_trigger == 0:
            lbl = "[後]"
        else:
            lbl = "[?]"
        news_lines.append(f"{i}. {lbl} {art.title}")

    news_section = "\n".join(news_lines) if news_lines else "（ニュースなし）"

    parts = [
        "/no_think",
        "以下の株価急落イベントについて分析してください。",
        "",
        f"【銘柄】{event.symbol}{name_part} / {market}{sector_part}",
        change_line,
    ]
    if volume_line:
        parts.append(volume_line)
    if sector_line:
        parts.append(sector_line)
    parts += [
        "",
        "【関連ニュース（急落前後）】",
        news_section,
        "",
        "以下のJSON形式のみで回答してください（他のテキスト不要）:",
        '{',
        '  "situation_summary": "1〜2文で何が起きたかを説明",',
        '  "initial_class": "accident または incident または unknown"',
        '}',
    ]
    return "\n".join(parts)


def parse_llm_response(text: str) -> dict[str, str]:
    """LLM の応答から JSON を抽出してパースする。失敗時はフォールバック値を返す。"""
    _fallback = {"situation_summary": "（解析失敗）", "initial_class": "unknown"}
    match = re.search(r'\{[^{}]+\}', text, re.DOTALL)
    if not match:
        return _fallback
    try:
        data = json.loads(match.group())
        cls = data.get("initial_class", "unknown")
        if cls not in _VALID_CLASSES:
            cls = "unknown"
        return {
            "situation_summary": data.get("situation_summary", "（解析失敗）"),
            "initial_class": cls,
        }
    except json.JSONDecodeError:
        return _fallback
```

- [ ] **Step 4: テストの成功を確認する**

```
uv run pytest tests/test_intelligence/test_interview.py -v
```

Expected: 14 passed

- [ ] **Step 5: コミット**

```bash
git add app/intelligence/interview.py tests/test_intelligence/test_interview.py
git commit -m "feat: add interview build_prompt and parse_llm_response"
```

---

### Task 5: `interview.py` — `run_interview()`

**Files:**
- Modify: `app/intelligence/interview.py`（`run_interview` を追記）
- Modify: `tests/test_intelligence/test_interview.py`（統合テストを追記）

- [ ] **Step 1: テストを追加する**

```python
# tests/test_intelligence/test_interview.py の末尾に追記

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.models import Base, Briefing, DipEvent, NewsArticle
from app.intelligence.interview import run_interview


async def _setup_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_run_interview_saves_briefing_on_success():
    engine, Session = await _setup_db()
    now = datetime.now(timezone.utc).isoformat()

    async with Session() as session:
        event = DipEvent(
            symbol="CRWD", detected_date="2024-07-19", trigger_date="2024-07-19",
            change_pct_1d=-11.2, status="analyzed", macro_flag=0,
            created_at=now, updated_at=now,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)

        article = NewsArticle(
            dip_event_id=event.id, symbol="CRWD",
            title="CrowdStrike update causes outage", url="http://example.com/a1",
            priority=4, fetched_at=now, is_duplicate=0, before_trigger=1,
        )
        session.add(article)
        await session.commit()

        llm_json = '{"situation_summary": "ソフトウェア障害。", "initial_class": "accident"}'
        with patch("app.intelligence.interview.generate", new=AsyncMock(return_value=(llm_json, 1.5))):
            briefing = await run_interview(session, event, None, [article])

    assert briefing is not None
    assert briefing.situation_summary == "ソフトウェア障害。"
    assert briefing.initial_class == "accident"
    assert briefing.initial_class_jp == "事故型"
    assert briefing.briefing_type == "interview"
    assert briefing.generation_sec == pytest.approx(1.5)

    async with Session() as session2:
        from sqlalchemy import select as sa_select
        result = await session2.execute(sa_select(DipEvent).where(DipEvent.id == event.id))
        refreshed = result.scalar_one()
        assert refreshed.status == "interviewed"

    await engine.dispose()


@pytest.mark.asyncio
async def test_run_interview_returns_none_on_llm_error():
    engine, Session = await _setup_db()
    now = datetime.now(timezone.utc).isoformat()

    async with Session() as session:
        event = DipEvent(
            symbol="CRWD", detected_date="2024-07-19", trigger_date="2024-07-19",
            change_pct_1d=-11.2, status="analyzed", macro_flag=0,
            created_at=now, updated_at=now,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)

        article = NewsArticle(
            dip_event_id=event.id, symbol="CRWD",
            title="test", url="http://example.com/a2",
            priority=5, fetched_at=now, is_duplicate=0,
        )
        session.add(article)
        await session.commit()

        with patch("app.intelligence.interview.generate", new=AsyncMock(side_effect=Exception("Ollama down"))):
            briefing = await run_interview(session, event, None, [article])

    assert briefing is None

    async with Session() as session2:
        from sqlalchemy import select as sa_select
        result = await session2.execute(sa_select(DipEvent).where(DipEvent.id == event.id))
        refreshed = result.scalar_one()
        assert refreshed.status == "analyzed"  # ステータスは変わらない

    await engine.dispose()
```

- [ ] **Step 2: テストの失敗を確認する**

```
uv run pytest tests/test_intelligence/test_interview.py::test_run_interview_saves_briefing_on_success tests/test_intelligence/test_interview.py::test_run_interview_returns_none_on_llm_error -v
```

Expected: `ImportError`（run_interview が未定義）

- [ ] **Step 3: `run_interview()` を実装する**

`app/intelligence/interview.py` の末尾に追記する：

```python
async def run_interview(
    session: AsyncSession,
    event: DipEvent,
    analysis: NumericalAnalysis | None,
    articles: list[NewsArticle],
    meta=None,
) -> Briefing | None:
    """問診を実行し Briefing を DB に保存する。失敗時は None を返す（status は変えない）。"""
    try:
        prompt = build_prompt(
            event, analysis, articles,
            name=meta.name if meta else None,
            sector=meta.sector if meta else None,
        )
        text, elapsed = await generate(prompt, model=OLLAMA_MODEL_INTERVIEW)
        parsed = parse_llm_response(text)

        now = datetime.now(timezone.utc).isoformat()
        briefing = Briefing(
            dip_event_id=event.id,
            briefing_type="interview",
            situation_summary=parsed["situation_summary"],
            initial_class=parsed["initial_class"],
            initial_class_jp=_CLASS_JP.get(parsed["initial_class"], "不明"),
            prompt_used=prompt,
            model_name=OLLAMA_MODEL_INTERVIEW,
            generation_sec=elapsed,
            created_at=now,
            is_latest=1,
        )
        session.add(briefing)

        event.status = "interviewed"
        event.updated_at = now

        await session.commit()
        await session.refresh(briefing)
        logger.info("Interviewed %s: class=%s (%.1fs)", event.symbol, parsed["initial_class"], elapsed)
        return briefing
    except Exception as e:
        logger.error("Interview failed for %s: %s", event.symbol, e)
        await session.rollback()
        return None
```

- [ ] **Step 4: テストの成功を確認する**

```
uv run pytest tests/test_intelligence/ -v
```

Expected: 全テスト passed

- [ ] **Step 5: コミット**

```bash
git add app/intelligence/interview.py tests/test_intelligence/test_interview.py
git commit -m "feat: add interview run_interview with error handling"
```

---

### Task 6: `runner.py` — Stage 3a・3b を追加

**Files:**
- Modify: `app/pipeline/runner.py`

- [ ] **Step 1: import を追加する**

`app/pipeline/runner.py` の import セクションに以下を追記する：

```python
from sqlalchemy import nullslast, select, update  # nullslast を追加（既存の select, update はそのまま）

from app.intelligence.interview import run_interview
from app.intelligence.news_fetcher import fetch_and_save_news
from app.models import DipEvent, IndexPrice, NewsArticle, NumericalAnalysis, StockMeta, StockPrice
```

注意：既存の `from sqlalchemy import select, update` を `from sqlalchemy import nullslast, select, update` に置き換える。`NewsArticle` と `NumericalAnalysis` を models の import に追加する。

- [ ] **Step 2: Stage 3a・3b を runner.py に追加する**

`run_daily_pipeline` の `# ── ステータス更新 ──` ブロックの直前に以下を挿入する：

```python
        # ── 第3段階a: ニュース取得 ──
        non_macro_events = [e for e in dip_events if not e.macro_flag]
        logger.info("Stage 3a: Fetching news for %d non-macro dips", len(non_macro_events))
        for event in non_macro_events:
            try:
                articles = await fetch_and_save_news(session, event)
                stats["news_fetched"] = stats.get("news_fetched", 0) + len(articles)
            except Exception as e:
                logger.warning("News fetch failed for %s: %s", event.symbol, e)

        # ── 第3段階b: LLM 問診 ──
        logger.info("Stage 3b: Running interview for %d dips", len(non_macro_events))
        stats["dips_interviewed"] = 0
        for event in non_macro_events:
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
```

- [ ] **Step 3: ステータス更新ブロックを修正する**

既存のステータス更新ブロック（`# ── ステータス更新 ──`）を以下に置き換える（`detected → analyzed` の更新を `macro_flag=0` の `analyzed → interviewed` に変更）：

```python
        # ── ステータス更新（analyzed）: macro_flag を問わず全 dip を analyzed に ──
        await session.execute(
            update(DipEvent)
            .where(DipEvent.detected_date == target_date, DipEvent.status == "detected")
            .values(status="analyzed", updated_at=datetime.now(timezone.utc).isoformat())
        )
        await session.commit()
```

注意：`run_interview` が成功した場合は内部で status を "interviewed" に更新するため、runner.py 側で interviewed への一括更新は不要。

- [ ] **Step 4: 手動で動作確認する（Ollama が起動していない場合はスキップ可）**

```bash
# Ollama が起動している場合
uv run python scripts/backfill.py 2024-07-19
# ログに "Stage 3a: Fetching news" と "Stage 3b: Running interview" が出ることを確認
```

Ollama が未起動の場合は "Interview failed for CRWD: ..." のエラーログが出るが正常（スキップして続行）。

- [ ] **Step 5: コミット**

```bash
git add app/pipeline/runner.py
git commit -m "feat: add Stage 3a news fetch and Stage 3b interview to runner"
```

---

### Task 7: `dashboard.py` + `dashboard.html` — 問診バッジ

**Files:**
- Modify: `app/routers/dashboard.py`
- Modify: `app/templates/dashboard.html`

- [ ] **Step 1: `dashboard.py` に Briefing クエリを追加する**

`app/routers/dashboard.py` を以下のように修正する：

import の `from app.models import DipEvent, NumericalAnalysis, StockMeta` を以下に変更：

```python
from app.models import Briefing, DipEvent, NumericalAnalysis, StockMeta
```

`dashboard` 関数の末尾、`return templates.TemplateResponse(...)` の直前に以下を追加：

```python
    event_ids = [e.id for e in events]
    interviews: dict[int, Briefing] = {}
    if event_ids:
        br_result = await session.execute(
            select(Briefing)
            .where(
                Briefing.dip_event_id.in_(event_ids),
                Briefing.briefing_type == "interview",
                Briefing.is_latest == 1,
            )
        )
        interviews = {b.dip_event_id: b for b in br_result.scalars().all()}
```

`return templates.TemplateResponse(...)` のコンテキスト辞書に `"interviews": interviews` を追加：

```python
    return templates.TemplateResponse(request, "dashboard.html", {
        "events": events,
        "analyses": analyses,
        "meta_map": meta_map,
        "interviews": interviews,
    })
```

- [ ] **Step 2: `dashboard.html` のバッジ部分を更新する**

`app/templates/dashboard.html` 内の以下の部分を：

```html
        {# Phase 2 以降で事故/事件ラベルをここに追加 #}
        <span class="bg-gray-800 text-gray-500 px-2 py-0.5 rounded">{{ event.status }}</span>
```

以下に置き換える：

```html
        {% set interview = interviews.get(event.id) %}
        {% if interview %}
          {% if interview.initial_class == 'accident' %}
            <span class="bg-green-900 text-green-300 px-2 py-0.5 rounded">事故型</span>
          {% elif interview.initial_class == 'incident' %}
            <span class="bg-red-900 text-red-300 px-2 py-0.5 rounded">事件型</span>
          {% else %}
            <span class="bg-gray-700 text-gray-400 px-2 py-0.5 rounded">不明</span>
          {% endif %}
        {% else %}
          <span class="bg-gray-800 text-gray-500 px-2 py-0.5 rounded">{{ event.status }}</span>
        {% endif %}
```

- [ ] **Step 3: テスト全体を実行して確認する**

```
uv run pytest tests/ -v
```

Expected: 全テスト passed（27 + 新規テスト）

- [ ] **Step 4: サーバーを起動して UI を確認する（オプション）**

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

http://localhost:8000 で急落リストを開き、問診済みイベントに「事故型」「事件型」「不明」バッジが表示されることを確認。

- [ ] **Step 5: コミット**

```bash
git add app/routers/dashboard.py app/templates/dashboard.html
git commit -m "feat: add interview badge to dashboard"
```
