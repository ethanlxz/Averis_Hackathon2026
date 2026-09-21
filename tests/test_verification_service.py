import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from models.audit_event import AuditEvent
from models.document import Document
from models.email_message import EmailMessage
from models.extraction import Extraction
from models.verification import Verification
from services.audit_service import serialize_detail
from services.verification_service import VerificationService, serialize_verification


class VerificationServiceMissingDocumentTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

    def _email_with_extraction(self, email_id: str, document_type: str) -> EmailMessage:
        email = EmailMessage(
            email_id=email_id,
            sender="ops@example.com",
            subject=f"{document_type} only",
            body="Please verify attached document.",
            attachment_count=1,
            category="BL_COMPARISON",
        )
        self.db.add(email)
        self.db.flush()

        document = Document(
            email_id=email.email_id,
            filename=f"{email_id}_{document_type}.txt",
            attachment_path=f"attachments/{email_id}_{document_type}.txt",
            document_type=document_type,
            file_extension="txt",
            status="imported",
        )
        self.db.add(document)
        self.db.flush()

        extraction = Extraction(
            email_id=email.email_id,
            document_id=document.id,
            document_type=document_type,
            extraction_method="txt",
            fields={"shipper": "A", "container_count": "1"},
            normalized_fields={"Shipper": "A", "Container Count": "1"},
            status="ok",
            detected_document_type=document_type,
            errors=[],
            warnings=[],
        )
        self.db.add(extraction)
        self.db.flush()
        return email

    def test_only_si_requires_review_for_missing_bl(self):
        email = self._email_with_extraction("email_only_si", "SI")

        verification = VerificationService().verify_email(self.db, email)
        serialized = serialize_verification(verification)

        self.assertEqual(verification.result, "REVIEW")
        self.assertEqual(verification.review_reason, "missing_document")
        self.assertEqual(verification.missing_fields, ["missing_bl_document"])
        self.assertEqual(serialized["missing_field_labels"], ["Missing BL document"])
        self.assertEqual(serialized["review_reason_label"], "Missing required document")

    def test_only_bl_requires_review_for_missing_si_and_audit_snapshot_records_it(self):
        email = self._email_with_extraction("email_only_bl", "BL")

        verification = VerificationService().verify_email(self.db, email)
        event = (
            self.db.query(AuditEvent)
            .filter(AuditEvent.event_type == "verification_completed")
            .one()
        )
        detail = serialize_detail(self.db, event)

        self.assertEqual(verification.result, "REVIEW")
        self.assertEqual(verification.review_reason, "missing_document")
        self.assertEqual(verification.missing_fields, ["missing_si_document"])
        self.assertEqual(
            detail["payload"]["verification"]["missing_field_labels"],
            ["Missing SI document"],
        )


if __name__ == "__main__":
    unittest.main()
