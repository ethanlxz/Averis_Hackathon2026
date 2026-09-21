import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import get_settings
from services.classification_schema import (
    ALLOWED_CATEGORIES,
    ClassificationResult,
    normalize_category,
)


class LLMService:
    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.deepseek_api_key)

    def classify_email(
        self,
        subject: str,
        body: str,
        attachments: list[str] | None = None,
    ) -> ClassificationResult | None:
        if not self.settings.deepseek_api_key:
            return None

        prompt = self._classification_prompt(subject, body, attachments or [])
        content = self._complete(
            "You classify shipping-document emails. Return strict JSON "
            "only and never include markdown.",
            prompt,
        )
        if content is None:
            return None

        try:
            result_payload = json.loads(content)
        except json.JSONDecodeError:
            return None

        category = normalize_category(result_payload.get("category"))
        if category is None:
            return None

        confidence = result_payload.get("confidence", 0.0)
        try:
            confidence_float = float(confidence)
        except (TypeError, ValueError):
            confidence_float = 0.0

        return ClassificationResult(
            category=category,
            confidence=max(0.0, min(confidence_float, 1.0)),
            source="deepseek",
            reason=result_payload.get("reason"),
        )

    def extract_shipment_fields(self, text: str) -> dict[str, str] | None:
        """Ask the LLM to extract structured shipment fields from raw text."""
        if not self.settings.deepseek_api_key:
            return None

        content = self._complete(
            "You extract shipping-document fields. Return strict JSON only "
            "and never include markdown.",
            self._fields_prompt(text),
        )
        if content is None:
            return None

        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return None

        if not isinstance(payload, dict):
            return None

        allowed = {
            "shipper",
            "consignee",
            "notify_party",
            "port_of_loading",
            "port_of_discharge",
            "container_count",
            "gross_weight_kg",
        }
        return {
            key: str(value).strip()
            for key, value in payload.items()
            if key in allowed and value not in (None, "")
        }

    def _complete(self, system: str, user_prompt: str) -> str | None:
        payload = {
            "model": self.settings.deepseek_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
        }

        base_url = self.settings.deepseek_base_url.rstrip("/")
        request = Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.deepseek_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(
                request,
                timeout=self.settings.deepseek_timeout_seconds,
            ) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            return None

        return self._extract_message_content(response_payload)

    def _classification_prompt(
        self,
        subject: str,
        body: str,
        attachments: list[str],
    ) -> str:
        categories = ", ".join(ALLOWED_CATEGORIES)
        attachment_lines = "\n".join(f"- {attachment}" for attachment in attachments)
        return (
            "Classify this email into exactly one category.\n"
            f"Allowed categories: {categories}\n\n"
            "Category meanings:\n"
            "- BL_COMPARISON: asks to compare/check a Shipping Instruction and "
            "draft Bill of Lading. Use this when the email asks to compare SI "
            "against draft BL, check BL against SI, verify BL matches SI, or "
            "find/revert discrepancies. Missing or dropped attachments do not "
            "change a comparison-intent email to GENERAL.\n"
            "- SI_REQUEST: asks for or sends a Shipping Instruction without a BL "
            "comparison task.\n"
            "- INVOICE_QUERY: invoice, billing, payment, or commercial query.\n"
            "- GENERAL: normal shipping-related message that does not fit above, "
            "including requests to send/revert a draft BL without asking to "
            "compare it against the SI.\n"
            "- SPAM: unsolicited or irrelevant spam.\n\n"
            "Examples:\n"
            "- 'Please assist to send the draft BL for PSGSE9638346 for "
            "checking asap.' with no attachments => GENERAL.\n"
            "- Shipping instruction details followed by 'Please revert with "
            "draft BL once available.' => GENERAL.\n"
            "- 'Please compare the SI and draft BL and confirm (attachments "
            "appear to have been dropped).' with no attachments => "
            "BL_COMPARISON.\n\n"
            'Return JSON shaped like {"category":"BL_COMPARISON",'
            '"confidence":0.92,"reason":"short reason"}.\n\n'
            f"Subject:\n{subject}\n\n"
            f"Body:\n{body}\n\n"
            f"Attachments:\n{attachment_lines or '- none'}"
        )

    def _fields_prompt(self, text: str) -> str:
        return (
            "Extract the following shipment fields from the document text.\n"
            "Return a single JSON object with exactly these keys. Use null for "
            "any field that is not present. Preserve the original casing and "
            "formatting of values (for example keep '1 x 40\\'HC' and "
            "'21,577 KG' as they appear).\n\n"
            "Keys:\n"
            '{"shipper": null, "consignee": null, "notify_party": null, '
            '"port_of_loading": null, "port_of_discharge": null, '
            '"container_count": null, "gross_weight_kg": null}\n\n'
            f"Document text:\n{text}"
        )

    def _extract_message_content(self, response_payload: dict) -> str | None:
        choices = response_payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return None

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            return None

        message = first_choice.get("message")
        if not isinstance(message, dict):
            return None

        content = message.get("content")
        return content if isinstance(content, str) else None
