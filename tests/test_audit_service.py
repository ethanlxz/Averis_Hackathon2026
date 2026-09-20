import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from models.audit_event import AuditEvent
from models.document import Document
from models.email_message import EmailMessage
from models.extraction import Extraction
from models.verification import Verification
from services.audit_service import (
    list_events,
    record_classification,
    record_document_registration,
    record_extraction,
    record_verification,
    serialize_detail,
)
from services.verification_service import VerificationService


class AuditServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.email = EmailMessage(
            email_id="email_audit",
            sender="ops@example.com",
            subject="Audit subject",
            body="Body",
            attachment_count=2,
            category="BL_COMPARISON",
            classification_confidence=0.95,
            classification_source="rules",
            classified_at=datetime(2026, 9, 20, 1, 0, tzinfo=timezone.utc),
        )
        self.db.add(self.email)
        self.db.flush()
        self.si_doc = Document(
            email_id=self.email.email_id,
            filename="email_audit_SI.txt",
            attachment_path="attachments/email_audit_SI.txt",
            document_type="SI",
            file_extension="txt",
            status="imported",
        )
        self.bl_doc = Document(
            email_id=self.email.email_id,
            filename="email_audit_BL.txt",
            attachment_path="attachments/email_audit_BL.txt",
            document_type="BL",
            file_extension="txt",
            status="imported",
        )
        self.db.add_all([self.si_doc, self.bl_doc])
        self.db.flush()
        self.si = Extraction(
            email_id=self.email.email_id,
            document_id=self.si_doc.id,
            document_type="SI",
            extraction_method="txt",
            fields={"shipper": "A", "container_count": "2"},
            normalized_fields={"Shipper": "a", "Container Count": "2"},
            status="ok",
            detected_document_type="SI",
            errors=[],
            warnings=[],
        )
        self.bl = Extraction(
            email_id=self.email.email_id,
            document_id=self.bl_doc.id,
            document_type="BL",
            extraction_method="txt",
            fields={"shipper": "B", "container_count": "2"},
            normalized_fields={"Shipper": "b", "Container Count": "2"},
            status="ok",
            detected_document_type="BL",
            errors=[],
            warnings=[],
        )
        self.db.add_all([self.si, self.bl])
        self.db.flush()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

    def test_records_process_events(self):
        record_classification(self.db, self.email)
        record_document_registration(self.db, self.email, self.si_doc)
        record_extraction(self.db, self.email, self.si_doc, self.si)
        self.db.commit()

        events = self.db.query(AuditEvent).order_by(AuditEvent.id).all()
        self.assertEqual(
            [event.event_type for event in events],
            [
                "classification_completed",
                "document_registered",
                "extraction_completed",
            ],
        )
        self.assertEqual(events[1].document_id, self.si_doc.id)
        self.assertEqual(events[2].payload["extraction"]["status"], "ok")

    def test_verification_snapshot_is_immutable_and_filterable_by_hash(self):
        verification = VerificationService().verify_email(self.db, self.email)
        original_hash = verification.verification_hash
        event = (
            self.db.query(AuditEvent)
            .filter(AuditEvent.event_type == "verification_completed")
            .one()
        )
        self.si.fields = {"shipper": "CHANGED"}
        self.db.commit()

        detail = serialize_detail(self.db, event)
        self.assertEqual(detail["verification_hash"], original_hash)
        self.assertEqual(detail["payload"]["si"]["display_fields"]["Shipper"], "A")

        filtered = list_events(self.db, search=original_hash[:16])
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["events"][0]["verification_hash"], original_hash)

    def test_review_sets_reviewed_at_and_records_audit_event(self):
        verification = VerificationService().verify_email(self.db, self.email)
        reviewed = VerificationService().review(
            self.db,
            verification.id,
            "correct",
            {"shipper": "B"},
        )
        self.db.commit()

        self.assertIsNotNone(reviewed.reviewed_at)
        event = (
            self.db.query(AuditEvent)
            .filter(AuditEvent.event_type == "verification_corrected")
            .one()
        )
        self.assertEqual(event.actor, "reviewer")
        self.assertEqual(event.payload["verification"]["corrected_fields"]["shipper"], "B")

    def test_list_events_filters_and_orders(self):
        record_classification(self.db, self.email)
        record_document_registration(self.db, self.email, self.si_doc)
        record_extraction(self.db, self.email, self.si_doc, self.si)
        self.db.commit()

        filtered = list_events(self.db, event_type="document_registered", page_size=1)
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["events"][0]["event_type"], "document_registered")

        paged = list_events(self.db, page=1, page_size=2)
        self.assertEqual(paged["page"], 1)
        self.assertEqual(len(paged["events"]), 2)
        self.assertGreater(paged["events"][0]["id"], paged["events"][1]["id"])


if __name__ == "__main__":
    unittest.main()
