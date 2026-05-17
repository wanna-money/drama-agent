import enum
from datetime import datetime
from sqlalchemy import String, Text, DateTime, JSON, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ProjectStatus(str, enum.Enum):
    CREATED = "created"
    ANALYZING = "analyzing"
    SCREENPLAY = "screenplay"
    SCREENPLAY_REVIEW = "screenplay_review"
    STORYBOARD = "storyboard"
    PROMPTS = "prompts"
    PROMPTS_REVIEW = "prompts_review"
    GENERATING = "generating"
    ASSEMBLING = "assembling"
    COMPLETED = "completed"
    FAILED = "failed"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    raw_input: Mapped[str] = mapped_column(Text)
    genre: Mapped[str] = mapped_column(String(100), default="drama")
    status: Mapped[str] = mapped_column(String(50), default=ProjectStatus.CREATED)
    llm_model: Mapped[str] = mapped_column(String(100), default="deepseek-v4-pro")
    video_provider: Mapped[str] = mapped_column(String(50), default="seedance")
    video_model: Mapped[str] = mapped_column(String(100), default="")
    state_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
