from __future__ import annotations

import base64
from typing import Any


class OpenAIOCRProvider:
    name = "openai"

    def __init__(
        self,
        api_key: str | None,
        model: str = "gpt-5.5",
        client: Any | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.client = client

    def is_available(self) -> bool:
        if not self.api_key and self.client is None:
            return False
        return self._client() is not None

    def extract_text_from_bytes(self, data: bytes, kind: str = "") -> str:
        if not self.is_available():
            return ""

        normalized = str(kind or "").lower()
        if normalized.endswith(".pdf") or normalized == "pdf":
            return self.ocr_pdf(data)
        return self.ocr_image(data)

    def ocr_pdf(self, data: bytes) -> str:
        pages = self._render_pdf_pages(data)
        if not pages:
            return ""

        parts = []
        for index, page_bytes in enumerate(pages, start=1):
            text = self.ocr_image(page_bytes)
            if text:
                parts.append(f"--- Page {index} ---\n{text}")
        return "\n\n".join(parts)

    def ocr_image(self, data: bytes) -> str:
        client = self._client()
        if client is None:
            return ""

        image_url = f"data:image/png;base64,{base64.b64encode(data).decode('ascii')}"
        try:
            response = client.responses.create(
                model=self.model,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    "Extract all visible text from this shipping "
                                    "document image. Preserve labels and line "
                                    "breaks. Return plain text only."
                                ),
                            },
                            {
                                "type": "input_image",
                                "image_url": image_url,
                                "detail": "high",
                            },
                        ],
                    }
                ],
            )
        except Exception:
            return ""

        return self._response_text(response)

    def _client(self):
        if self.client is not None:
            return self.client
        if not self.api_key:
            return None
        try:
            from openai import OpenAI

            self.client = OpenAI(api_key=self.api_key)
            return self.client
        except Exception:
            return None

    @staticmethod
    def _response_text(response: Any) -> str:
        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str):
            return output_text.strip()

        if isinstance(response, dict):
            output_text = response.get("output_text")
            if isinstance(output_text, str):
                return output_text.strip()
        return ""

    @staticmethod
    def _render_pdf_pages(data: bytes) -> list[bytes]:
        try:
            import pymupdf as fitz
        except ImportError:
            try:
                import fitz
            except ImportError:
                return []

        try:
            document = fitz.open(stream=data, filetype="pdf")
        except Exception:
            return []

        pages: list[bytes] = []
        try:
            for page in document:
                pixmap = page.get_pixmap(dpi=200)
                pages.append(pixmap.tobytes("png"))
        except Exception:
            return []
        finally:
            document.close()

        return pages

