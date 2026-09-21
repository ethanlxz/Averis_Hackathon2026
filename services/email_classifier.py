from services.classification_schema import (
    BL_COMPARISON,
    GENERAL,
    INVOICE_QUERY,
    SI_REQUEST,
    SPAM,
    ClassificationResult,
)
from services.llm_service import LLMService


COMPARISON_PHRASES = (
    "compare the si and bl",
    "compare si and bl",
    "compare the si and draft bl",
    "compare si and draft bl",
    "compare the shipping instruction and bl",
    "compare shipping instruction and bl",
    "compare the shipping instruction and draft bl",
    "compare shipping instruction and draft bl",
    "check the si and bl",
    "check si and bl",
    "check the draft bl against the si",
    "check draft bl against the si",
    "check the bl against the si",
    "check bl against the si",
    "verify the bl matches the si",
    "verify bl matches si",
    "confirm the bl matches the si",
    "confirm bl matches si",
    "bl matches the si",
    "bl match the si",
    "revert with any discrepancy",
)

DRAFT_BL_REQUEST_PHRASES = (
    "assist to send the draft bl",
    "please send the draft bl",
    "send the draft bl",
    "revert with draft bl once available",
    "please revert with draft bl",
)

INVOICE_QUERY_PHRASES = (
    "invoice query",
    "invoice status",
    "check invoice",
    "confirm invoice",
    "commercial query",
    "billing",
    "payment",
)


class EmailClassifier:
    def __init__(
        self,
        llm_service: LLMService | None = None,
        prefer_llm: bool = True,
    ) -> None:
        self.llm_service = llm_service or LLMService()
        self.prefer_llm = prefer_llm

    def classify(
        self,
        subject: str,
        body: str,
        attachments: list[str] | None = None,
    ) -> ClassificationResult:
        rule_result = self.classify_with_rules(subject, body, attachments)

        if not self.prefer_llm:
            return rule_result

        if not self.llm_service.is_configured:
            return ClassificationResult(
                category=None,
                confidence=0.0,
                source="missing_ai_key",
                reason="AI key not included",
            )

        llm_result = self.llm_service.classify_email(subject, body, attachments or [])
        if llm_result is not None:
            return llm_result

        return ClassificationResult(
            category=rule_result.category,
            confidence=rule_result.confidence,
            source="rules_fallback",
            reason=rule_result.reason or "deepseek_unavailable",
        )

    def classify_with_rules(
        self,
        subject: str,
        body: str,
        attachments: list[str] | None = None,
    ) -> ClassificationResult:
        attachments = [str(attachment) for attachment in attachments or []]
        haystack = f"{subject}\n{body}".casefold()
        attachment_text = " ".join(attachments).casefold()

        has_si_attachment = "_si" in attachment_text or " si." in attachment_text
        has_bl_attachment = "_bl" in attachment_text or " bl." in attachment_text
        has_si_text = (
            "shipping instruction" in haystack
            or " si " in f" {haystack} "
            or " si/" in haystack
        )
        has_bl_text = (
            "bill of lading" in haystack
            or "draft bl" in haystack
        )
        has_si = has_si_text or has_si_attachment
        has_bl = has_bl_text or has_bl_attachment
        asks_for_comparison = any(
            phrase in haystack for phrase in COMPARISON_PHRASES
        ) or (
            "discrepancy" in haystack
            and has_si
            and has_bl
        )
        asks_for_draft_bl_only = any(
            phrase in haystack for phrase in DRAFT_BL_REQUEST_PHRASES
        )

        if "spam" in haystack or "lottery" in haystack:
            return ClassificationResult(SPAM, 0.93, "rules", "spam_keyword")
        if any(phrase in haystack for phrase in INVOICE_QUERY_PHRASES):
            return ClassificationResult(
                INVOICE_QUERY,
                0.90,
                "rules",
                "invoice_keyword",
            )
        if asks_for_comparison:
            return ClassificationResult(
                BL_COMPARISON,
                0.92,
                "rules",
                "comparison_intent",
            )
        if has_si_attachment and has_bl_attachment:
            return ClassificationResult(
                BL_COMPARISON,
                0.92,
                "rules",
                "si_and_bl_attachments",
            )
        if asks_for_draft_bl_only:
            return ClassificationResult(
                GENERAL,
                0.78,
                "rules",
                "draft_bl_request_without_comparison",
            )
        if has_si_attachment or (has_si_text and not has_bl):
            return ClassificationResult(SI_REQUEST, 0.85, "rules", "si_evidence")
        if has_bl_attachment:
            return ClassificationResult(
                BL_COMPARISON,
                0.78,
                "rules",
                "bl_attachment",
            )
        return ClassificationResult(GENERAL, 0.60, "rules", "no_specific_evidence")
