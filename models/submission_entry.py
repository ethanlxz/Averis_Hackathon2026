from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SubmissionEntry(Base):
    """Persisted hackathon submission payload for one email."""

    __tablename__ = "submission_entries"

    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(
        String(50),
        ForeignKey("email_messages.email_id"),
        nullable=False,
        unique=True,
        index=True,
    )
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
