from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.database import Base, engine, init_db
from models.document import Document
from models.email_message import EmailMessage
from models.email_message import utc_now
from services.email_classifier import EmailClassifier
from services.inbox_service import InboxService
from services.audit_service import record_classification, record_document_registration


def infer_document_type(attachment_path: str) -> str:
    stem = Path(attachment_path).stem.upper()
    if stem.endswith("_SI") or "_SI_" in stem:
        return "SI"
    if stem.endswith("_BL") or "_BL_" in stem:
        return "BL"
    if "INVOICE" in stem:
        return "INVOICE"
    return "UNKNOWN"


def reset_database() -> None:
    Base.metadata.drop_all(bind=engine)
    init_db()


class InputDataImporter:
    def __init__(
        self,
        inbox_service: InboxService | None = None,
        email_classifier: EmailClassifier | None = None,
    ) -> None:
        self.inbox_service = inbox_service or InboxService()
        self.email_classifier = email_classifier or EmailClassifier()

    def import_all(self, db: Session) -> dict[str, int]:
        init_db()

        email_count = 0
        document_count = 0

        for email in self.inbox_service.list_emails():
            email_count += 1
            email_record = self._upsert_email(db, email)

            for attachment_path in email.get("attachments", []):
                document_count += 1
                document, created = self._upsert_document(
                    db,
                    email["email_id"],
                    attachment_path,
                )
                if created:
                    record_document_registration(db, email_record, document)

            self._classify_email(email_record, email.get("attachments", []))
            record_classification(db, email_record)

        db.commit()
        return {"emails": email_count, "documents": document_count}

    def _upsert_email(self, db: Session, email: dict[str, Any]) -> EmailMessage:
        record = (
            db.query(EmailMessage)
            .filter(EmailMessage.email_id == email["email_id"])
            .one_or_none()
        )

        if record is None:
            record = EmailMessage(email_id=email["email_id"])
            db.add(record)

        attachments = email.get("attachments", [])
        record.sender = email.get("from", "")
        record.subject = email.get("subject", "")
        record.body = email.get("body", "")
        record.attachment_count = len(attachments)
        return record

    def _classify_email(
        self,
        record: EmailMessage,
        attachments: list[str],
    ) -> None:
        result = self.email_classifier.classify(
            subject=record.subject,
            body=record.body,
            attachments=attachments,
        )
        record.category = result.category
        record.classification_confidence = result.confidence
        record.classification_source = result.source
        record.classified_at = utc_now()

    def _upsert_document(
        self,
        db: Session,
        email_id: str,
        attachment_path: str,
    ) -> tuple[Document, bool]:
        record = (
            db.query(Document)
            .filter(Document.attachment_path == attachment_path)
            .one_or_none()
        )

        created = record is None
        if record is None:
            record = Document(attachment_path=attachment_path)
            db.add(record)

        path = Path(attachment_path)
        record.email_id = email_id
        record.filename = path.name
        record.document_type = infer_document_type(attachment_path)
        record.file_extension = path.suffix.lower().lstrip(".") or "unknown"
        record.file_size_bytes = self.inbox_service.attachment_size(attachment_path)
        record.status = "imported"
        return record, created
