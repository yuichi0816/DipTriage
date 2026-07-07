from sqlalchemy import String, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.models.stock import Base


class PipelineRun(Base):
    """パイプライン実行履歴（監査 3-1, 6-1）。"""
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trigger: Mapped[str] = mapped_column(String, nullable=False)   # manual | schedule | schedule-retry
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")  # running | done | error
    target_date: Mapped[str | None] = mapped_column(String)
    stats_json: Mapped[str | None] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(String)
    started_at: Mapped[str] = mapped_column(String, nullable=False)
    finished_at: Mapped[str | None] = mapped_column(String)
