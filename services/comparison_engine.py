from typing import Any

from services.field_normalizer import (
    compare_ports,
    is_missing_value,
    names_match,
    parse_container_count,
    parse_gross_weight_kg,
)

COMPARISON_FIELDS = (
    "shipper",
    "consignee",
    "notify_party",
    "port_of_loading",
    "port_of_discharge",
    "container_count",
    "gross_weight_kg",
)

PARTY_FIELDS = {"shipper", "consignee", "notify_party"}
PORT_FIELDS = {"port_of_loading", "port_of_discharge"}
GROSS_WEIGHT_TOLERANCE_KG = 1.0


class ComparisonEngine:
    def compare(self, si_data: dict[str, Any], bl_data: dict[str, Any]) -> dict[str, Any]:
        mismatches = []
        missing = []
        mismatch_details: dict[str, dict[str, Any]] = {}
        review_details: dict[str, dict[str, Any]] = {}

        for field in COMPARISON_FIELDS:
            si_value = si_data.get(field)
            bl_value = bl_data.get(field)

            if is_missing_value(si_value) or is_missing_value(bl_value):
                missing.append(field)
                continue

            matched: bool
            if field in PARTY_FIELDS:
                matched = names_match(str(si_value), str(bl_value))
            elif field in PORT_FIELDS:
                port_result = compare_ports(str(si_value), str(bl_value))
                matched = port_result["match"]
                if port_result["needs_review"]:
                    matched = False
                    review_details[field] = {
                        "si": si_value,
                        "bl": bl_value,
                        "reason": port_result["reason"],
                    }
            elif field == "container_count":
                si_count = parse_container_count(str(si_value))
                bl_count = parse_container_count(str(bl_value))
                if si_count is None or bl_count is None:
                    missing.append(field)
                    continue
                matched = si_count == bl_count
            elif field == "gross_weight_kg":
                si_weight = parse_gross_weight_kg(str(si_value))
                bl_weight = parse_gross_weight_kg(str(bl_value))
                if si_weight is None or bl_weight is None:
                    missing.append(field)
                    continue
                matched = abs(si_weight - bl_weight) <= GROSS_WEIGHT_TOLERANCE_KG
            else:
                matched = str(si_value).strip().casefold() == str(bl_value).strip().casefold()

            if not matched:
                mismatches.append(field)
                mismatch_details[field] = {"si": si_value, "bl": bl_value}
                if field in review_details:
                    mismatch_details[field]["reason"] = review_details[field]["reason"]

        if missing:
            status = "NEEDS_REVIEW"
            review_reason = "missing_value"
        elif mismatches:
            status = "MISMATCH"
            review_reason = None
        else:
            status = "OK"
            review_reason = None

        return {
            "status": status,
            "has_defect": bool(mismatches),
            "defect_fields": mismatches,
            "mismatch_details": mismatch_details,
            "review_reason": review_reason,
            "missing_fields": missing,
            "review_details": review_details,
        }
