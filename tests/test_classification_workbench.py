import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from services.classification_schema import (
    ALLOWED_CATEGORIES,
    BL_COMPARISON,
    GENERAL,
    INVOICE_QUERY,
    SI_REQUEST,
    SPAM,
)
from services.classification_workbench import (
    build_classification_view_model,
    classification_summary,
)


def email(
    email_id,
    category,
    classification_source="deepseek",
    documents=None,
):
    return SimpleNamespace(
        id=1,
        email_id=email_id,
        sender="ops@example.com",
        subject=f"Subject {email_id}",
        body="Body preview text",
        attachment_count=len(documents or []),
        category=category,
        classification_confidence=0.91 if category else 0.0,
        classification_source=classification_source,
        classified_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
        created_at=datetime(2026, 9, 20, tzinfo=timezone.utc),
        documents=documents or [],
    )


def document(filename, document_type):
    return SimpleNamespace(
        id=1,
        filename=filename,
        document_type=document_type,
        status="imported",
    )


class ClassificationWorkbenchTests(unittest.TestCase):
    def test_counts_include_all_official_categories(self):
        model = build_classification_view_model(
            [
                email("email_004", BL_COMPARISON),
                email("email_005", SI_REQUEST),
            ]
        )

        self.assertEqual(set(model["counts"]), set(ALLOWED_CATEGORIES))
        self.assertEqual(model["counts"][BL_COMPARISON], 1)
        self.assertEqual(model["counts"][SI_REQUEST], 1)
        self.assertEqual(model["counts"][INVOICE_QUERY], 0)
        self.assertEqual(model["counts"][GENERAL], 0)
        self.assertEqual(model["counts"][SPAM], 0)

    def test_default_category_is_bl_comparison(self):
        model = build_classification_view_model([])

        self.assertEqual(model["selected_category"], BL_COMPARISON)
        self.assertEqual(model["selected_action"], "Process documents")
        self.assertIn("SI/BL match", model["pipeline_stages"])

    def test_missing_ai_key_emails_are_blocked(self):
        model = build_classification_view_model(
            [
                email("email_001", None, "missing_ai_key"),
                email("email_004", BL_COMPARISON),
            ]
        )

        self.assertEqual(model["needs_classification_count"], 1)
        self.assertEqual(model["needs_classification"][0]["email_id"], "email_001")
        self.assertEqual(model["counts"][BL_COMPARISON], 1)

    def test_bl_comparison_email_serializes_documents(self):
        model = build_classification_view_model(
            [
                email(
                    "email_004",
                    BL_COMPARISON,
                    documents=[
                        document("email_004_SI.txt", "SI"),
                        document("email_004_BL.txt", "BL"),
                    ],
                )
            ]
        )

        selected = model["selected_emails"][0]
        self.assertEqual(selected["email_id"], "email_004")
        self.assertEqual(selected["document_types"], "BL, SI")
        self.assertEqual(len(selected["documents"]), 2)


class FakeQuery:
    def __init__(self, emails):
        self.emails = emails

    def options(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return self.emails


class FakeSession:
    def __init__(self, emails):
        self.emails = emails

    def query(self, model):
        return FakeQuery(self.emails)


class ClassificationSummaryTests(unittest.TestCase):
    def test_summary_shape(self):
        summary = classification_summary(
            FakeSession(
                [
                    email("email_004", BL_COMPARISON),
                    email("email_009", INVOICE_QUERY),
                    email("email_010", None, "missing_ai_key"),
                ]
            )
        )

        self.assertEqual(summary["counts"][BL_COMPARISON], 1)
        self.assertEqual(summary["counts"][INVOICE_QUERY], 1)
        self.assertEqual(summary["needs_classification_count"], 1)
        self.assertEqual(summary["total_classified"], 2)
        self.assertEqual(summary["total_emails"], 3)


if __name__ == "__main__":
    unittest.main()
