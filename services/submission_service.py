from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from models.email_message import EmailMessage
from models.extraction import Extraction
from models.submission_entry import SubmissionEntry, utc_now
from models.verification import Verification
from services.classification_schema import ALLOWED_CATEGORIES, BL_COMPARISON


NON_BL_CATEGORIES = tuple(
    category for category in ALLOWED_CATEGORIES if category != BL_COMPARISON
)

_RESULT_TO_STATUS = {
    "MATCH": "OK",
    "MISMATCH": "MISMATCH",
    "REVIEW": "NEEDS_REVIEW",
}


class SubmissionService:
    """Builds and persists the official hackathon submission JSON."""

    def upsert_for_email(
        self,
        db: Session,
        email: EmailMessage,
        verification: Verification | None = None,
    ) -> SubmissionEntry | None:
        payload = self.build_payload(db, email, verification=verification)
        if payload is None:
            return None

        entry = (
            db.query(SubmissionEntry)
            .filter(SubmissionEntry.email_id == email.email_id)
            .one_or_none()
        )
        if entry is None:
            entry = SubmissionEntry(email_id=email.email_id)
            db.add(entry)

        entry.payload = payload
        entry.updated_at = utc_now()
        db.flush()
        return entry

    def refresh_all(self, db: Session) -> dict[str, int]:
        emails = db.query(EmailMessage).order_by(EmailMessage.email_id).all()
        email_ids = {email.email_id for email in emails}
        upserted = 0
        removed = 0

        for email in emails:
            if self.build_payload(db, email) is None:
                removed += self._delete_entry(db, email.email_id)
                continue
            self.upsert_for_email(db, email)
            upserted += 1

        stale_entries = (
            db.query(SubmissionEntry)
            .filter(~SubmissionEntry.email_id.in_(email_ids))
            .all()
            if email_ids
            else db.query(SubmissionEntry).all()
        )
        for entry in stale_entries:
            db.delete(entry)
            removed += 1

        db.flush()
        return {"upserted": upserted, "removed": removed}

    def export(self, db: Session) -> dict[str, dict[str, Any]]:
        entries = db.query(SubmissionEntry).order_by(SubmissionEntry.email_id).all()
        return {entry.email_id: entry.payload for entry in entries}

    def build_payload(
        self,
        db: Session,
        email: EmailMessage,
        verification: Verification | None = None,
    ) -> dict[str, Any] | None:
        category = email.category
        if category not in ALLOWED_CATEGORIES:
            return None

        if category in NON_BL_CATEGORIES:
            return {"category": category}

        verification = verification or self._latest_verification(db, email.email_id)
        if verification is None:
            return None

        status = _RESULT_TO_STATUS.get(verification.result)
        if status is None:
            return None

        payload: dict[str, Any] = {
            "category": BL_COMPARISON,
            "status": status,
            "review_reason": None,
            "has_defect": False,
            "defect_fields": [],
        }

        if verification.result == "MISMATCH":
            payload["has_defect"] = True
            payload["defect_fields"] = verification.defect_fields or []
        elif verification.result == "REVIEW":
            payload["review_reason"] = self._submission_review_reason(
                db,
                verification,
            )

        return payload

    def _submission_review_reason(
        self,
        db: Session,
        verification: Verification,
    ) -> str:
        if verification.review_reason == "missing_document":
            return "missing_attachment"
        if verification.review_reason == "missing_value":
            return "missing_value"
        if verification.review_reason == "port_code_mismatch":
            return "missing_value"
        if verification.review_reason == "extraction_error":
            return self._review_reason_from_extraction_errors(
                db,
                verification.email_id,
            )
        return "missing_value"

    def _review_reason_from_extraction_errors(
        self,
        db: Session,
        email_id: str,
    ) -> str:
        error_codes = self._extraction_error_codes(db, email_id)
        if "wrong_document_type" in error_codes:
            return "wrong_doc_type"
        if {"empty_text", "unrecognized_layout"} & error_codes:
            return "unreadable"
        return "unreadable"

    @staticmethod
    def _extraction_error_codes(db: Session, email_id: str) -> set[str]:
        extractions = (
            db.query(Extraction)
            .filter(Extraction.email_id == email_id)
            .order_by(Extraction.id)
            .all()
        )
        codes = set()
        for extraction in extractions:
            for error in extraction.errors or []:
                if isinstance(error, dict) and error.get("code"):
                    codes.add(str(error["code"]))
        return codes

    @staticmethod
    def _latest_verification(db: Session, email_id: str) -> Verification | None:
        return (
            db.query(Verification)
            .filter(Verification.email_id == email_id)
            .order_by(Verification.id.desc())
            .first()
        )

    @staticmethod
    def _delete_entry(db: Session, email_id: str) -> int:
        entry = (
            db.query(SubmissionEntry)
            .filter(SubmissionEntry.email_id == email_id)
            .one_or_none()
        )
        if entry is None:
            return 0
        db.delete(entry)
        return 1
