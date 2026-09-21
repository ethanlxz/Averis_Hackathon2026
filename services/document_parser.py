from __future__ import annotations

import html
import io
import re
import zipfile
from pathlib import Path
from typing import Callable
from pydantic import BaseModel

from services.field_normalizer import (
    is_missing_value,
    normalize_whitespace_unicode,
    parse_container_count,
    parse_gross_weight_kg,
)


# snake_case key -> human display key used in the expected output.
DISPLAY_FIELDS = (
    ("shipper", "Shipper"),
    ("consignee", "Consignee"),
    ("notify_party", "Notify Party"),
    ("port_of_loading", "Port of Loading"),
    ("port_of_discharge", "Port of Discharge"),
    ("container_count", "Container Count"),
    ("gross_weight_kg", "Gross Weight (kg)"),
)

SNAKE_FIELDS = tuple(snake for snake, _ in DISPLAY_FIELDS)

FIELD_PATTERNS = {
    "shipper": re.compile(
        r"^\s*SHIPPER(?:\s*/\s*EXPORTER)?\s*:\s*(.+?)\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    "consignee": re.compile(
        r"^\s*CONSIGNEE(?:\s*\([^)\n]*\))?\s*:\s*(.+?)\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    "notify_party": re.compile(
        r"^\s*(?:NOTIFY(?:\s+PARTY)?)\s*:\s*(.+?)\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    "port_of_loading": re.compile(
        r"^\s*(?:PORT\s+OF\s+LOADING(?:\s*\(\s*POL\s*\))?|LOAD\s+PORT|POL)\s*:\s*(.+?)\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    "port_of_discharge": re.compile(
        r"^\s*(?:PORT\s+OF\s+DISCHARGE|DISCHARGE\s+PORT|POD)\s*:\s*(.+?)\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    "container_count": re.compile(
        r"^\s*(?:CONTAINER\s+COUNT|TOTAL\s+CONTAINERS?|NO\.?\s+OF\s+CONTAINERS?(?:\s+OR\s+PACKAGES)?)\s*:\s*(.+?)\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    "gross_weight_kg": re.compile(
        r"^\s*GROSS\s+(?:WT|WEIGHT)(?:\s*\(\s*(?:KGS?|KG)\s*\))?\s*:\s*(.+?)\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
}

TEXT_EXTENSIONS = {"txt", "text"}
DOCX_EXTENSIONS = {"docx"}
PDF_EXTENSIONS = {"pdf"}
XLSX_EXTENSIONS = {"xlsx", "xls", "xlsm"}
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"}


# snake_case key -> human display key used in the expected output.
DISPLAY_FIELDS = (
    ("shipper", "Shipper"),
    ("consignee", "Consignee"),
    ("notify_party", "Notify Party"),
    ("port_of_loading", "Port of Loading"),
    ("port_of_discharge", "Port of Discharge"),
    ("container_count", "Container Count"),
    ("gross_weight_kg", "Gross Weight (kg)"),
)

SNAKE_FIELDS = tuple(snake for snake, _ in DISPLAY_FIELDS)

# Label matchers for the seven shipment fields. The lookahead keeps a label
# from matching when it is only a prefix of a longer word (e.g. "POL" inside
# "POLARIS"). A value may follow the label on the same line, on a later line,
# with or without a colon, and with or without parenthetical notes.
FIELD_LABELS = {
    "shipper": re.compile(r"SHIPPER(?:\s*/\s*EXPORTER)?(?=$|[\s:(])", re.IGNORECASE),
    "consignee": re.compile(r"CONSIGNEE(?=$|[\s:(])", re.IGNORECASE),
    "notify_party": re.compile(r"NOTIFY(?:\s+PARTY)?(?=$|[\s:(])", re.IGNORECASE),
    "port_of_loading": re.compile(
        r"PORT\s+OF\s+LOADING|LOAD\s+PORT|POL(?=$|[\s:(])",
        re.IGNORECASE,
    ),
    "port_of_discharge": re.compile(
        r"PORT\s+OF\s+DISCHARGE|DISCHARGE\s+PORT|POD(?=$|[\s:(])",
        re.IGNORECASE,
    ),
    "container_count": re.compile(
        r"CONTAINER\s+COUNT|TOTAL\s+CONTAINERS?|"
        r"NO\.?\s+OF\s+CONTAINERS?(?:\s+OR\s+PACKAGES)?(?=$|[\s:(])",
        re.IGNORECASE,
    ),
    "gross_weight_kg": re.compile(
        r"(?:TOTAL\s+)?GROSS\s+(?:WT|WEIGHT)(?=$|[\s:(])",
        re.IGNORECASE,
    ),
}

TEXT_EXTENSIONS = {"txt", "text"}
DOCX_EXTENSIONS = {"docx"}
PDF_EXTENSIONS = {"pdf"}
XLSX_EXTENSIONS = {"xlsx", "xls", "xlsm"}
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"}


class ShipmentFields(BaseModel):
    shipper: str | None = None
    consignee: str | None = None
    notify_party: str | None = None
    port_of_loading: str | None = None
    port_of_discharge: str | None = None
    container_count: str | None = None
    gross_weight_kg: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {snake: getattr(self, snake) for snake in SNAKE_FIELDS}

    def to_display_dict(self) -> dict[str, str | None]:
        return {
            display: getattr(self, snake) for snake, display in DISPLAY_FIELDS
        }

    def missing_fields(self) -> list[str]:
        return [snake for snake in SNAKE_FIELDS if is_missing_value(getattr(self, snake))]

    def is_complete(self) -> bool:
        return not self.missing_fields()


def snake_to_display(fields: dict) -> dict:
    """Convert a snake_case field dict into the expected display-key output."""
    return {display: fields.get(snake) for snake, display in DISPLAY_FIELDS}


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    if is_missing_value(cleaned):
        return None
    return cleaned or None

# A line is a candidate "Label: value" pair only if it doesn't start with
# whitespace -- address/continuation lines in these documents are always
# indented and semicolon-delimited (no colon), so they never match.
_LABEL_LINE_RE = re.compile(r"^(\S[^:]*):\s*(.*)$")


def _canonical_field_for_label(label: str) -> str | None:
    text = label.strip().upper()

    if "NOTIFY" in text:
        return "notify_party"
    if "TO THE ORDER OF" in text:
        return "consignee"
    if "CONSIGNEE" in text:
        return "consignee"
    if "SHIPPER" in text:
        return "shipper"
    if "PORT OF LOADING" in text or "LOAD PORT" in text or text == "POL":
        return "port_of_loading"
    if "PORT OF DISCHARGE" in text or "DISCHARGE PORT" in text or text == "POD":
        return "port_of_discharge"
    if "CONTAINER" in text:
        return "container_count"
    if "GROSS WEIGHT" in text or "GROSS WT" in text:
        return "gross_weight_kg"
    return None


# Ordered content markers for detecting the *semantic* document class from the
# extracted text. Order matters: invoices are checked first because an invoice
# footer may literally say "NOT A SHIPPING INSTRUCTION". SI is checked before
# BL because "BILL OF LADING INSTRUCTION" is an SI document.
DOCUMENT_CLASS_MARKERS = (
    ("INVOICE", re.compile(r"(?:COMMERCIAL\s+)?INVOICE", re.IGNORECASE)),
    (
        "PACKING_LIST",
        re.compile(
            r"PACKING\s+LIST|CARTON\s+NO\.?|DIMENSIONS|PACKING\s+LIST\s+ONLY",
            re.IGNORECASE,
        ),
    ),
    (
        "CERTIFICATE_OF_ORIGIN",
        re.compile(
            r"CERTIFICATE\s+OF\s+ORIGIN|COUNTRY\s+OF\s+ORIGIN|ISSUING\s+AUTHORITY",
            re.IGNORECASE,
        ),
    ),
    (
        "SI",
        re.compile(
            r"SHIPPING\s+INSTRUCTION|BILL\s+OF\s+LADING\s+INSTRUCTION|B/L\s+INSTRUCTION",
            re.IGNORECASE,
        ),
    ),
    ("BL", re.compile(r"BILL\s+OF\s+LADING(?!\s+INSTRUCTION)", re.IGNORECASE)),
)


def detect_document_class(text: str | None) -> str | None:
    """Return the semantic document class detected from document text.

    Returns None when the class cannot be determined from the text.
    """
    if not text:
        return None
    for class_name, pattern in DOCUMENT_CLASS_MARKERS:
        if pattern.search(text):
            return class_name
    return None


class DocumentParser:
    """Detects document kind, extracts raw text, and parses shipment fields."""

    def __init__(
        self,
        reader: Callable[[str], bytes] | None = None,
        ocr_service: object | None = None,
    ) -> None:
        self._reader = reader
        self._ocr_service = ocr_service

    # -- document type detection ---------------------------------------
    def detect_kind(self, extension: str) -> str:
        ext = extension.lower().lstrip(".")
        if ext in TEXT_EXTENSIONS:
            return "txt"
        if ext in DOCX_EXTENSIONS:
            return "docx"
        if ext in PDF_EXTENSIONS:
            return "pdf"
        if ext in XLSX_EXTENSIONS:
            return "xlsx"
        if ext in IMAGE_EXTENSIONS:
            return "image"
        return "unknown"

    # -- raw text extraction -------------------------------------------
    def extract_text(
        self,
        path: str,
        bytes_data: bytes | None = None,
    ) -> tuple[str, str]:
        """Return (text, extraction_method) for the given attachment."""
        extension = Path(path).suffix
        kind = self.detect_kind(extension)

        if bytes_data is None and self._reader is not None:
            bytes_data = self._reader(path)
        if bytes_data is None:
            return "", "missing"

        if kind == "txt":
            return self._decode(bytes_data), "txt"
        if kind == "docx":
            text = self._extract_docx(bytes_data)
            return text, "docx"
        if kind == "pdf":
            text, method = self._extract_pdf(bytes_data)
            return text, method
        if kind == "xlsx":
            text = self._extract_xlsx(bytes_data)
            return text, "xlsx"
        if kind == "image":
            text = self._extract_image(bytes_data)
            return text, "ocr"
        return self._decode(bytes_data), "unknown"

      
    # -- field parsing --------------------------------------------------
    def parse_text(self, text: str) -> ShipmentFields:
        raw_values: dict[str, str] = {}
    
        if not text:
            return ShipmentFields()

        lines = [line.strip() for line in text.splitlines()]
        values: dict[str, str | None] = {}

        for snake, label_pattern in FIELD_LABELS.items():
            values[snake] = None
            for index, line in enumerate(lines):
                match = label_pattern.match(line)
                if not match:
                    continue

                value = self._value_from_rest(line[match.end():])
                if not value:
                    value = self._value_from_next_lines(
                        lines,
                        index + 1,
                        multiline=snake in {"shipper", "consignee", "notify_party"},
                    )
                if value:
                    values[snake] = value
                break  # first matching label wins

        for line in text.splitlines():
            match = _LABEL_LINE_RE.match(line)
            if not match:
                continue

            label, value = match.groups()
            value = value.strip()
            if not value:
                continue

            field = _canonical_field_for_label(label)
            if field and field not in raw_values:
                raw_values[field] = value

        fields: dict[str, str | None] = {}
        for field in ("shipper", "consignee", "notify_party", "port_of_loading", "port_of_discharge"):
            value = raw_values.get(field) or values.get(field)
            if value:
                fields[field] = normalize_whitespace_unicode(value)

        container_value = raw_values.get("container_count") or values.get("container_count")
        if container_value:
            count = parse_container_count(container_value)
            fields["container_count"] = None if count is None else str(count)

        weight_value = raw_values.get("gross_weight_kg") or values.get("gross_weight_kg")
        if weight_value:
            weight = parse_gross_weight_kg(weight_value)
            fields["gross_weight_kg"] = None if weight is None else str(weight)

        return ShipmentFields(**fields)

    @staticmethod
    def _value_from_rest(rest: str) -> str | None:
        """Extract the value that follows a label on the same line.

        Tolerates an optional colon and leading parenthetical notes such as
        "(Non-Negotiable)", "(POD)", or "(装货港)" that are part of the label
        decoration rather than the value itself.
        """
        rest = rest.strip()
        while True:
            changed = False
            stripped = re.sub(r"^\s*:\s*", "", rest)
            if stripped != rest:
                rest = stripped
                changed = True
            stripped = re.sub(r"^\s*\([^)]*\)\s*", "", rest)
            if stripped != rest:
                rest = stripped
                changed = True
            if not changed:
                break
        return _clean(rest) or None

    @staticmethod
    def _value_from_next_lines(
        lines: list[str],
        start: int,
        multiline: bool = False,
    ) -> str | None:
        """Take following line values for label-only layouts."""
        collected: list[str] = []
        for line in lines[start:]:
            if not line:
                if collected:
                    break
                continue
            if DocumentParser._looks_like_label(line):
                break
            if not multiline:
                return _clean(line)
            cleaned = _clean(line)
            if cleaned:
                collected.append(cleaned)

        if collected:
            return "; ".join(collected)
        return None

    @staticmethod
    def _looks_like_label(line: str) -> bool:
        return any(
            pattern.match(line) for pattern in FIELD_LABELS.values()
        )

    def merge_fields(
        self,
        base: ShipmentFields,
        extra: dict | None,
    ) -> ShipmentFields:
        """Fill missing base fields with values from an LLM-produced dict."""
        merged = base.to_dict()
        for snake in SNAKE_FIELDS:
            if merged.get(snake):
                continue
            if extra and extra.get(snake):
                merged[snake] = _clean(str(extra.get(snake)))
        return ShipmentFields(**merged)

    # -- helpers --------------------------------------------------------
    @staticmethod
    def _decode(data: bytes) -> str:
        for encoding in ("utf-8", "utf-16", "latin-1"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")

    @staticmethod
    def _extract_docx(data: bytes) -> str:
        """Extract text from a .docx using only the standard library."""
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                xml = archive.read("word/document.xml").decode(
                    "utf-8", errors="replace"
                )
        except (zipfile.BadZipFile, KeyError):
            return ""

        xml = re.sub(r"<w:p\b[^>]*>", "\n", xml)
        xml = re.sub(r"</w:p>", "\n", xml)
        xml = re.sub(r"<w:br\b[^>]*/>", "\n", xml)
        xml = re.sub(r"<w:cr\b[^>]*/>", "\n", xml)
        xml = re.sub(r"<w:tab\b[^>]*/>", "\t", xml)
        text = re.sub(r"<[^>]+>", "", xml)
        text = html.unescape(text)
        text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _extract_xlsx(data: bytes) -> str:
        """Dump spreadsheet rows as "label: value" lines (stdlib only).

        Handles the three OOXML string encodings: inline strings
        (`t="inlineStr"`), shared strings (`t="s"`), and plain numeric
        values. Label cells (first column) and value cells (subsequent
        columns) are joined with ": " so the regular expression field
        extractor can find them.
        """
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            return ""

        shared: list[str] = []
        try:
            shared_xml = archive.read("xl/sharedStrings.xml").decode(
                "utf-8", errors="replace"
            )
            shared = re.findall(r"<t[^>]*>(.*?)</t>", shared_xml, re.DOTALL)
        except KeyError:
            pass

        sheet_names = sorted(
            name
            for name in archive.namelist()
            if re.match(r"xl/worksheets/sheet\d+\.xml$", name)
        )
        if not sheet_names:
            return ""

        sheet_xml = archive.read(sheet_names[0]).decode("utf-8", errors="replace")

        lines: list[str] = []
        for row_match in re.finditer(r"<row[^>]*>(.*?)</row>", sheet_xml, re.DOTALL):
            cells: list[tuple[str, str]] = []
            for cell_match in re.finditer(
                r"<c\b([^>]*)>(.*?)</c>",
                row_match.group(1),
                re.DOTALL,
            ):
                attrs = cell_match.group(1)
                content = cell_match.group(2)
                ref_match = re.search(r'\br="([A-Z]+)(\d+)"', attrs)
                type_match = re.search(r'\bt="([^"]+)"', attrs)
                cell_type = type_match.group(1) if type_match else "n"

                value = ""
                if cell_type == "inlineStr":
                    text_match = re.search(r"<t[^>]*>(.*?)</t>", content, re.DOTALL)
                    if text_match:
                        value = text_match.group(1)
                elif cell_type == "s":
                    num_match = re.search(r"<v[^>]*>(.*?)</v>", content, re.DOTALL)
                    if num_match:
                        try:
                            value = shared[int(num_match.group(1))]
                        except (ValueError, IndexError):
                            value = num_match.group(1)
                else:
                    num_match = re.search(r"<v[^>]*>(.*?)</v>", content, re.DOTALL)
                    if num_match:
                        value = num_match.group(1)

                if ref_match and value.strip():
                    cells.append((ref_match.group(1), value))

            if not cells:
                continue

            cells.sort(key=lambda cell: (len(cell[0]), cell[0]))
            values = [html.unescape(cell[1]).strip() for cell in cells]
            if len(values) >= 2:
                lines.append(f"{values[0]}: {' | '.join(values[1:])}")
            else:
                lines.append(values[0])

        return "\n".join(lines)

    def _extract_pdf(self, data: bytes) -> tuple[str, str]:
        # pdfplumber -> pypdf -> PyMuPDF, then OCR as a last resort.
        for extractor in ("pdfplumber", "pypdf", "fitz"):
            text = self._pdf_with_library(extractor, data)
            if text:
                return text, "pdf_text"

        if self._ocr_service is not None:
            ocr_text = self._ocr_service.extract_text_from_bytes(data, "pdf")
            if ocr_text:
                return ocr_text, "pdf_ocr"
        return "", "pdf_text"

    @staticmethod
    def _pdf_with_library(library: str, data: bytes) -> str:
        try:
            if library == "pdfplumber":
                import pdfplumber

                with pdfplumber.open(io.BytesIO(data)) as pdf:
                    return "\n".join(
                        page.extract_text() or "" for page in pdf.pages
                    )
            if library == "pypdf":
                from pypdf import PdfReader

                reader = PdfReader(io.BytesIO(data))
                return "\n".join(
                    page.extract_text() or "" for page in reader.pages
                )
            if library == "fitz":
                try:
                    import pymupdf as fitz
                except ImportError:
                    import fitz

                with fitz.open(stream=data, filetype="pdf") as doc:
                    return "\n".join(page.get_text() for page in doc)
        except Exception:
            return ""
        return ""

    def _extract_image(self, data: bytes) -> str:
        if self._ocr_service is None:
            return ""
        return self._ocr_service.extract_text_from_bytes(data, "image")
