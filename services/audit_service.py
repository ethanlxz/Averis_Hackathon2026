from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from models.audit_event import AuditEvent
from models.document import Document
from models.email_message import EmailMessage
from models.extraction import Extraction
from models.verification import Verification
from services.document_parser import snake_to_display


EVENT_TYPES = (
    "classification_completed",
    "document_registered",
    "extraction_completed",
    "verification_completed",
    "verification_approved",
    "verification_corrected",
)

EVENT_LABELS = {
    "classification_completed": "Classification completed",
    "document_registered": "Document registered",
    "extraction_completed": "Extraction completed",
    "verification_completed": "Verification completed",
    "verification_approved": "Verification approved",
    "verification_corrected": "Verification corrected",
}

RESULT_CLASSES = {
    "MATCH": "success",
    "MISMATCH": "danger",
    "REVIEW": "warning",
}


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_bound(value: str | None, end: bool = False) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    try:
        if len(raw) == 10:
            parsed_date = date.fromisoformat(raw)
            if end:
                return datetime.combine(
                    parsed_date + timedelta(days=1),
                    time.min,
                    tzinfo=timezone.utc,
                )
            return datetime.combine(parsed_date, time.min, tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid date value: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _event_label(event_type: str) -> str:
    return EVENT_LABELS.get(event_type, event_type.replace("_", " ").title())


def _short_hash(value: str | None) -> str:
    if not value:
        return "-"
    return f"{value[:12]}...{value[-8:]}"


def _record_timeline(
    email: EmailMessage | None = None,
    document: Document | None = None,
    extraction: Extraction | None = None,
    verification: Verification | None = None,
    si_document: Document | None = None,
    bl_document: Document | None = None,
    si_extraction: Extraction | None = None,
    bl_extraction: Extraction | None = None,
) -> list[dict[str, str | None]]:
    entries: list[dict[str, str | None]] = []

    def add(label: str, timestamp: datetime | None, source: str) -> None:
        entries.append(
            {
                "label": label,
                "timestamp": _iso(timestamp),
                "source": source,
            }
        )

    if email:
        add("Email created", email.created_at, "EmailMessage.created_at")
        add("Email classified", email.classified_at, "EmailMessage.classified_at")
    if document:
        add(
            f"Document registered ({document.document_type})",
            document.created_at,
            "Document.created_at",
        )
    if extraction:
        add("Extraction created", extraction.created_at, "Extraction.created_at")
        add("Extraction processed", extraction.processed_at, "Extraction.processed_at")
    if si_document and si_document is not document:
        add(
            "SI document registered",
            si_document.created_at,
            "Document.created_at",
        )
    if bl_document and bl_document is not document:
        add(
            "BL document registered",
            bl_document.created_at,
            "Document.created_at",
        )
    if si_extraction and si_extraction is not extraction:
        add("SI extraction created", si_extraction.created_at, "Extraction.created_at")
        add("SI extraction processed", si_extraction.processed_at, "Extraction.processed_at")
    if bl_extraction and bl_extraction is not extraction:
        add("BL extraction created", bl_extraction.created_at, "Extraction.created_at")
        add("BL extraction processed", bl_extraction.processed_at, "Extraction.processed_at")
    if verification:
        add("Verification created", verification.created_at, "Verification.created_at")
        add("Verification reviewed", verification.reviewed_at, "Verification.reviewed_at")
    return entries


def _extraction_snapshot(extraction: Extraction | None) -> dict[str, Any] | None:
    if extraction is None:
        return None
    return {
        "id": extraction.id,
        "document_id": extraction.document_id,
        "document_type": extraction.document_type,
        "status": extraction.status,
        "extraction_method": extraction.extraction_method,
        "detected_document_type": extraction.detected_document_type,
        "fields": dict(extraction.fields or {}),
        "display_fields": snake_to_display(extraction.fields or {}),
        "normalized_fields": dict(extraction.normalized_fields or {}),
        "errors": list(extraction.errors or []),
        "warnings": list(extraction.warnings or []),
        "created_at": _iso(extraction.created_at),
        "processed_at": _iso(extraction.processed_at),
    }


def _verification_snapshot(
    email: EmailMessage,
    verification: Verification,
    si: Extraction | None,
    bl: Extraction | None,
    timeline: list[dict[str, str | None]],
) -> dict[str, Any]:
    return {
        "email": {
            "id": email.id,
            "email_id": email.email_id,
            "subject": email.subject,
            "sender": email.sender,
            "category": email.category,
        },
        "verification": {
            "id": verification.id,
            "result": verification.result,
            "confidence": verification.confidence,
            "reviewer_status": verification.reviewer_status,
            "review_reason": verification.review_reason,
            "has_defect": verification.has_defect,
            "defect_fields": list(verification.defect_fields or []),
            "mismatch_details": verification.mismatch_details or {},
            "review_details": verification.review_details or {},
            "missing_fields": list(verification.missing_fields or []),
            "corrected_fields": verification.corrected_fields,
            "verification_hash": verification.verification_hash,
            "created_at": _iso(verification.created_at),
            "reviewed_at": _iso(verification.reviewed_at),
        },
        "si": _extraction_snapshot(si),
        "bl": _extraction_snapshot(bl),
        "timeline": timeline,
    }


def create_event(
    db: Session,
    event_type: str,
    payload: dict[str, Any],
    *,
    email_id: str | None = None,
    document_id: int | None = None,
    extraction_id: int | None = None,
    verification_id: int | None = None,
    result: str | None = None,
    reviewer_status: str | None = None,
    verification_hash: str | None = None,
    actor: str = "system",
) -> AuditEvent:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unsupported audit event type: {event_type}")
    event = AuditEvent(
        event_type=event_type,
        email_id=email_id,
        document_id=document_id,
        extraction_id=extraction_id,
        verification_id=verification_id,
        result=result,
        reviewer_status=reviewer_status,
        verification_hash=verification_hash,
        actor=actor,
        payload=payload,
    )
    db.add(event)
    db.flush()
    return event


def record_classification(
    db: Session,
    email: EmailMessage,
    *,
    actor: str = "system",
) -> AuditEvent:
    db.flush()
    return create_event(
        db,
        "classification_completed",
        {
            "classification": {
                "category": email.category,
                "confidence": email.classification_confidence,
                "source": email.classification_source,
                "classified_at": _iso(email.classified_at),
            },
            "timeline": _record_timeline(email=email),
        },
        email_id=email.email_id,
        actor=actor,
    )


def record_document_registration(
    db: Session,
    email: EmailMessage,
    document: Document,
    *,
    actor: str = "system",
) -> AuditEvent:
    db.flush()
    return create_event(
        db,
        "document_registered",
        {
            "document": {
                "id": document.id,
                "filename": document.filename,
                "attachment_path": document.attachment_path,
                "document_type": document.document_type,
                "file_extension": document.file_extension,
                "file_size_bytes": document.file_size_bytes,
                "status": document.status,
                "created_at": _iso(document.created_at),
            },
            "timeline": _record_timeline(email=email, document=document),
        },
        email_id=email.email_id,
        document_id=document.id,
        actor=actor,
    )


def record_extraction(
    db: Session,
    email: EmailMessage,
    document: Document,
    extraction: Extraction,
    *,
    actor: str = "system",
) -> AuditEvent:
    db.flush()
    return create_event(
        db,
        "extraction_completed",
        {
            "document": {
                "id": document.id,
                "filename": document.filename,
                "document_type": document.document_type,
            },
            "extraction": _extraction_snapshot(extraction),
            "timeline": _record_timeline(
                email=email,
                document=document,
                extraction=extraction,
            ),
        },
        email_id=email.email_id,
        document_id=document.id,
        extraction_id=extraction.id,
        actor=actor,
    )


def record_verification(
    db: Session,
    email: EmailMessage,
    verification: Verification,
    si: Extraction | None,
    bl: Extraction | None,
    *,
    event_type: str = "verification_completed",
    actor: str = "system",
) -> AuditEvent:
    db.flush()
    si_document = db.get(Document, si.document_id) if si and si.document_id else None
    bl_document = db.get(Document, bl.document_id) if bl and bl.document_id else None
    timeline = _record_timeline(
        email=email,
        verification=verification,
        si_document=si_document,
        bl_document=bl_document,
        si_extraction=si,
        bl_extraction=bl,
    )
    return create_event(
        db,
        event_type,
        _verification_snapshot(email, verification, si, bl, timeline),
        email_id=email.email_id,
        document_id=verification.document_id,
        extraction_id=bl.id if bl else (si.id if si else None),
        verification_id=verification.id,
        result=verification.result,
        reviewer_status=verification.reviewer_status,
        verification_hash=verification.verification_hash,
        actor=actor,
    )


def serialize_event(event: AuditEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "event_label": _event_label(event.event_type),
        "occurred_at": _iso(event.occurred_at),
        "email_id": event.email_id,
        "document_id": event.document_id,
        "extraction_id": event.extraction_id,
        "verification_id": event.verification_id,
        "result": event.result,
        "result_class": RESULT_CLASSES.get(event.result or "", ""),
        "reviewer_status": event.reviewer_status,
        "verification_hash": event.verification_hash,
        "short_hash": _short_hash(event.verification_hash),
        "actor": event.actor,
    }


def list_events(
    db: Session,
    *,
    event_type: str | None = None,
    result: str | None = None,
    reviewer_status: str | None = None,
    email_id: str | None = None,
    search: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    query = db.query(AuditEvent)

    if event_type:
        query = query.filter(AuditEvent.event_type == event_type)
    if result:
        query = query.filter(AuditEvent.result == result)
    if reviewer_status:
        query = query.filter(AuditEvent.reviewer_status == reviewer_status)
    if email_id:
        query = query.filter(AuditEvent.email_id.ilike(f"%{email_id.strip()}%"))

    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                AuditEvent.email_id.ilike(term),
                AuditEvent.event_type.ilike(term),
                AuditEvent.result.ilike(term),
                AuditEvent.reviewer_status.ilike(term),
                AuditEvent.verification_hash.ilike(term),
            )
        )

    lower_bound = _parse_bound(date_from)
    upper_bound = _parse_bound(date_to, end=True)
    if lower_bound:
        query = query.filter(AuditEvent.occurred_at >= lower_bound)
    if upper_bound:
        query = query.filter(AuditEvent.occurred_at < upper_bound)

    total = query.count()
    events = (
        query.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    event_types = [
        row[0]
        for row in db.query(AuditEvent.event_type)
        .distinct()
        .order_by(AuditEvent.event_type)
        .all()
    ]
    results = [
        row[0]
        for row in db.query(AuditEvent.result)
        .filter(AuditEvent.result.isnot(None))
        .distinct()
        .order_by(AuditEvent.result)
        .all()
    ]
    reviewer_statuses = [
        row[0]
        for row in db.query(AuditEvent.reviewer_status)
        .filter(AuditEvent.reviewer_status.isnot(None))
        .distinct()
        .order_by(AuditEvent.reviewer_status)
        .all()
    ]

    return {
        "events": [serialize_event(event) for event in events],
        "total": total,
        "page": page,
        "page_size": page_size,
        "event_types": event_types,
        "results": results,
        "reviewer_statuses": reviewer_statuses,
    }


def serialize_detail(db: Session, event: AuditEvent) -> dict[str, Any]:
    summary = serialize_event(event)
    payload = dict(event.payload or {})
    timeline = payload.get("timeline") or []

    if not timeline:
        email = (
            db.query(EmailMessage)
            .filter(EmailMessage.email_id == event.email_id)
            .one_or_none()
            if event.email_id
            else None
        )
        document = db.get(Document, event.document_id) if event.document_id else None
        extraction = db.get(Extraction, event.extraction_id) if event.extraction_id else None
        verification = (
            db.get(Verification, event.verification_id)
            if event.verification_id
            else None
        )
        timeline = _record_timeline(
            email=email,
            document=document,
            extraction=extraction,
            verification=verification,
        )

    return {
        **summary,
        "occurred_at_utc": _iso(event.occurred_at),
        "payload": payload,
        "timeline": timeline,
    }
