from sqlalchemy import String, Integer, Float, ForeignKey, Index
from sqlalchemy import text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.stock import Base


class Briefing(Base):
    __tablename__ = "briefings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dip_event_id: Mapped[int] = mapped_column(Integer, ForeignKey("dip_events.id"), nullable=False)
    briefing_type: Mapped[str] = mapped_column(String, nullable=False)  # "interview" | "diagnosis"

    # 問診結果（interview）
    situation_summary: Mapped[str | None] = mapped_column(String)
    initial_class: Mapped[str | None] = mapped_column(String)     # accident | incident | structural | macro | unknown
    initial_class_jp: Mapped[str | None] = mapped_column(String)  # 事故型 | 事件型 | 構造型 | マクロ型 | 不明

    # 診断結果（diagnosis）
    accident_subtype: Mapped[str | None] = mapped_column(String)
    moat_json: Mapped[str | None] = mapped_column(String)
    counterarguments: Mapped[str | None] = mapped_column(String)
    confidence: Mapped[str | None] = mapped_column(String)  # high | medium | low

    # 共通
    full_text: Mapped[str | None] = mapped_column(String)
    prompt_used: Mapped[str | None] = mapped_column(String)
    model_name: Mapped[str | None] = mapped_column(String)
    generation_sec: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[str] = mapped_column(String, nullable=False)
    is_latest: Mapped[int] = mapped_column(Integer, default=1)
    # 1=LLM応答のパース成功, 0=フォールバック値で保存（監査 1-4）
    parse_ok: Mapped[int] = mapped_column(Integer, default=1)
    # パース失敗の事後調査用に LLM 生応答を保存（監査 6-4）
    raw_response: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        Index("idx_briefings_dip_event_id", "dip_event_id"),
        Index(
            "uq_briefings_latest",
            "dip_event_id",
            "briefing_type",
            unique=True,
            sqlite_where=text("is_latest = 1"),
        ),
    )
