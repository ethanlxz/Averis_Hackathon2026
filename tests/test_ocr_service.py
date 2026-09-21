import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.config import get_settings
from services.ocr_providers.easyocr_provider import EasyOCRProvider
from services.ocr_providers.openai_provider import OpenAIOCRProvider
from services.ocr_service import NoopOCRProvider, OCRService


class OCRServiceProviderSelectionTests(unittest.TestCase):
    def tearDown(self):
        get_settings.cache_clear()

    def _service_with_env(self, provider: str) -> OCRService:
        get_settings.cache_clear()
        with patch.dict("os.environ", {"OCR_PROVIDER": provider}, clear=False):
            get_settings.cache_clear()
            return OCRService()

    def test_easyocr_provider_is_selected_by_config(self):
        service = self._service_with_env("easyocr")

        self.assertIsInstance(service.provider, EasyOCRProvider)
        self.assertEqual(service.provider_name, "easyocr")

    def test_openai_provider_is_selected_by_config(self):
        service = self._service_with_env("openai")

        self.assertIsInstance(service.provider, OpenAIOCRProvider)
        self.assertEqual(service.provider_name, "openai")

    def test_unknown_provider_uses_noop_provider(self):
        service = self._service_with_env("unknown")

        self.assertIsInstance(service.provider, NoopOCRProvider)
        self.assertFalse(service.is_available())
        self.assertEqual(service.extract_text_from_bytes(b"anything", "pdf"), "")


class FakeResponses:
    def __init__(self, outputs=None, raises: Exception | None = None):
        self.outputs = list(outputs or ["OCR TEXT"])
        self.raises = raises
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise self.raises
        return SimpleNamespace(output_text=self.outputs.pop(0))


class FakeClient:
    def __init__(self, outputs=None, raises: Exception | None = None):
        self.responses = FakeResponses(outputs, raises)


class OpenAIOCRProviderTests(unittest.TestCase):
    def test_image_bytes_are_sent_as_base64_input_image(self):
        client = FakeClient(["VISIBLE TEXT"])
        provider = OpenAIOCRProvider(api_key=None, client=client)

        text = provider.ocr_image(b"image-bytes")

        self.assertEqual(text, "VISIBLE TEXT")
        call = client.responses.calls[0]
        content = call["input"][0]["content"]
        image = content[1]
        self.assertEqual(image["type"], "input_image")
        self.assertTrue(image["image_url"].startswith("data:image/png;base64,"))

    def test_pdf_pages_are_joined_with_page_markers(self):
        class ProviderWithPages(OpenAIOCRProvider):
            @staticmethod
            def _render_pdf_pages(data: bytes) -> list[bytes]:
                return [b"page-one", b"page-two"]

        client = FakeClient(["PAGE ONE TEXT", "PAGE TWO TEXT"])
        provider = ProviderWithPages(api_key=None, client=client)

        text = provider.ocr_pdf(b"pdf-bytes")

        self.assertIn("--- Page 1 ---\nPAGE ONE TEXT", text)
        self.assertIn("--- Page 2 ---\nPAGE TWO TEXT", text)
        self.assertEqual(len(client.responses.calls), 2)

    def test_api_failure_returns_empty_text(self):
        client = FakeClient(raises=RuntimeError("api failed"))
        provider = OpenAIOCRProvider(api_key=None, client=client)

        self.assertEqual(provider.ocr_image(b"image-bytes"), "")


if __name__ == "__main__":
    unittest.main()

