from typing import Literal

from sqlalchemy.orm import Session

from models.email_message import EmailMessage
from models.verification import Verification
from services.classification_schema import BL_COMPARISON
from services.extraction_service import ExtractionService
from services.submission_service import SubmissionService
from services.verification_service import VerificationService


VerifyMode = Literal["all", "pending"]


class BLVerificationBatchService:
    def __init__(
        self,
        extraction_service: ExtractionService | None = None,
        verification_service: VerificationService | None = None,
        submission_service: SubmissionService | None = None,
    ):
        self.extraction_service = extraction_service or ExtractionService()
        self.verification_service = verification_service or VerificationService()
        self.submission_service = submission_service or SubmissionService()

    def run(self, db: Session, mode: VerifyMode) -> dict[str, int | str]:
        if mode not in ("all", "pending"):
            raise ValueError("mode must be all or pending")

        emails = (
            db.query(EmailMessage)
            .filter(EmailMessage.category == BL_COMPARISON)
            .order_by(EmailMessage.email_id)
            .all()
        )
        verified_email_ids = {
            email_id
            for (email_id,) in db.query(Verification.email_id).distinct().all()
        }

        processed = 0
        skipped = 0
        for email in emails:
            if mode == "pending" and email.email_id in verified_email_ids:
                skipped += 1
                continue

            self.extraction_service.process_email(db, email)
            verification = self.verification_service.verify_email(db, email)
            self.submission_service.upsert_for_email(db, email, verification)
            processed += 1

        return {
            "status": "verified",
            "mode": mode,
            "emails": len(emails),
            "verified": processed,
            "skipped": skipped,
        }
