import datetime as dt
import secrets
import uuid

from sqlalchemy import Date, DateTime, Enum, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


def naive_utc_now() -> dt.datetime:
    """UTC now, tz-naive — the shape every DateTime column below stores.

    Lives here rather than in a service because more than one of them compares
    against these columns, and a second copy of the expression is how the
    writer and the reader of a timestamp drift apart: make the columns
    timezone-aware and a stale copy keeps producing naive values that no longer
    compare.
    """
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


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
    songs: Mapped[list["Song"]] = relationship(back_populates="church", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("church_id", "email", name="uq_user_church_email"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    church_id: Mapped[str] = mapped_column(ForeignKey("churches.id", ondelete="CASCADE"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Bumped whenever every session must end at once — a password change, or a
    # detected refresh-token replay. Access tokens carry the value they were
    # minted under; get_current_user rejects any that no longer match, which is
    # what lets a stateless 1-hour JWT be killed before it expires.
    token_version: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
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
    # NULL while the token is live; stamped when it is rotated. A rotated token
    # is kept rather than deleted so that presenting it again is distinguishable
    # from presenting one that was never issued: the first is a replay to catch,
    # the second is garbage to ignore. The timestamp is what separates a genuine
    # replay (stamped long ago) from two tabs racing the same rotation (stamped
    # a moment ago).
    rotated_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, nullable=False)


class PasswordResetToken(Base):
    """One outstanding reset link for one account.

    The token itself is never stored — only its SHA-256 — so a dump of this
    table cannot be turned back into a working link. Hashing rather than
    bcrypt: the value is 32 bytes of `secrets`, so there is nothing to brute
    force and a slow hash would only cost the confirm route ~200ms.

    Rows are deleted when spent or superseded rather than kept and flagged. A
    refresh token is soft-deleted so a replay stays visible, but a reset link
    has no session to protect after the fact — presenting a spent one is
    answered the same way as presenting garbage, so there is nothing the extra
    row would let us say.
    """

    __tablename__ = "password_reset_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # Indexed because every request deletes this user's outstanding tokens
    # first; Postgres does not index a foreign key on its own.
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 64 hex characters, unique so a lookup can claim the row in one statement.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, nullable=False)


class Song(Base):
    """The canonical song a church sings, distinct from a week's use of it.

    `Score` stayed a weekly usage row (see below) rather than being renamed,
    so this table sits above it: title/file here are the source of truth, and
    every Score.song_id points at the row that answers "which song is this."
    """

    __tablename__ = "songs"
    __table_args__ = (UniqueConstraint("church_id", "title_key", name="uq_songs_church_title_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    church_id: Mapped[str] = mapped_column(
        ForeignKey("churches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploader_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Matching key, not display: normalize_title() applied to `title`. Kept as
    # its own column so the migration and the app compute it the same way
    # without either one re-deriving it from the other at read time.
    title_key: Mapped[str] = mapped_column(String(255), nullable=False)
    file_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow, nullable=False
    )

    church: Mapped["Church"] = relationship(back_populates="songs")
    usages: Mapped[list["Score"]] = relationship(back_populates="song", cascade="all, delete-orphan")


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    church_id: Mapped[str] = mapped_column(ForeignKey("churches.id", ondelete="CASCADE"), nullable=False)
    uploader_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    song_id: Mapped[str] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"), nullable=False, index=True)
    # Weekly snapshot: what was actually filed for this week. `songs` holds the
    # canonical values GET /scores now serves; these stay so a reupload can be
    # traced and so downgrading the split migration loses nothing.
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
    song: Mapped["Song"] = relationship(back_populates="usages")
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
