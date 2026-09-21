import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from models.email_message import EmailMessage
from models.submission_entry import SubmissionEntry
from models.verification import Verification
from routers.api import download_submission_json
from services.bl_verification_service import BLVerificationBatchService


class FakeExtractionService:
    def __init__(self):
        self.processed = []

    def process_email(self, db, email):
        self.processed.append(email.email_id)
        return {"email_id": email.email_id, "extractions": []}


class FakeVerificationService:
    def __init__(self):
        self.verified = []

    def verify_email(self, db, email):
        self.verified.append(email.email_id)
        verification = (
            db.query(Verification)
            .filter(Verification.email_id == email.email_id)
            .one_or_none()
        )
        if verification is None:
            verification = Verification(email_id=email.email_id)
            db.add(verification)

        verification.category = email.category
        verification.result = "MATCH"
        verification.confidence = 1.0
        verification.reviewer_status = "pending"
        verification.review_reason = None
        verification.has_defect = False
        verification.defect_fields = []
        verification.mismatch_details = []
        verification.review_details = []
        verification.missing_fields = []
        db.flush()
        return verification


class BLVerificationBatchServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.extractor = FakeExtractionService()
        self.verifier = FakeVerificationService()
        self.service = BLVerificationBatchService(
            extraction_service=self.extractor,
            verification_service=self.verifier,
        )

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

    def _email(self, email_id, category="BL_COMPARISON"):
        email = EmailMessage(
            email_id=email_id,
            sender="ops@example.com",
            subject="Shipping docs",
            body="Please verify.",
            attachment_count=2,
            category=category,
            classification_confidence=0.9,
            classification_source="rules",
        )
        self.db.add(email)
        self.db.flush()
        return email

    def _verified_email(self, email_id):
        email = self._email(email_id)
        self.db.add(
            Verification(
                email_id=email.email_id,
                category=email.category,
                result="MATCH",
                confidence=1.0,
                reviewer_status="pending",
                has_defect=False,
                defect_fields=[],
                mismatch_details=[],
                review_details=[],
                missing_fields=[],
            )
        )
        self.db.flush()
        return email

    def test_pending_mode_skips_already_verified_emails(self):
        self._verified_email("email_done")
        self._email("email_pending")
        self._email("email_general", category="GENERAL")

        result = self.service.run(self.db, "pending")

        self.assertEqual(result["emails"], 2)
        self.assertEqual(result["verified"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(self.verifier.verified, ["email_pending"])

    def test_all_mode_reruns_every_bl_comparison_email(self):
        self._verified_email("email_done")
        self._email("email_pending")

        result = self.service.run(self.db, "all")

        self.assertEqual(result["emails"], 2)
        self.assertEqual(result["verified"], 2)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(self.verifier.verified, ["email_done", "email_pending"])

    def test_running_verify_twice_does_not_duplicate_submission_entries(self):
        self._email("email_one")
        self._email("email_two")

        self.service.run(self.db, "all")
        self.service.run(self.db, "all")

        entries = self.db.query(SubmissionEntry).order_by(SubmissionEntry.email_id).all()
        self.assertEqual([entry.email_id for entry in entries], ["email_one", "email_two"])

    def test_download_submission_json_returns_attachment_response(self):
        email = self._email("email_export")
        verification = self.verifier.verify_email(self.db, email)
        self.service.submission_service.upsert_for_email(self.db, email, verification)

        response = download_submission_json(self.db)

        self.assertEqual(response.media_type, "application/json")
        self.assertIn("attachment", response.headers["content-disposition"])
        self.assertEqual(
            json.loads(response.body),
            {
                "email_export": {
                    "category": "BL_COMPARISON",
                    "defect_fields": [],
                    "has_defect": False,
                    "review_reason": None,
                    "status": "OK",
                }
            },
        )


if __name__ == "__main__":
    unittest.main()
