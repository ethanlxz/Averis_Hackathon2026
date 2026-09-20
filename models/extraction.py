from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Extraction(Base):
    """A single shipment-field extraction result for one SI/BL document."""

    __tablename__ = "extractions"

    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(
        String(50),
        ForeignKey("email_messages.email_id"),
        nullable=False,
        index=True,
    )
    document_id = Column(
        Integer,
        ForeignKey("documents.id"),
        nullable=True,
        index=True,
    )
    document_type = Column(String(50), nullable=False, index=True)  # "SI" or "BL"
    extraction_method = Column(String(50), nullable=False, index=True)
    fields = Column(JSON, nullable=False, default=dict)
    normalized_fields = Column(JSON, nullable=False, default=dict)
    status = Column(String(50), nullable=False, default="pending", index=True)
    detected_document_type = Column(String(50), nullable=True, index=True)
    errors = Column(JSON, nullable=False, default=list)
    warnings = Column(JSON, nullable=False, default=list)
    processed_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    email = relationship("EmailMessage", back_populates="extractions")
    document = relationship("Document", back_populates="extractions")
