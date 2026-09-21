from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


DISPLAY_FIELDS = (
    ("shipper", "Shipper"),
    ("consignee", "Consignee"),
    ("notify_party", "Notify Party"),
    ("port_of_loading", "Port of Loading"),
    ("port_of_discharge", "Port of Discharge"),
    ("container_count", "Container Count"),
    ("gross_weight_kg", "Gross Weight (kg)"),
)

VERDICT_COLORS = {
    "MATCH": colors.HexColor("#16803c"),
    "MISMATCH": colors.HexColor("#c33434"),
    "REVIEW": colors.HexColor("#95620a"),
    "PENDING": colors.HexColor("#68686f"),
}

_MUTED = colors.HexColor("#68686f")
_HEADER_BG = colors.HexColor("#f0f0f2")
_GRID = colors.HexColor("#d9d9dc")
_MISMATCH_BG = colors.HexColor("#fdeaea")
_MISSING_BG = colors.HexColor("#fff7e6")


def _fmt(value: Any) -> str:
    if value in (None, ""):
        return "—"
    return str(value)


def _esc(value: Any) -> str:
    return escape(_fmt(value))


def generate_report(
    email_id: str,
    subject: str,
    sender: str,
    category: str,
    verification: dict[str, Any] | None,
    si_fields: dict[str, Any] | None,
    bl_fields: dict[str, Any] | None,
) -> bytes:
    """Build a simple, readable verification PDF and return its bytes."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Verification Report {email_id}",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleCustom", parent=styles["Title"], fontSize=20, spaceAfter=8
    )
    h2_style = ParagraphStyle(
        "H2Custom",
        parent=styles["Heading2"],
        fontSize=13,
        spaceBefore=14,
        spaceAfter=6,
    )
    body = styles["BodyText"]
    small = ParagraphStyle(
        "Small",
        parent=styles["BodyText"],
        fontSize=9,
        textColor=_MUTED,
    )

    story: list[Any] = []
    story.append(Paragraph("Averis Veritas Verification Report", title_style))
    story.append(Paragraph(f"Email: <b>{_esc(email_id)}</b>", body))
    story.append(Paragraph(f"Subject: {_esc(subject)}", body))
    story.append(Paragraph(f"Sender: {_esc(sender)}", body))
    story.append(Paragraph(f"Category: {_esc(category)}", body))
    story.append(Spacer(1, 10))

    verification = verification or {}
    result = verification.get("result", "PENDING")
    confidence = verification.get("confidence")
    conf_text = f"{confidence * 100:.0f}%" if confidence is not None else "—"
    reviewer = str(verification.get("reviewer_status") or "—").replace("_", " ").title()

    story.append(Paragraph("Decision", h2_style))
    decision_table = Table(
        [
            ["Verdict", "Confidence", "Review status"],
            [result, conf_text, reviewer],
        ],
        colWidths=[60 * mm, 40 * mm, 60 * mm],
    )
    decision_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 1), (0, 1), VERDICT_COLORS.get(result, colors.black)),
                ("FONTNAME", (0, 1), (0, 1), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, _GRID),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(decision_table)

    story.append(Paragraph("SI vs BL comparison", h2_style))
    defect_fields = set(verification.get("defect_fields") or [])
    missing_fields = set(verification.get("missing_fields") or [])
    rows = [["Field", "SI", "BL"]]
    for snake, label in DISPLAY_FIELDS:
        rows.append(
            [
                label,
                _fmt((si_fields or {}).get(label)),
                _fmt((bl_fields or {}).get(label)),
            ]
        )

    comparison_table = Table(rows, colWidths=[45 * mm, 65 * mm, 65 * mm], repeatRows=1)
    table_style = [
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, _GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    for index, (snake, _label) in enumerate(DISPLAY_FIELDS, start=1):
        if snake in defect_fields:
            table_style.append(("BACKGROUND", (0, index), (-1, index), _MISMATCH_BG))
        elif snake in missing_fields:
            table_style.append(("BACKGROUND", (0, index), (-1, index), _MISSING_BG))
    comparison_table.setStyle(TableStyle(table_style))
    story.append(comparison_table)

    review_reason = verification.get("review_reason")
    review_reason_label = verification.get("review_reason_label") or review_reason
    mismatch_details = verification.get("mismatch_details") or {}
    missing = verification.get("missing_fields") or []
    missing_labels = verification.get("missing_field_labels") or missing
    if review_reason or mismatch_details or missing:
        story.append(Paragraph("Notes", h2_style))
        if review_reason_label:
            story.append(Paragraph(f"Review reason: {_esc(review_reason_label)}", body))
        for field, detail in mismatch_details.items():
            if not isinstance(detail, dict):
                continue
            story.append(
                Paragraph(
                    f"<b>{_esc(field)}</b>: SI = {_esc(detail.get('si'))} · "
                    f"BL = {_esc(detail.get('bl'))}",
                    body,
                )
            )
        if missing:
            story.append(Paragraph(f"Missing fields: {_esc(', '.join(missing_labels))}", body))

    story.append(Spacer(1, 18))
    story.append(
        Paragraph(
            f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            small,
        )
    )
    verification_hash = verification.get("verification_hash")
    if verification_hash:
        story.append(Paragraph(f"Verification hash: {_esc(verification_hash[:16])}…", small))

    doc.build(story)
    return buffer.getvalue()
