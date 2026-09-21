import json
from typing import Any

from sqlalchemy.orm import Session, selectinload

from models.email_message import EmailMessage
from services.classification_schema import ALLOWED_CATEGORIES, BL_COMPARISON
from services.document_parser import snake_to_display
from services.verification_service import serialize_verification


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
    "Files",
    "Type check",
    "Text extraction",
    "Shipment JSON",
    "SI/BL match",
    "Human review",
    "Report",
)

VERIFICATION_STATUS_TABS = (
    {"key": "all", "label": "All"},
    {"key": "matched", "label": "Matched"},
    {"key": "mismatch", "label": "Mismatch"},
    {"key": "needs_review", "label": "Needs review"},
    {"key": "pending", "label": "Pending"},
)


def build_pipeline_stages(email: EmailMessage) -> list[dict[str, Any]]:
    """Map a single email to the end-to-end SI/BL verification pipeline."""
    documents = getattr(email, "documents", None) or []
    extractions = getattr(email, "extractions", None) or []
    verifications = getattr(email, "verifications", None) or []
    verification = verifications[0] if verifications else None

    has_documents = bool(documents)
    si_documents = [document for document in documents if document.document_type == "SI"]
    bl_documents = [document for document in documents if document.document_type == "BL"]
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
    has_errors = any(extraction.status == "error" for extraction in extractions)
    has_warnings = any(extraction.status == "warning" for extraction in extractions)
    issue_status = "Issue" if has_errors else ("Review" if has_warnings else "Done")
    verification_status = verification.result if verification else None

    def done_detail(count: int, label: str) -> str:
        return f"{count} {label}{'' if count == 1 else 's'}"

    return [
        {
            "key": "attachments",
            "name": PIPELINE_STAGES[0],
            "status": "Done" if has_documents else "Pending",
            "detail": (
                f"{len(si_documents)} SI · {len(bl_documents)} BL"
                if has_documents
                else "Waiting for SI/BL files"
            ),
        },
        {
            "key": "detection",
            "name": PIPELINE_STAGES[1],
            "status": "Done" if has_types else "Pending",
            "detail": "SI and BL identified" if has_types else "Needs document labels",
        },
        {
            "key": "extraction",
            "name": PIPELINE_STAGES[2],
            "status": issue_status if has_extraction else "Pending",
            "detail": ", ".join(methods) if has_extraction else None,
        },
        {
            "key": "json",
            "name": PIPELINE_STAGES[3],
            "status": "Done" if has_fields else "Pending",
            "detail": done_detail(len(populated), "record") if has_fields else None,
        },
        {
            "key": "comparison",
            "name": PIPELINE_STAGES[4],
            "status": verification_status or "Pending",
            "detail": (
                f"{verification.confidence * 100:.0f}% confidence"
                if verification and verification.confidence is not None
                else "Run extraction to compare"
            ),
        },
        {
            "key": "review",
            "name": PIPELINE_STAGES[5],
            "status": (
                verification.reviewer_status.title()
                if verification and verification.reviewer_status != "pending"
                else ("Pending" if verification and verification.result != "MATCH" else "Not needed")
            ),
            "detail": (
                verification.review_reason
                if verification and verification.review_reason
                else None
            ),
        },
        {
            "key": "report",
            "name": PIPELINE_STAGES[6],
            "status": "Ready" if verification else "Pending",
            "detail": "PDF available" if verification else None,
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
            selectinload(EmailMessage.verifications),
        )
        .order_by(EmailMessage.email_id)
        .all()
    )
    return build_classification_view_model(
        emails,
        selected_category,
        search_query=search_query,
    )


def get_bl_verification_view_model(
    db: Session,
    selected_status: str | None = None,
    search_query: str | None = None,
) -> dict[str, Any]:
    emails = (
        db.query(EmailMessage)
        .options(
            selectinload(EmailMessage.documents),
            selectinload(EmailMessage.extractions),
            selectinload(EmailMessage.verifications),
        )
        .filter(EmailMessage.category == BL_COMPARISON)
        .order_by(EmailMessage.email_id)
        .all()
    )
    return build_bl_verification_view_model(
        emails,
        selected_status=selected_status,
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
    verification_lookup: dict[str, Any] = {}
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
        if item.get("verification"):
            verification_lookup[item["email_id"]] = item["verification"]
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
        "verification_data_json": json.dumps(verification_lookup).replace("<", "\\u003c"),
    }


def build_bl_verification_view_model(
    emails: list[EmailMessage],
    selected_status: str | None = None,
    search_query: str | None = None,
) -> dict[str, Any]:
    statuses = {tab["key"] for tab in VERIFICATION_STATUS_TABS}
    selected = selected_status if selected_status in statuses else "all"
    groups = {status: [] for status in statuses}
    groups["all"] = []
    extraction_lookup: dict[str, Any] = {}
    verification_lookup: dict[str, Any] = {}
    query = (search_query or "").strip()

    for email in emails:
        item = serialize_email(email)
        item["verification_status"] = verification_status_key(item)
        groups["all"].append(item)
        groups[item["verification_status"]].append(item)

        for document in item["documents"]:
            if document.get("extraction_method"):
                extraction_lookup[str(document["id"])] = {
                    "filename": document["filename"],
                    "document_type": document["document_type"],
                    "extraction_method": document.get("extraction_method"),
                    "fields": document.get("fields"),
                    "normalized_fields": document.get("normalized_fields"),
                }
        if item.get("verification"):
            verification_lookup[item["email_id"]] = item["verification"]

    selected_emails = groups[selected]
    display_emails = [
        item for item in selected_emails if _search_matches(item, query)
    ] if query else selected_emails
    counts = {status: len(groups[status]) for status in groups}
    selected_label = next(
        tab["label"] for tab in VERIFICATION_STATUS_TABS if tab["key"] == selected
    )

    return {
        "status_tabs": [
            {
                "key": tab["key"],
                "label": tab["label"],
                "count": counts[tab["key"]],
            }
            for tab in VERIFICATION_STATUS_TABS
        ],
        "status_groups": groups,
        "counts": counts,
        "total_bl": counts["all"],
        "total_classified": counts["all"],
        "total_emails": counts["all"],
        "selected_status": selected,
        "selected_status_label": selected_label,
        "selected_emails": selected_emails,
        "display_emails": display_emails,
        "active_email": display_emails[0] if display_emails else None,
        "pipeline_stages": PIPELINE_STAGES,
        "bl_category": BL_COMPARISON,
        "search_query": search_query,
        "search_active": bool(query),
        "extraction_data_json": json.dumps(extraction_lookup).replace("<", "\\u003c"),
        "verification_data_json": json.dumps(verification_lookup).replace("<", "\\u003c"),
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


def verification_status_key(item: dict[str, Any]) -> str:
    verification = item.get("verification")
    if not verification:
        return "pending"
    result = verification.get("result")
    if result == "MATCH":
        return "matched"
    if result == "MISMATCH":
        return "mismatch"
    if result == "REVIEW":
        return "needs_review"
    return "pending"


def serialize_email(email: EmailMessage) -> dict[str, Any]:
    extractions = getattr(email, "extractions", None) or []
    extraction_by_doc = {
        extraction.document_id: extraction
        for extraction in extractions
        if extraction.document_id is not None
    }
    verifications = getattr(email, "verifications", None) or []
    verification = verifications[0] if verifications else None

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
        "verification": serialize_verification(verification),
        "extraction_errors": extraction_errors,
        "extraction_warnings": extraction_warnings,
        "has_extraction_issues": bool(extraction_errors or extraction_warnings),
    }
