from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from models.document import Document
from models.email_message import EmailMessage
from models.verification import Verification
from services.classification_workbench import (
    CATEGORY_LABELS,
    get_bl_verification_view_model,
    get_classification_view_model,
)
from services.audit_service import list_events


router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="templates")


def _build_inbox_category_tabs(emails: list[EmailMessage]) -> list[dict[str, int | str]]:
    counts = {category: 0 for category in CATEGORY_LABELS}
    unclassified_count = 0

    for email in emails:
        if email.category in counts:
            counts[email.category] += 1
        else:
            unclassified_count += 1

    tabs = [{"key": "", "label": "All", "count": len(emails)}]
    tabs.extend(
        {"key": key, "label": label, "count": counts[key]}
        for key, label in CATEGORY_LABELS.items()
    )
    if unclassified_count:
        tabs.append(
            {
                "key": "unclassified",
                "label": "Unclassified",
                "count": unclassified_count,
            }
        )
    return tabs


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    total_emails = db.query(EmailMessage).count()
    total_documents = db.query(Document).count()
    classification = get_classification_view_model(db)
    bl_overview = get_bl_verification_view_model(db)
    verification_counts = bl_overview["counts"]
    matched_count = verification_counts.get("matched", 0)
    mismatch_count = verification_counts.get("mismatch", 0)
    needs_review_count = verification_counts.get("needs_review", 0)
    pending_count = verification_counts.get("pending", 0)
    total_bl = verification_counts.get("all", 0)
    action_required = mismatch_count + needs_review_count + pending_count
    match_rate = round((matched_count / total_bl) * 100) if total_bl else 0
    reviewed_count = (
        db.query(Verification)
        .filter(Verification.reviewer_status.in_(("approved", "corrected")))
        .count()
    )

    def chart_degrees(count: int) -> float:
        return round((count / total_bl) * 360, 2) if total_bl else 0

    matched_end = chart_degrees(matched_count)
    mismatch_end = matched_end + chart_degrees(mismatch_count)
    review_end = mismatch_end + chart_degrees(needs_review_count)

    attention_queue = []
    for status_key, label, tone, action in (
        ("mismatch", "Mismatch", "danger", "Compare fields"),
        ("needs_review", "Review", "warning", "Check reason"),
        ("pending", "Pending", "neutral", "Run comparison"),
    ):
        for email in bl_overview["status_groups"].get(status_key, []):
            if len(attention_queue) >= 5:
                break
            attention_queue.append(
                {
                    "email_id": email["email_id"],
                    "subject": email["subject"] or "(No subject)",
                    "attachments": email["attachment_count"],
                    "status_label": label,
                    "tone": tone,
                    "action": action,
                }
            )
        if len(attention_queue) >= 5:
            break

    decision_message = "All BL/SI comparisons are matched."
    if mismatch_count:
        decision_message = "Resolve mismatches before preparing reports."
    elif needs_review_count:
        decision_message = "Review flagged cases before clearing the queue."
    elif pending_count:
        decision_message = "Run comparisons for pending BL/SI emails."

    recent_emails = (
        db.query(EmailMessage)
        .order_by(EmailMessage.created_at.desc())
        .limit(6)
        .all()
    )

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "stats": {
                "total_emails": total_emails,
                "total_documents": total_documents,
                "total_bl": total_bl,
                "matched": matched_count,
                "mismatch": mismatch_count,
                "needs_review": needs_review_count,
                "pending": pending_count,
                "action_required": action_required,
                "match_rate": match_rate,
                "reviewed": reviewed_count,
            },
            "verification_chart": {
                "matched_end": matched_end,
                "mismatch_end": mismatch_end,
                "review_end": review_end,
            },
            "decision_message": decision_message,
            "attention_queue": attention_queue,
            "classification": classification,
            "recent_emails": recent_emails,
            "active_page": "dashboard",
        },
    )


@router.get("/classification", response_class=HTMLResponse)
def classification_workbench(
    request: Request,
    status: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
):
    view_model = get_bl_verification_view_model(
        db,
        selected_status=status,
        search_query=q,
    )
    return templates.TemplateResponse(
        request,
        "classification.html",
        {**view_model, "active_page": "classification"},
    )


@router.get("/inbox", response_class=HTMLResponse)
def inbox_page(request: Request, db: Session = Depends(get_db)):
    emails = db.query(EmailMessage).order_by(EmailMessage.created_at.desc()).all()
    return templates.TemplateResponse(
        request,
        "inbox.html",
        {
            "emails": emails,
            "category_tabs": _build_inbox_category_tabs(emails),
            "active_page": "inbox",
        },
    )


@router.get("/inbox/{email_id}", response_class=HTMLResponse)
def inbox_detail(request: Request, email_id: str, db: Session = Depends(get_db)):
    email = (
        db.query(EmailMessage)
        .options(selectinload(EmailMessage.documents))
        .filter(EmailMessage.email_id == email_id)
        .one_or_none()
    )
    if email is None:
        raise HTTPException(status_code=404, detail="Email not found")
    return templates.TemplateResponse(
        request,
        "inbox_detail.html",
        {"email": email, "active_page": "inbox"},
    )


@router.get("/library", response_class=HTMLResponse)
def document_library(request: Request, db: Session = Depends(get_db)):
    documents = db.query(Document).order_by(Document.created_at.desc()).all()
    return templates.TemplateResponse(
        request,
        "library.html",
        {"documents": documents, "active_page": "library"},
    )


@router.get("/audit", response_class=HTMLResponse)
def audit_trail(
    request: Request,
    event_type: str | None = None,
    result: str | None = None,
    reviewer_status: str | None = None,
    email_id: str | None = None,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
):
    error = None
    try:
        audit = list_events(
            db,
            event_type=event_type,
            result=result,
            reviewer_status=reviewer_status,
            email_id=email_id,
            search=q,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        error = str(exc)
        audit = list_events(db)

    filters = {
        "event_type": event_type or "",
        "result": result or "",
        "reviewer_status": reviewer_status or "",
        "email_id": email_id or "",
        "q": q or "",
        "date_from": date_from or "",
        "date_to": date_to or "",
    }

    return templates.TemplateResponse(
        request,
        "audit.html",
        {
            **audit,
            "filters": filters,
            "error": error,
            "active_page": "audit",
        },
    )
