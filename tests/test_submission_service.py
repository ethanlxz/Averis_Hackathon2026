import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from models.document import Document
from models.email_message import EmailMessage
from models.extraction import Extraction
from models.submission_entry import SubmissionEntry
from models.verification import Verification
from services.classification_schema import ClassificationResult
from services.input_importer import InputDataImporter
from services.submission_service import SubmissionService
from services.verification_service import VerificationService


class SubmissionServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.service = SubmissionService()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

    def _email(self, email_id="email_001", category="BL_COMPARISON"):
        email = EmailMessage(
            email_id=email_id,
            sender="ops@example.com",
            subject="Shipping docs",
            body="Please verify.",
            attachment_count=0,
            category=category,
            classification_confidence=0.9,
            classification_source="rules",
        )
        self.db.add(email)
        self.db.flush()
        return email

    def _verification(
        self,
        email,
        result,
        review_reason=None,
        has_defect=False,
        defect_fields=None,
    ):
        verification = Verification(
            email_id=email.email_id,
            category=email.category,
            result=result,
            confidence=1.0,
            reviewer_status="pending",
            review_reason=review_reason,
            has_defect=has_defect,
            defect_fields=defect_fields or [],
            mismatch_details=[],
            review_details=[],
            missing_fields=[],
        )
        self.db.add(verification)
        self.db.flush()
        return verification

    def _extraction_error(self, email, code):
        extraction = Extraction(
            email_id=email.email_id,
            document_type="BL",
            extraction_method="txt",
            fields={},
            normalized_fields={},
            status="error",
            detected_document_type="INVOICE",
            errors=[{"code": code}],
            warnings=[],
        )
        self.db.add(extraction)
        self.db.flush()
        return extraction

    def test_non_bl_category_payload_is_category_only(self):
        email = self._email("email_invoice", "INVOICE_QUERY")

        entry = self.service.upsert_for_email(self.db, email)

        self.assertEqual(entry.payload, {"category": "INVOICE_QUERY"})

    def test_match_payload_uses_ok_status(self):
        email = self._email()
        verification = self._verification(email, "MATCH")

        entry = self.service.upsert_for_email(self.db, email, verification)

        self.assertEqual(
            entry.payload,
            {
                "category": "BL_COMPARISON",
                "status": "OK",
                "review_reason": None,
                "has_defect": False,
                "defect_fields": [],
            },
        )

    def test_mismatch_payload_preserves_defect_fields(self):
        email = self._email()
        verification = self._verification(
            email,
            "MISMATCH",
            has_defect=True,
            defect_fields=["consignee"],
        )

        entry = self.service.upsert_for_email(self.db, email, verification)

        self.assertEqual(entry.payload["status"], "MISMATCH")
        self.assertIsNone(entry.payload["review_reason"])
        self.assertTrue(entry.payload["has_defect"])
        self.assertEqual(entry.payload["defect_fields"], ["consignee"])

    def test_missing_document_review_maps_to_missing_attachment(self):
        email = self._email()
        verification = self._verification(email, "REVIEW", "missing_document")

        entry = self.service.upsert_for_email(self.db, email, verification)

        self.assertEqual(entry.payload["status"], "NEEDS_REVIEW")
        self.assertEqual(entry.payload["review_reason"], "missing_attachment")

    def test_wrong_document_type_error_maps_to_wrong_doc_type(self):
        email = self._email("email_501")
        verification = self._verification(email, "REVIEW", "extraction_error")
        self._extraction_error(email, "wrong_document_type")

        entry = self.service.upsert_for_email(self.db, email, verification)

        self.assertEqual(entry.payload["review_reason"], "wrong_doc_type")

    def test_unreadable_extraction_errors_map_to_unreadable(self):
        for code in ("empty_text", "unrecognized_layout", "unexpected"):
            email = self._email(f"email_{code}", "BL_COMPARISON")
            verification = self._verification(email, "REVIEW", "extraction_error")
            self._extraction_error(email, code)

            entry = self.service.upsert_for_email(self.db, email, verification)

            self.assertEqual(entry.payload["review_reason"], "unreadable")

    def test_missing_value_review_maps_to_missing_value(self):
        email = self._email()
        verification = self._verification(email, "REVIEW", "missing_value")

        entry = self.service.upsert_for_email(self.db, email, verification)

        self.assertEqual(entry.payload["review_reason"], "missing_value")

    def test_refresh_removes_unclassified_entries(self):
        email = self._email("email_unclassified", None)
        self.db.add(
            SubmissionEntry(
                email_id=email.email_id,
                payload={"category": "GENERAL"},
            )
        )
        self.db.flush()

        result = self.service.refresh_all(self.db)

        self.assertEqual(result["removed"], 1)
        self.assertEqual(self.service.export(self.db), {})


class FakeInboxService:
    def list_emails(self):
        return [
            {
                "email_id": "email_003",
                "from": "billing@example.com",
                "subject": "Invoice question",
                "body": "Can you check invoice status?",
                "attachments": [],
            }
        ]

    def attachment_size(self, attachment_path):
        return 0


class FakeClassifier:
    def classify(self, subject, body, attachments):
        return ClassificationResult(
            category="INVOICE_QUERY",
            confidence=0.95,
            source="test",
        )


class SubmissionProgressTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

    def test_import_classification_creates_non_bl_submission_row(self):
        importer = InputDataImporter(FakeInboxService(), FakeClassifier())

        importer.import_all(self.db)

        entry = self.db.query(SubmissionEntry).one()
        self.assertEqual(entry.email_id, "email_003")
        self.assertEqual(entry.payload, {"category": "INVOICE_QUERY"})

    def test_verification_creates_bl_submission_row(self):
        email = EmailMessage(
            email_id="email_verified",
            sender="ops@example.com",
            subject="Shipping docs",
            body="Please verify.",
            attachment_count=2,
            category="BL_COMPARISON",
        )
        self.db.add(email)
        self.db.flush()
        si_doc = Document(
            email_id=email.email_id,
            filename="email_verified_SI.txt",
            attachment_path="attachments/email_verified_SI.txt",
            document_type="SI",
            file_extension="txt",
            status="imported",
        )
        bl_doc = Document(
            email_id=email.email_id,
            filename="email_verified_BL.txt",
            attachment_path="attachments/email_verified_BL.txt",
            document_type="BL",
            file_extension="txt",
            status="imported",
        )
        self.db.add_all([si_doc, bl_doc])
        self.db.flush()
        fields = {
            "shipper": "A",
            "consignee": "B",
            "notify_party": "C",
            "port_of_loading": "Rotterdam",
            "port_of_discharge": "Singapore",
            "container_count": "1",
            "gross_weight_kg": "1000",
        }
        self.db.add_all(
            [
                Extraction(
                    email_id=email.email_id,
                    document_id=si_doc.id,
                    document_type="SI",
                    extraction_method="txt",
                    fields=fields,
                    normalized_fields={},
                    status="ok",
                    detected_document_type="SI",
                    errors=[],
                    warnings=[],
                ),
                Extraction(
                    email_id=email.email_id,
                    document_id=bl_doc.id,
                    document_type="BL",
                    extraction_method="txt",
                    fields=fields,
                    normalized_fields={},
                    status="ok",
                    detected_document_type="BL",
                    errors=[],
                    warnings=[],
                ),
            ]
        )
        self.db.flush()

        verification = VerificationService().verify_email(self.db, email)
        entry = SubmissionService().upsert_for_email(self.db, email, verification)

        self.assertEqual(entry.payload["category"], "BL_COMPARISON")
        self.assertEqual(entry.payload["status"], "OK")


if __name__ == "__main__":
    unittest.main()
