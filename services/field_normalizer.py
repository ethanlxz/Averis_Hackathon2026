"""Text normalization for the seven SI/BL comparison fields.

Party names (shipper/consignee/notify_party) and ports (loading/discharge)
are extracted as raw strings by DocumentParser and normalized here at
compare-time, so the report can still display the original text side by
side. Container count and gross weight are numeric fields on
`ShipmentFields`, so their parsing happens once, at extraction time, via
`parse_container_count` / `parse_gross_weight_kg`.
"""

from __future__ import annotations

import difflib
import re
import unicodedata

NAME_MATCH_THRESHOLD = 0.90

_LEGAL_SUFFIX_SYNONYMS = {
    "LIMITED": "LTD",
    "CORPORATION": "CORP",
    "COMPANY": "CO",
    "INCORPORATED": "INC",
}

_SUFFIX_PAREN_TOKENS = {"LLC", "INC", "LTD", "CORP", "CO", "LLP", "GMBH", "FZE"}
_TRAILING_SUFFIX_PAREN_RE = re.compile(r"\(([A-Z]{2,5})\)\s*$")

_COUNTRY_ABBREVIATIONS = {
    "US": "UNITED STATES",
    "USA": "UNITED STATES",
    "UK": "UNITED KINGDOM",
    "UAE": "UNITED ARAB EMIRATES",
}

# Curated from ports observed in the sample SI/BL attachments. Extend as
# more documents are reviewed; an unknown code is simply skipped (no
# false "needs review" is raised for codes outside this table).
LOCODE_LOOKUP: dict[str, tuple[str, str]] = {
    "MYPKG": ("PORT KLANG", "MALAYSIA"),
    "PECLL": ("CALLAO", "PERU"),
    "KEMBA": ("MOMBASA", "KENYA"),
    "VNSGN": ("HO CHI MINH CITY", "VIETNAM"),
    "NGAPP": ("APAPA", "NIGERIA"),
    "MMRGN": ("YANGON", "MYANMAR"),
    "INNSA": ("NHAVA SHEVA", "INDIA"),
    "USSAV": ("SAVANNAH", "UNITED STATES"),
    "CNSHA": ("SHANGHAI", "CHINA"),
    "AUFRE": ("FREMANTLE", "AUSTRALIA"),
}

_LOCODE_RE = re.compile(r"\(([A-Z]{2}[A-Z0-9]{3})\)\s*$")
_PAREN_RE = re.compile(r"\s*\([^)]*\)")
_CONTAINER_COMPOUND_RE = re.compile(r"(\d+)\s*[xX]\s*\d+'?\s*[A-Za-z\-]+")
_CONTAINER_PAREN_RE = re.compile(r"\((\d+)\)")
_CONTAINER_LEADING_INT_RE = re.compile(r"^\s*(\d+)\b")
_WEIGHT_NUMBER_RE = re.compile(r"[\d,]+(?:\.\d+)?")
_LB_UNIT_RE = re.compile(r"\bLBS?\b|\bPOUNDS?\b", re.IGNORECASE)
LB_TO_KG = 0.453592


def normalize_whitespace_unicode(text: str) -> str:
    """Unicode-normalize (NFKC) and collapse whitespace/newlines."""
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


# --- Party names (shipper / consignee / notify party) -----------------

def normalize_party_name(raw: str) -> str:
    text = normalize_whitespace_unicode(raw).upper()
    text = text.replace(".", "").replace(",", "")
    text = re.sub(r"\s+", " ", text).strip()

    match = _TRAILING_SUFFIX_PAREN_RE.search(text)
    if match and match.group(1) in _SUFFIX_PAREN_TOKENS:
        text = text[: match.start()].strip() + " " + match.group(1)

    tokens = [_LEGAL_SUFFIX_SYNONYMS.get(tok, tok) for tok in text.split(" ")]
    return " ".join(tokens).strip()


def names_match(si_raw: str, bl_raw: str, threshold: float = NAME_MATCH_THRESHOLD) -> bool:
    a = normalize_party_name(si_raw)
    b = normalize_party_name(bl_raw)
    if not a or not b:
        return a == b
    if a == b:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= threshold


# --- Ports (loading / discharge) ---------------------------------------

def parse_port(raw: str) -> dict:
    text = normalize_whitespace_unicode(raw).upper()

    locode = None
    match = _LOCODE_RE.search(text)
    if match:
        locode = match.group(1)
        text = text[: match.start()].strip().rstrip(",").strip()

    if "," in text:
        city_part, _, country_part = text.rpartition(",")
    else:
        city_part, country_part = text, ""

    city_part = _PAREN_RE.sub("", city_part).strip()
    cities = [c.strip() for c in city_part.split("/") if c.strip()] or [city_part]
    city = cities[0]

    country = country_part.strip()
    country = _COUNTRY_ABBREVIATIONS.get(country, country)

    return {"locode": locode, "city": city, "cities": cities, "country": country}


def _locode_city_consistent(parsed: dict) -> bool | None:
    locode = parsed["locode"]
    if not locode or locode not in LOCODE_LOOKUP:
        return None
    expected_city, _expected_country = LOCODE_LOOKUP[locode]
    candidates = parsed["cities"] or [parsed["city"]]
    for city in candidates:
        if difflib.SequenceMatcher(None, city, expected_city).ratio() >= 0.6:
            return True
    return False


def compare_ports(si_raw: str, bl_raw: str) -> dict:
    si = parse_port(si_raw)
    bl = parse_port(bl_raw)

    si_consistent = _locode_city_consistent(si)
    bl_consistent = _locode_city_consistent(bl)
    needs_review = si_consistent is False or bl_consistent is False

    if si["locode"] and bl["locode"]:
        match = si["locode"] == bl["locode"]
    else:
        match = bool(si["city"]) and set(si["cities"]) & set(bl["cities"]) and si["country"] == bl["country"]

    return {
        "match": bool(match),
        "needs_review": needs_review,
        "reason": "locode_city_mismatch" if needs_review else None,
    }


def normalize_port_value(raw: str) -> str:
    """Collapse a port string down to its canonical comparison value.

    The LOCODE is the stable identifier across label/format variance, so
    it's preferred whenever present; otherwise fall back to normalized
    "CITY, COUNTRY" text.
    """
    parsed = parse_port(raw)
    if parsed["locode"]:
        return parsed["locode"]
    if parsed["country"]:
        return f"{parsed['city']}, {parsed['country']}"
    return parsed["city"]


# --- Container count -----------------------------------------------------

def parse_container_count(raw: str) -> int | None:
    text = normalize_whitespace_unicode(raw)

    compound_matches = _CONTAINER_COMPOUND_RE.findall(text)
    if compound_matches:
        return sum(int(n) for n in compound_matches)

    paren_match = _CONTAINER_PAREN_RE.search(text)
    if paren_match:
        return int(paren_match.group(1))

    leading_match = _CONTAINER_LEADING_INT_RE.match(text)
    if leading_match:
        return int(leading_match.group(1))

    return None


# --- Gross weight (kg) ----------------------------------------------------

def parse_gross_weight_kg(raw: str) -> float | None:
    text = normalize_whitespace_unicode(raw)

    number_match = _WEIGHT_NUMBER_RE.search(text)
    if not number_match:
        return None

    value = float(number_match.group(0).replace(",", ""))
    if _LB_UNIT_RE.search(text):
        value *= LB_TO_KG
    return value


# --- Structured JSON input (field already identified by its key) --------

_PARTY_JSON_KEYS = {"Shipper", "Consignee", "Notify Party"}
_PORT_JSON_KEYS = {"Port of Loading", "Port of Discharge"}


def normalize_shipment_json(data: dict[str, str | None]) -> dict[str, str]:
    """Normalize a shipment-fields dict keyed by canonical field name.

    Unlike DocumentParser (which must recognize label variants in raw
    attachment text, e.g. "To the Order of" for Consignee or "Notify:"
    for Notify Party), this assumes the field is already identified by
    its JSON key -- no label/alias recognition is needed here. Every
    output value is a string, matching the shape of the input.
    """
    normalized: dict[str, str] = {}

    for key, raw in data.items():
        raw_text = "" if raw is None else str(raw)

        if key in _PARTY_JSON_KEYS:
            normalized[key] = normalize_party_name(raw_text)
        elif key in _PORT_JSON_KEYS:
            normalized[key] = normalize_port_value(raw_text)
        elif key == "Container Count":
            count = parse_container_count(raw_text)
            normalized[key] = "" if count is None else str(count)
        elif key == "Gross Weight (kg)":
            weight = parse_gross_weight_kg(raw_text)
            normalized[key] = "" if weight is None else str(weight)
        else:
            normalized[key] = normalize_whitespace_unicode(raw_text)

    return normalized
