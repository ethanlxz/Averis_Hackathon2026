from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AuditEvent(Base):
    """Immutable record of a document-processing or verification event."""

    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    occurred_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )
    email_id = Column(
        String(50),
        ForeignKey("email_messages.email_id"),
        nullable=True,
        index=True,
    )
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True, index=True)
    extraction_id = Column(Integer, ForeignKey("extractions.id"), nullable=True, index=True)
    verification_id = Column(
        Integer,
        ForeignKey("verifications.id"),
        nullable=True,
        index=True,
    )
    result = Column(String(50), nullable=True, index=True)
    reviewer_status = Column(String(50), nullable=True, index=True)
    verification_hash = Column(String(64), nullable=True, index=True)
    actor = Column(String(50), nullable=False, default="system")
    payload = Column(JSON, nullable=False, default=dict)
