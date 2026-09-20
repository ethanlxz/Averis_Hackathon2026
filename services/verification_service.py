from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from models.email_message import EmailMessage
from models.extraction import Extraction
from models.verification import Verification, utc_now
from services.audit_service import record_verification
from services.comparison_engine import COMPARISON_FIELDS, ComparisonEngine


VERDICT_LABELS = {
    "MATCH": "Match",
    "MISMATCH": "Mismatch",
    "REVIEW": "Review",
    "PENDING": "Pending",
}

VERDICT_CLASSES = {
    "MATCH": "success",
    "MISMATCH": "danger",
    "REVIEW": "warning",
    "PENDING": "",
}

_STATUS_TO_RESULT = {
    "OK": "MATCH",
    "MISMATCH": "MISMATCH",
    "NEEDS_REVIEW": "REVIEW",
}


class VerificationService:
    """Runs SI/BL comparison and persists the verification decision."""

    def __init__(self, comparison_engine: ComparisonEngine | None = None) -> None:
        self.comparison = comparison_engine or ComparisonEngine()

    # -- verification --------------------------------------------------
    def verify_email(self, db: Session, email: EmailMessage) -> Verification:
        extractions = (
            db.query(Extraction)
            .filter(Extraction.email_id == email.email_id)
            .all()
        )
        by_type = {e.document_type: e for e in extractions}
        si = by_type.get("SI")
        bl = by_type.get("BL")

        if si is None or bl is None:
            return self._upsert(
                db,
                email,
                si,
                bl,
                result="REVIEW",
                review_reason="missing_document",
                confidence=0.0,
                comparison=None,
            )

        if si.status == "error" or bl.status == "error":
            return self._upsert(
                db,
                email,
                si,
                bl,
                result="REVIEW",
                review_reason="extraction_error",
                confidence=0.0,
                comparison=None,
            )

        comparison = self.comparison.compare(si.fields or {}, bl.fields or {})
        result = _STATUS_TO_RESULT.get(comparison["status"], "REVIEW")

        return self._upsert(
            db,
            email,
            si,
            bl,
            result=result,
            review_reason=comparison.get("review_reason"),
            confidence=self._confidence(comparison),
            comparison=comparison,
        )

    # -- human review ---------------------------------------------------
    def review(
        self,
        db: Session,
        verification_id: int,
        action: str,
        corrected_fields: dict | None = None,
    ) -> Verification | None:
        record = (
            db.query(Verification)
            .filter(Verification.id == verification_id)
            .one_or_none()
        )
        if record is None:
            return None

        if action == "approve":
            record.reviewer_status = "approved"
        elif action == "correct":
            record.reviewer_status = "corrected"
            record.corrected_fields = corrected_fields or {}
        else:
            return record

        record.reviewed_at = utc_now()
        db.flush()

        email = (
            db.query(EmailMessage)
            .filter(EmailMessage.email_id == record.email_id)
            .one_or_none()
        )
        if email is not None:
            extractions = (
                db.query(Extraction)
                .filter(Extraction.email_id == record.email_id)
                .all()
            )
            by_type = {extraction.document_type: extraction for extraction in extractions}
            record_verification(
                db,
                email,
                record,
                by_type.get("SI"),
                by_type.get("BL"),
                event_type=(
                    "verification_approved"
                    if record.reviewer_status == "approved"
                    else "verification_corrected"
                ),
                actor="reviewer",
            )
        return record

    # -- persistence ----------------------------------------------------
    def _upsert(
        self,
        db: Session,
        email: EmailMessage,
        si: Extraction | None,
        bl: Extraction | None,
        result: str,
        review_reason: str | None,
        confidence: float,
        comparison: dict[str, Any] | None,
    ) -> Verification:
        record = (
            db.query(Verification)
            .filter(Verification.email_id == email.email_id)
            .one_or_none()
        )
        if record is None:
            record = Verification(email_id=email.email_id)
            db.add(record)

        # A fresh decision invalidates any previous human decision.
        if record.result != result:
            record.reviewer_status = "pending"
            record.corrected_fields = None

        record.si_document_id = si.id if si else None
        record.bl_document_id = bl.id if bl else None
        record.document_id = bl.id if bl else (si.id if si else None)
        record.category = email.category or "BL_COMPARISON"
        record.result = result
        record.confidence = confidence
        record.review_reason = review_reason
        record.has_defect = bool(comparison["has_defect"]) if comparison else False
        record.defect_fields = comparison["defect_fields"] if comparison else []
        record.mismatch_details = comparison["mismatch_details"] if comparison else []
        record.review_details = comparison["review_details"] if comparison else []
        record.missing_fields = comparison["missing_fields"] if comparison else []
        record.verification_hash = self._hash(email, si, bl)
        db.flush()
        record_verification(db, email, record, si, bl)
        return record

    # -- helpers --------------------------------------------------------
    @staticmethod
    def _confidence(comparison: dict[str, Any]) -> float:
        total = len(COMPARISON_FIELDS)
        missing = len(comparison.get("missing_fields", []) or [])
        mismatches = len(comparison.get("defect_fields", []) or [])
        matched = total - missing - mismatches
        return round(matched / total, 4) if total else 0.0

    @staticmethod
    def _hash(
        email: EmailMessage,
        si: Extraction | None,
        bl: Extraction | None,
    ) -> str:
        payload = {
            "email_id": email.email_id,
            "si_fields": si.fields if si else None,
            "bl_fields": bl.fields if bl else None,
        }
        canonical = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def serialize_verification(record: Verification | None) -> dict[str, Any] | None:
    if record is None:
        return None

    return {
        "id": record.id,
        "email_id": record.email_id,
        "si_document_id": record.si_document_id,
        "bl_document_id": record.bl_document_id,
        "result": record.result,
        "confidence": record.confidence,
        "reviewer_status": record.reviewer_status,
        "review_reason": record.review_reason,
        "has_defect": record.has_defect,
        "defect_fields": record.defect_fields or [],
        "mismatch_details": record.mismatch_details or [],
        "review_details": record.review_details or [],
        "missing_fields": record.missing_fields or [],
        "corrected_fields": record.corrected_fields,
        "verification_hash": record.verification_hash,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "reviewed_at": record.reviewed_at.isoformat() if record.reviewed_at else None,
        "verdict_label": VERDICT_LABELS.get(record.result, record.result),
        "verdict_class": VERDICT_CLASSES.get(record.result, ""),
    }
