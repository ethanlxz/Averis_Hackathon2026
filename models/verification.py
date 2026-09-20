from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Verification(Base):
    """SI vs BL verification decision for one email."""

    __tablename__ = "verifications"

    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(
        String(50),
        ForeignKey("email_messages.email_id"),
        nullable=False,
        index=True,
    )
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True, index=True)
    si_document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    bl_document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)
    category = Column(String(50), nullable=False, default="BL_COMPARISON", index=True)
    # MATCH / MISMATCH / REVIEW
    result = Column(String(50), nullable=False, default="PENDING", index=True)
    confidence = Column(Float, nullable=False, default=0.0)
    # pending / approved / corrected
    reviewer_status = Column(String(50), nullable=False, default="pending", index=True)
    review_reason = Column(String(50), nullable=True)
    has_defect = Column(Boolean, nullable=False, default=False)
    defect_fields = Column(JSON, nullable=False, default=list)
    mismatch_details = Column(JSON, nullable=False, default=list)
    review_details = Column(JSON, nullable=False, default=list)
    missing_fields = Column(JSON, nullable=False, default=list)
    corrected_fields = Column(JSON, nullable=True)
    verification_hash = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    email = relationship("EmailMessage", back_populates="verifications")
    document = relationship(
        "Document",
        back_populates="verifications",
        foreign_keys=[document_id],
    )
