from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT
from models.document import Document
from models.email_message import EmailMessage
from models.extraction import Extraction, utc_now
from services.document_parser import DocumentParser, ShipmentFields, snake_to_display
from services.document_validator import DocumentValidator, ValidationResult
from services.field_normalizer import normalize_shipment_json
from services.inbox_service import InboxService
from services.llm_service import LLMService
from services.ocr_service import OCRService
from services.audit_service import record_extraction


class ExtractionService:
    """Runs the document-extraction pipeline and persists per-document results.

    Flow per document:
        1. load raw bytes
        2. detect document type (TXT / DOCX / PDF / image / XLSX)
        3. extract raw text (native text, PDF text, or OCR)
        4. parse the seven shipment fields into structured JSON
        5. optionally fill gaps with the DeepSeek LLM
        6. validate the result (wrong format, missing fields, unreadable text)
        7. upsert an Extraction row with a unique id, extraction_method,
           status/errors/warnings, and processed_at.
    """

    def __init__(
        self,
        inbox_service: InboxService | None = None,
        parser: DocumentParser | None = None,
        ocr_service: OCRService | None = None,
        llm_service: LLMService | None = None,
        validator: DocumentValidator | None = None,
    ) -> None:
        self.inbox = inbox_service or InboxService()
        self.ocr = ocr_service or OCRService()
        self.parser = parser or DocumentParser(
            reader=self._read_bytes,
            ocr_service=self.ocr,
        )
        self.llm = llm_service or LLMService()
        self.validator = validator or DocumentValidator()

    # -- public API -----------------------------------------------------
    def process_email(self, db: Session, email: EmailMessage) -> dict[str, Any]:
        documents = (
            db.query(Document)
            .filter(Document.email_id == email.email_id)
            .order_by(Document.id)
            .all()
        )

        extractions = []
        for document in documents:
            if document.document_type not in ("SI", "BL"):
                continue
            record = self.extract_document(db, email, document)
            record_extraction(db, email, document, record)
            extractions.append(self.serialize(record))

        return {
            "email_id": email.email_id,
            "category": email.category,
            "extractions": extractions,
        }

    def extract_document(
        self,
        db: Session,
        email: EmailMessage,
        document: Document,
    ) -> Extraction:
        text, method = self.parser.extract_text(document.attachment_path)
        fields = self.parser.parse_text(text)

        if not fields.is_complete() and self.llm.is_configured and text:
            llm_fields = self.llm.extract_shipment_fields(text)
            if llm_fields:
                fields = self.parser.merge_fields(fields, llm_fields)
                method = f"{method}+llm"

        validation = self.validator.validate(document.document_type, text, fields)
        return self._upsert(db, email, document, method, fields, validation)

    # -- persistence ----------------------------------------------------
    def _upsert(
        self,
        db: Session,
        email: EmailMessage,
        document: Document,
        method: str,
        fields: ShipmentFields,
        validation: ValidationResult,
    ) -> Extraction:
        record = (
            db.query(Extraction)
            .filter(Extraction.document_id == document.id)
            .one_or_none()
        )
        if record is None:
            record = Extraction(document_id=document.id)
            db.add(record)

        record.email_id = email.email_id
        record.document_type = document.document_type
        record.extraction_method = method
        record.fields = fields.to_dict()
        record.normalized_fields = normalize_shipment_json(fields.to_display_dict())
        record.status = validation.status
        record.detected_document_type = validation.detected_document_type
        record.errors = validation.errors
        record.warnings = validation.warnings
        record.processed_at = utc_now()
        db.flush()
        return record

    # -- serialization --------------------------------------------------
    @staticmethod
    def serialize(record: Extraction) -> dict[str, Any]:
        return {
            "id": record.id,
            "email_id": record.email_id,
            "document_id": record.document_id,
            "document_type": record.document_type,
            "detected_document_type": record.detected_document_type,
            "extraction_method": record.extraction_method,
            "status": record.status,
            "errors": record.errors or [],
            "warnings": record.warnings or [],
            "processed_at": (
                record.processed_at.isoformat() if record.processed_at else None
            ),
            "fields": snake_to_display(record.fields or {}),
            "normalized_fields": record.normalized_fields or {},
        }

    # -- helpers --------------------------------------------------------
    def _read_bytes(self, attachment_path: str) -> bytes | None:
        try:
            return self.inbox.read_attachment_bytes(attachment_path)
        except Exception:
            pass

        try:
            full_path = Path(PROJECT_ROOT) / attachment_path
            if full_path.exists():
                return full_path.read_bytes()
        except OSError:
            pass
        return None
