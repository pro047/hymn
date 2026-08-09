import datetime as dt
import secrets
import uuid

from sqlalchemy import Date, DateTime, Enum, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


# l/1 and o/0 are left out: the code is read off one screen and typed into
# another by a person, and those are the pairs that get transcribed wrong.
# 32 symbols over 8 places is ~1.1e12 codes, so guessing one is not a way in.
JOIN_CODE_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"
JOIN_CODE_LENGTH = 8


def generate_join_code() -> str:
    """A fresh church invite code. secrets, not random: this is a credential."""
    return "".join(secrets.choice(JOIN_CODE_ALPHABET) for _ in range(JOIN_CODE_LENGTH))


class Church(Base):
    __tablename__ = "churches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # Wider than the 8 the generator emits, so the format can grow without a
    # column change. Defaulted here rather than at every call site: a church
    # without a code cannot be joined, so there is no valid row to leave one off.
    join_code: Mapped[str] = mapped_column(
        String(16), unique=True, nullable=False, default=generate_join_code
    )
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Seoul")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="church", cascade="all, delete-orphan")
    scores: Mapped[list["Score"]] = relationship(back_populates="church", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("church_id", "email", name="uq_user_church_email"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    church_id: Mapped[str] = mapped_column(ForeignKey("churches.id", ondelete="CASCADE"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(Enum("leader", "member", name="user_role"), nullable=False, default="member")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, nullable=False)

    church: Mapped["Church"] = relationship(back_populates="users")
    uploaded_scores: Mapped[list["Score"]] = relationship(back_populates="uploader")
    saved_scores: Mapped[list["SavedScore"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    # id is the JWT jti claim of the issued refresh token
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, nullable=False)


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    church_id: Mapped[str] = mapped_column(ForeignKey("churches.id", ondelete="CASCADE"), nullable=False)
    uploader_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    week_of: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    file_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("draft", "published", "archived", name="score_status"), nullable=False, default="draft"
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow, nullable=False
    )

    church: Mapped["Church"] = relationship(back_populates="scores")
    uploader: Mapped["User"] = relationship(back_populates="uploaded_scores")
    assets: Mapped[list["ScoreAsset"]] = relationship(back_populates="score", cascade="all, delete-orphan")
    set_items: Mapped[list["SetItem"]] = relationship(back_populates="score", cascade="all, delete-orphan")
    saved_by: Mapped[list["SavedScore"]] = relationship(
        back_populates="score", cascade="all, delete-orphan"
    )

class ScoreAsset(Base):
    __tablename__ = "score_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    score_id: Mapped[str] = mapped_column(ForeignKey("scores.id", ondelete="CASCADE"), nullable=False)
    variant: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g., pdf, chords, vocal, piano
    file_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, nullable=False)

    score: Mapped["Score"] = relationship(back_populates="assets")

class SavedScore(Base):
    __tablename__ = "saved_scores"
    __table_args__ = (
        UniqueConstraint("user_id", "score_id", name="uq_saved_scores_user_score"),
        )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    score_id: Mapped[str] = mapped_column(ForeignKey("scores.id", ondelete="CASCADE"), nullable=False)
    use_count: Mapped[int] = mapped_column(nullable=False, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, nullable=False)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="saved_scores")
    score: Mapped["Score"] = relationship(back_populates="saved_by")

class Week(Base):
    __tablename__ = "weeks"

    # Composite PK includes partition key (date) for RANGE partitioning
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, nullable=False)

    set_items: Mapped[list["SetItem"]] = relationship(back_populates="week", cascade="all, delete-orphan")


class SetItem(Base):
    __tablename__ = "set_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["week_id", "week_date"],
            ["weeks.id", "weeks.date"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    week_id: Mapped[str] = mapped_column(String(36), nullable=False)
    week_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    order_no: Mapped[int] = mapped_column(nullable=False)
    score_id: Mapped[str] = mapped_column(ForeignKey("scores.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    memo: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, nullable=False)

    week: Mapped["Week"] = relationship(back_populates="set_items")
    score: Mapped["Score"] = relationship(back_populates="set_items")
