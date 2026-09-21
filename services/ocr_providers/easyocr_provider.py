from __future__ import annotations

import importlib.util
import io
from typing import Any


_reader: Any = None


def _easyocr_installed() -> bool:
    return importlib.util.find_spec("easyocr") is not None


class EasyOCRProvider:
    name = "easyocr"

    def __init__(self, language: str = "en") -> None:
        self.language = language

    def is_available(self) -> bool:
        return _easyocr_installed()

    def extract_text_from_bytes(self, data: bytes, kind: str = "") -> str:
        if not self.is_available():
            return ""

        normalized = str(kind or "").lower()
        if normalized.endswith(".pdf") or normalized == "pdf":
            return self.ocr_pdf(data)
        return self.ocr_image(data)

    def ocr_image(self, data: bytes) -> str:
        reader = self._get_reader()
        if reader is None:
            return ""

        try:
            import numpy as np
            from PIL import Image

            image = Image.open(io.BytesIO(data)).convert("RGB")
            array = np.asarray(image)
        except Exception:
            return ""

        return self._read(reader, array)

    def ocr_pdf(self, data: bytes) -> str:
        fitz = self._load_pymupdf()
        reader = self._get_reader()
        if fitz is None or reader is None:
            return ""

        try:
            import numpy as np
            from PIL import Image

            document = fitz.open(stream=data, filetype="pdf")
        except Exception:
            return ""

        parts: list[str] = []
        try:
            for page in document:
                pixmap = page.get_pixmap(dpi=300)
                image = self._pixmap_to_image(Image, pixmap)
                parts.append(self._read(reader, np.asarray(image)))
        except Exception:
            return ""
        finally:
            document.close()

        return "\n".join(parts)

    @staticmethod
    def _read(reader, array) -> str:
        try:
            results = reader.readtext(array, detail=1, paragraph=False)
        except Exception:
            return ""

        lines = []
        for result in results or []:
            if isinstance(result, (list, tuple)) and len(result) >= 2:
                lines.append(str(result[1]))
        return "\n".join(lines)

    def _get_reader(self):
        global _reader
        if _reader is not None:
            return _reader

        try:
            import easyocr

            _reader = easyocr.Reader([self.language], gpu=False, verbose=False)
            return _reader
        except Exception:
            return None

    @staticmethod
    def _load_pymupdf():
        try:
            import pymupdf

            return pymupdf
        except ImportError:
            pass
        try:
            import fitz

            return fitz
        except ImportError:
            return None

    @staticmethod
    def _pixmap_to_image(Image, pixmap):
        if pixmap.n == 4:
            mode = "RGBA"
        elif pixmap.n == 3:
            mode = "RGB"
        else:
            mode = "L"
        return Image.frombytes(
            mode, [pixmap.width, pixmap.height], pixmap.samples
        ).convert("RGB")

