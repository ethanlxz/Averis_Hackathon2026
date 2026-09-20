import json
from typing import Any

from sqlalchemy.orm import Session, selectinload

from models.email_message import EmailMessage
from services.classification_schema import ALLOWED_CATEGORIES, BL_COMPARISON
from services.document_parser import snake_to_display


CATEGORY_LABELS = {
    "BL_COMPARISON": "BL Comparison",
    "SI_REQUEST": "SI Request",
    "INVOICE_QUERY": "Invoice Query",
    "GENERAL": "General",
    "SPAM": "Spam",
}

CATEGORY_ACTIONS = {
    "BL_COMPARISON": "Process documents",
    "SI_REQUEST": "Archive / prepare SI workflow",
    "INVOICE_QUERY": "Archive",
    "GENERAL": "Archive",
    "SPAM": "Archive",
}

PIPELINE_STAGES = (
    "Attachment Processing",
    "Document Type Detection",
    "Text/OCR Extraction",
    "Structured Shipment JSON",
    "SI/BL Comparison",
    "Human Review",
    "Report",
)

EXTRACTION_PIPELINE_STAGES = (
    "Attachment Processing",
    "Document Type Detection",
    "Text/OCR Extraction",
    "Structured Shipment JSON",
)


def build_pipeline_stages(email: EmailMessage) -> list[dict[str, Any]]:
    """Map a single email to the four extraction-pipeline stage statuses."""
    documents = getattr(email, "documents", None) or []
    extractions = getattr(email, "extractions", None) or []

    has_documents = bool(documents)
    has_types = bool(documents) and all(
        document.document_type and document.document_type != "UNKNOWN"
        for document in documents
    )
    methods = sorted(
        {
            extraction.extraction_method
            for extraction in extractions
            if extraction.extraction_method
        }
    )
    populated = [extraction for extraction in extractions if extraction.fields]
    has_extraction = bool(extractions)
    has_fields = bool(populated)

    return [
        {
            "key": "attachments",
            "name": EXTRACTION_PIPELINE_STAGES[0],
            "status": "Done" if has_documents else "Pending",
        },
        {
            "key": "detection",
            "name": EXTRACTION_PIPELINE_STAGES[1],
            "status": "Done" if has_types else "Pending",
        },
        {
            "key": "extraction",
            "name": EXTRACTION_PIPELINE_STAGES[2],
            "status": "Done" if has_extraction else "Pending",
            "detail": ", ".join(methods) if has_extraction else None,
        },
        {
            "key": "json",
            "name": EXTRACTION_PIPELINE_STAGES[3],
            "status": "Done" if has_fields else "Pending",
            "detail": (
                f"{len(populated)} record{'' if len(populated) == 1 else 's'}"
                if has_fields
                else None
            ),
        },
    ]

NEEDS_CLASSIFICATION_KEY = "NEEDS_CLASSIFICATION"


def _status_class(status: str | None) -> str | None:
    if status == "ok":
        return "success"
    if status == "error":
        return "danger"
    if status == "warning":
        return "warning"
    return None


def get_classification_view_model(
    db: Session,
    selected_category: str | None = None,
    search_query: str | None = None,
) -> dict[str, Any]:
    emails = (
        db.query(EmailMessage)
        .options(
            selectinload(EmailMessage.documents),
            selectinload(EmailMessage.extractions),
        )
        .order_by(EmailMessage.email_id)
        .all()
    )
    return build_classification_view_model(
        emails,
        selected_category,
        search_query=search_query,
    )


def build_classification_view_model(
    emails: list[EmailMessage],
    selected_category: str | None = None,
    search_query: str | None = None,
) -> dict[str, Any]:
    selected = (
        selected_category
        if selected_category in ALLOWED_CATEGORIES
        else BL_COMPARISON
    )
    groups = {category: [] for category in ALLOWED_CATEGORIES}
    needs_classification = []
    search_results = []
    extraction_lookup: dict[str, Any] = {}
    query = (search_query or "").strip()

    for email in emails:
        item = serialize_email(email)
        for document in item["documents"]:
            if document.get("extraction_method"):
                extraction_lookup[str(document["id"])] = {
                    "filename": document["filename"],
                    "document_type": document["document_type"],
                    "extraction_method": document.get("extraction_method"),
                    "fields": document.get("fields"),
                    "normalized_fields": document.get("normalized_fields"),
                }
        if query and _search_matches(item, query):
            search_results.append(item)
        if needs_classification_bucket(email):
            needs_classification.append(item)
            continue
        groups[email.category].append(item)

    counts = {category: len(groups[category]) for category in ALLOWED_CATEGORIES}
    selected_emails = groups[selected]

    return {
        "categories": [
            {
                "key": category,
                "label": CATEGORY_LABELS[category],
                "count": counts[category],
                "action": CATEGORY_ACTIONS[category],
            }
            for category in ALLOWED_CATEGORIES
        ],
        "groups": groups,
        "counts": counts,
        "needs_classification": needs_classification,
        "needs_classification_count": len(needs_classification),
        "total_classified": sum(counts.values()),
        "total_emails": len(emails),
        "selected_category": selected,
        "selected_label": CATEGORY_LABELS[selected],
        "selected_action": CATEGORY_ACTIONS[selected],
        "selected_emails": selected_emails,
        "active_email": selected_emails[0] if selected_emails else None,
        "pipeline_stages": PIPELINE_STAGES,
        "bl_category": BL_COMPARISON,
        "search_query": search_query,
        "search_results": search_results,
        "search_active": bool(query),
        "extraction_data_json": json.dumps(extraction_lookup).replace("<", "\\u003c"),
    }


def classification_summary(db: Session) -> dict[str, Any]:
    view_model = get_classification_view_model(db)
    return {
        "categories": view_model["categories"],
        "counts": view_model["counts"],
        "needs_classification_count": view_model["needs_classification_count"],
        "total_classified": view_model["total_classified"],
        "total_emails": view_model["total_emails"],
    }


def needs_classification_bucket(email: EmailMessage) -> bool:
    return (
        email.category not in ALLOWED_CATEGORIES
        or email.classification_source == "missing_ai_key"
    )


def _search_matches(item: dict[str, Any], query: str) -> bool:
    haystack = " ".join(
        [
            str(item.get("email_id") or ""),
            str(item.get("subject") or ""),
            str(item.get("sender") or ""),
            str(item.get("body") or ""),
            " ".join(
                str(document.get("filename", ""))
                for document in item.get("documents", [])
            ),
            str(item.get("category") or ""),
        ]
    ).casefold()
    return query.casefold() in haystack


def serialize_email(email: EmailMessage) -> dict[str, Any]:
    extractions = getattr(email, "extractions", None) or []
    extraction_by_doc = {
        extraction.document_id: extraction
        for extraction in extractions
        if extraction.document_id is not None
    }

    documents = []
    extraction_errors: list[dict[str, Any]] = []
    extraction_warnings: list[dict[str, Any]] = []

    for document in email.documents:
        extraction = extraction_by_doc.get(document.id)
        extraction_status = extraction.status if extraction else None

        documents.append(
            {
                "id": document.id,
                "filename": document.filename,
                "document_type": document.document_type,
                "status": document.status,
                "extraction_status": extraction_status,
                "extraction_status_class": _status_class(extraction_status),
                "detected_document_type": (
                    extraction.detected_document_type if extraction else None
                ),
                "extraction_method": (
                    extraction.extraction_method if extraction else None
                ),
                "fields": (
                    snake_to_display(extraction.fields)
                    if extraction and extraction.fields
                    else None
                ),
                "normalized_fields": (
                    extraction.normalized_fields if extraction else None
                ),
            }
        )

        if extraction:
            for error in extraction.errors or []:
                extraction_errors.append(
                    {
                        "filename": document.filename,
                        "document_type": document.document_type,
                        "code": error.get("code"),
                        "detail": error.get("detail"),
                        "field": error.get("field"),
                    }
                )
            for warning in extraction.warnings or []:
                extraction_warnings.append(
                    {
                        "filename": document.filename,
                        "document_type": document.document_type,
                        "code": warning.get("code"),
                        "detail": warning.get("detail"),
                        "field": warning.get("field"),
                    }
                )

    body = email.body or ""

    return {
        "id": email.id,
        "email_id": email.email_id,
        "sender": email.sender,
        "subject": email.subject,
        "body": body,
        "body_preview": body[:260],
        "attachment_count": email.attachment_count,
        "category": email.category,
        "category_label": CATEGORY_LABELS.get(email.category),
        "classification_confidence": email.classification_confidence,
        "classification_source": email.classification_source,
        "classified_at": email.classified_at.isoformat() if email.classified_at else None,
        "created_at": email.created_at.isoformat() if email.created_at else None,
        "documents": documents,
        "document_types": ", ".join(
            sorted({document["document_type"] for document in documents})
        )
        or "None",
        "pipeline": build_pipeline_stages(email),
        "extraction_errors": extraction_errors,
        "extraction_warnings": extraction_warnings,
        "has_extraction_issues": bool(extraction_errors or extraction_warnings),
    }
