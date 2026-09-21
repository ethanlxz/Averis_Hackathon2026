import unittest
from unittest.mock import patch

from routers import api as api_router
from services.classification_schema import (
    ALLOWED_CATEGORIES,
    BL_COMPARISON,
    GENERAL,
    INVOICE_QUERY,
    SI_REQUEST,
    SPAM,
)
from services.email_classifier import EmailClassifier


class FailingConfiguredLLM:
    is_configured = True

    def classify_email(self, subject, body, attachments):
        return None


class MissingLLM:
    is_configured = False

    def classify_email(self, subject, body, attachments):
        return None


class EmailClassifierTests(unittest.TestCase):
    def setUp(self):
        self.classifier = EmailClassifier(prefer_llm=False)

    def test_rule_classifier_covers_all_core_categories(self):
        cases = [
            ("Lottery winner", "This is spam", [], SPAM),
            ("Invoice query", "Please check payment status", [], INVOICE_QUERY),
            (
                "REQUEST BL DRAFT",
                "Attached are SI and draft BL. Please check.",
                ["attachments/email_004_SI.txt", "attachments/email_004_BL.txt"],
                BL_COMPARISON,
            ),
            (
                "Shipping instruction",
                "Please prepare shipping instruction.",
                ["attachments/email_001_SI.txt"],
                SI_REQUEST,
            ),
            ("Hello", "Thanks for the update.", [], GENERAL),
        ]

        for subject, body, attachments, expected in cases:
            with self.subTest(expected=expected):
                result = self.classifier.classify(subject, body, attachments)
                self.assertEqual(result.category, expected)
                self.assertEqual(result.source, "rules")
                self.assertIn(result.category, ALLOWED_CATEGORIES)

    def test_attachment_driven_classification(self):
        self.assertEqual(
            self.classifier.classify("", "", ["email_004_SI.txt", "email_004_BL.txt"]).category,
            BL_COMPARISON,
        )
        self.assertEqual(
            self.classifier.classify("", "", ["email_004_SI.txt"]).category,
            SI_REQUEST,
        )
        self.assertEqual(
            self.classifier.classify("", "", ["email_004_BL.txt"]).category,
            BL_COMPARISON,
        )

    def test_draft_bl_send_request_without_comparison_is_general(self):
        result = self.classifier.classify(
            "Draft BL MMSS 2507 V.257087E NHAVA SHEVA - amend BL 058",
            "Dear Mitchelle,\n\n"
            "Please assist to send the draft BL for PSGSE9638346 for checking asap.\n\n"
            "Thank you.",
            [],
        )

        self.assertEqual(result.category, GENERAL)
        self.assertEqual(result.reason, "draft_bl_request_without_comparison")

    def test_shipping_instruction_with_future_draft_bl_request_is_general(self):
        result = self.classifier.classify(
            "RE_ SI NEEDED_ 5APH-26773 _ UAB NOVAKOPA _ PO_25_2186 _ MERSIN",
            "Hi Ooi\n\n"
            "Please find Shipping instruction for 5APH-26773.\n\n"
            "POL: RUGAO/NANTONG/SHANGHAI, CHINA\n"
            "POD: MERSIN, TURKEY\n\n"
            "Documents Required:\n"
            "1) 3 Original invoice\n"
            "2) 3 Packing list\n"
            "3) 3 Original BL + 3 N/N\n"
            "Please revert with draft BL once available.",
            [],
        )

        self.assertEqual(result.category, GENERAL)
        self.assertEqual(result.reason, "draft_bl_request_without_comparison")

    def test_missing_attachments_do_not_hide_comparison_intent(self):
        result = self.classifier.classify(
            "TO CONFIRM DOCS",
            "Dear Team,\n\n"
            "Please compare the SI and draft BL for PSGSE8356691 and confirm "
            "(attachments appear to have been dropped). Thank you.",
            [],
        )

        self.assertEqual(result.category, BL_COMPARISON)
        self.assertEqual(result.reason, "comparison_intent")

    def test_check_draft_bl_against_si_with_attachments_is_comparison(self):
        result = self.classifier.classify(
            "Draft BL check",
            "Pls assist to check the draft BL against the SI for PO and revert "
            "with any discrepancy asap.",
            ["attachments/email_491_SI.txt", "attachments/email_491_BL.txt"],
        )

        self.assertEqual(result.category, BL_COMPARISON)
        self.assertEqual(result.reason, "comparison_intent")

    def test_configured_llm_failure_falls_back_to_rules(self):
        classifier = EmailClassifier(llm_service=FailingConfiguredLLM())
        result = classifier.classify(
            "REQUEST BL DRAFT",
            "Attached are SI and draft BL. Please check.",
            ["email_004_SI.txt", "email_004_BL.txt"],
        )

        self.assertEqual(result.category, BL_COMPARISON)
        self.assertEqual(result.source, "rules_fallback")

    def test_missing_ai_key_is_reported_explicitly(self):
        classifier = EmailClassifier(llm_service=MissingLLM())
        result = classifier.classify(
            "Invoice query",
            "Please confirm payment details.",
            [],
        )

        self.assertIsNone(result.category)
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.source, "missing_ai_key")
        self.assertEqual(result.reason, "AI key not included")


class ClassifyEmailApiHandlerTests(unittest.TestCase):
    def test_api_classify_email_returns_structured_result(self):
        with patch(
            "routers.api.EmailClassifier",
            return_value=EmailClassifier(llm_service=MissingLLM()),
        ):
            payload = api_router.classify_email(
                {
                    "subject": "Invoice query",
                    "body": "Please confirm payment details.",
                    "attachments": [],
                }
            )

        self.assertIsNone(payload["category"])
        self.assertIsInstance(payload["confidence"], float)
        self.assertEqual(payload["source"], "missing_ai_key")
        self.assertEqual(payload["reason"], "AI key not included")


if __name__ == "__main__":
    unittest.main()
