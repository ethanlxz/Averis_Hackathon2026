from __future__ import annotations

from app.config import get_settings
from services.ocr_providers.easyocr_provider import EasyOCRProvider
from services.ocr_providers.openai_provider import OpenAIOCRProvider


class NoopOCRProvider:
    name = "none"

    def is_available(self) -> bool:
        return False

    def extract_text_from_bytes(self, data: bytes, kind: str = "") -> str:
        return ""


class OCRService:
    """OCR seam for scanned PDFs and standalone images.

    Routes to the provider selected by OCR_PROVIDER. Supported providers are
    "easyocr" and "openai". Falls back to an empty string when the selected
    provider is unavailable so the pipeline degrades gracefully.
    """

    def __init__(self, provider: object | None = None) -> None:
        self.settings = get_settings()
        self.provider = provider or self._build_provider()

    @property
    def provider_name(self) -> str:
        return getattr(self.provider, "name", "none")

    def is_available(self) -> bool:
        return bool(self.provider.is_available())

    def extract_text(self, file_path: str) -> str:
        try:
            with open(file_path, "rb") as handle:
                return self.extract_text_from_bytes(handle.read(), file_path)
        except OSError:
            return ""

    def extract_text_from_bytes(self, data: bytes, kind: str = "") -> str:
        """OCR raw bytes. ``kind`` may be a file path, extension, or "pdf"."""
        try:
            return self.provider.extract_text_from_bytes(data, kind)
        except Exception:
            return ""

    def _build_provider(self):
        provider = (self.settings.ocr_provider or "easyocr").strip().lower()
        if provider == "easyocr":
            return EasyOCRProvider(language=self.settings.ocr_lang)
        if provider == "openai":
            return OpenAIOCRProvider(
                api_key=self.settings.openai_api_key,
                model=self.settings.openai_ocr_model,
            )
        return NoopOCRProvider()
