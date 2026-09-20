from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(
        String(50),
        ForeignKey("email_messages.email_id"),
        nullable=False,
        index=True,
    )
    filename = Column(String(255), nullable=False, index=True)
    attachment_path = Column(String(500), nullable=False, unique=True, index=True)
    document_type = Column(String(50), nullable=False, index=True)
    file_extension = Column(String(20), nullable=False, index=True)
    file_size_bytes = Column(Integer, nullable=True)
    status = Column(String(50), nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    email = relationship("EmailMessage", back_populates="documents")
    verifications = relationship(
        "Verification",
        back_populates="document",
        foreign_keys="Verification.document_id",
    )
    extractions = relationship(
        "Extraction",
        back_populates="document",
    )
