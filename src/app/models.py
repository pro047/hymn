import datetime as dt
import uuid

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class Church(Base):
    __tablename__ = "churches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Seoul")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="church", cascade="all, delete-orphan")
    scores: Mapped[list["Score"]] = relationship(back_populates="church", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("church_id", "email", name="uq_user_church_email"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    church_id: Mapped[str] = mapped_column(ForeignKey("churches.id", ondelete="CASCADE"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(Enum("admin", "editor", "viewer", name="user_role"), nullable=False, default="viewer")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, nullable=False)

    church: Mapped["Church"] = relationship(back_populates="users")
    uploaded_scores: Mapped[list["Score"]] = relationship(back_populates="uploader")


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    church_id: Mapped[str] = mapped_column(ForeignKey("churches.id", ondelete="CASCADE"), nullable=False)
    uploader_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    week_of: Mapped[dt.date] = mapped_column(Date, nullable=False)
    file_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(Enum("draft", "published", "archived", name="score_status"), nullable=False, default="draft")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow, nullable=False)

    church: Mapped["Church"] = relationship(back_populates="scores")
    uploader: Mapped["User"] = relationship(back_populates="uploaded_scores")
    assets: Mapped[list["ScoreAsset"]] = relationship(back_populates="score", cascade="all, delete-orphan")


class ScoreAsset(Base):
    __tablename__ = "score_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    score_id: Mapped[str] = mapped_column(ForeignKey("scores.id", ondelete="CASCADE"), nullable=False)
    variant: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g., pdf, chords, vocal, piano
    file_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, nullable=False)

    score: Mapped["Score"] = relationship(back_populates="assets")
