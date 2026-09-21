from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.document_parser import SNAKE_FIELDS, ShipmentFields, detect_document_class


@dataclass(frozen=True)
class ValidationResult:
    status: str
    detected_document_type: str | None
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "detected_document_type": self.detected_document_type,
            "errors": self.errors,
            "warnings": self.warnings,
        }


class DocumentValidator:
    """Flags wrong document types, unreadable files, and missing fields.

    Produces a structured result that the extraction service persists on each
    Extraction row so the UI and any downstream comparison step can react to
    bad inputs without throwing exceptions.
    """

    def validate(
        self,
        expected_type: str,
        text: str,
        fields: ShipmentFields,
    ) -> ValidationResult:
        detected = detect_document_class(text)
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        if not text.strip():
            errors.append(
                {
                    "code": "empty_text",
                    "detail": (
                        "No text could be extracted (scanned image, OCR not "
                        "available, or unreadable file)."
                    ),
                }
            )
        elif detected and detected != expected_type:
            if detected not in {"SI", "BL"}:
                errors.append(
                    {
                        "code": "wrong_document_type",
                        "detail": (
                            f"Expected {expected_type} but the content looks "
                            f"like {detected}."
                        ),
                        "expected": expected_type,
                        "detected": detected,
                    }
                )
            else:
                # SI vs BL titles are used interchangeably in shipping docs,
                # so a BL/SI cross-match is only a warning, not an error.
                warnings.append(
                    {
                        "code": "document_type_mismatch",
                        "detail": (
                            f"Expected {expected_type} but the content looks "
                            f"like {detected}."
                        ),
                        "expected": expected_type,
                        "detected": detected,
                    }
                )
            # When the document is the wrong kind, skip field-level checks.
        else:
            missing = fields.missing_fields()
            if missing:
                if len(missing) == len(SNAKE_FIELDS):
                    errors.append(
                        {
                            "code": "unrecognized_layout",
                            "detail": (
                                "Text was found but no shipment fields could "
                                "be matched."
                            ),
                        }
                    )
                else:
                    for snake in missing:
                        warnings.append(
                            {
                                "code": "missing_field",
                                "field": snake,
                                "detail": f"Field '{snake}' is missing.",
                            }
                        )

        if errors:
            status = "error"
        elif warnings:
            status = "warning"
        else:
            status = "ok"

        return ValidationResult(status, detected, errors, warnings)
