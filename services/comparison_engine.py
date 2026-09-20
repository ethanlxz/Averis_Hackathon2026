from typing import Any

from services.field_normalizer import compare_ports, names_match

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

            if si_value in (None, "") or bl_value in (None, ""):
                missing.append(field)
                continue

            matched: bool
            if field in PARTY_FIELDS:
                matched = names_match(str(si_value), str(bl_value))
            elif field in PORT_FIELDS:
                port_result = compare_ports(str(si_value), str(bl_value))
                matched = port_result["match"]
                if port_result["needs_review"]:
                    review_details[field] = {
                        "si": si_value,
                        "bl": bl_value,
                        "reason": port_result["reason"],
                    }
            elif field == "container_count":
                matched = int(si_value) == int(bl_value)
            elif field == "gross_weight_kg":
                matched = abs(float(si_value) - float(bl_value)) <= GROSS_WEIGHT_TOLERANCE_KG
            else:
                matched = str(si_value).strip().casefold() == str(bl_value).strip().casefold()

            if not matched:
                mismatches.append(field)
                mismatch_details[field] = {"si": si_value, "bl": bl_value}

        if missing:
            status = "NEEDS_REVIEW"
            review_reason = "missing_value"
        elif mismatches:
            status = "MISMATCH"
            review_reason = None
        elif review_details:
            status = "NEEDS_REVIEW"
            review_reason = "port_code_mismatch"
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
