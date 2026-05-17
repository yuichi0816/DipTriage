from sqlalchemy import String, Integer, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.models.stock import Base


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dip_event_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("dip_events.id"))
    symbol: Mapped[str | None] = mapped_column(String)

    title: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str | None] = mapped_column(String)
    source_type: Mapped[str | None] = mapped_column(String)  # tdnet | ir | wire | news
    priority: Mapped[int] = mapped_column(Integer, default=5)  # 1（最優先）〜5
    published_at: Mapped[str | None] = mapped_column(String)
    fetched_at: Mapped[str] = mapped_column(String, nullable=False)

    content_text: Mapped[str | None] = mapped_column(String)
    content_hash: Mapped[str | None] = mapped_column(String)
    is_duplicate: Mapped[int] = mapped_column(Integer, default=0)

    # 1=急落前の原因記事、0=後追い記事、None=不明
    before_trigger: Mapped[int | None] = mapped_column(Integer)

    extra_json: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        UniqueConstraint("url", name="uq_news_articles_url"),
        Index("idx_news_dip_event_id", "dip_event_id"),
        Index("idx_news_published_at", "published_at"),
    )
