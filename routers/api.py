import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from models.audit_event import AuditEvent
from models.document import Document
from models.email_message import EmailMessage, utc_now
from models.extraction import Extraction
from models.verification import Verification
from services.email_classifier import EmailClassifier
from services.classification_workbench import classification_summary
from services.document_parser import snake_to_display
from services.extraction_service import ExtractionService
from services.input_importer import InputDataImporter, reset_database
from services.pdf_report import generate_report
from services.submission_service import SubmissionService
from services.verification_service import VerificationService, serialize_verification
from services.audit_service import list_events, record_classification, serialize_detail
from services.bl_verification_service import BLVerificationBatchService


router = APIRouter(prefix="/api", tags=["api"])


@router.get("/status")
def api_status() -> dict[str, str]:
    return {"status": "ready"}


@router.get("/classification-summary")
def get_classification_summary(db: Session = Depends(get_db)) -> dict:
    return classification_summary(db)


@router.post("/classify-email")
def classify_email(payload: dict) -> dict[str, str | float | None]:
    classifier = EmailClassifier()
    result = classifier.classify(
        subject=str(payload.get("subject", "")),
        body=str(payload.get("body", "")),
        attachments=payload.get("attachments", []),
    )
    return result.to_dict()


@router.post("/classify-imported-emails")
def classify_imported_emails(db: Session = Depends(get_db)) -> dict[str, int | str]:
    classifier = EmailClassifier()
    submission_service = SubmissionService()
    emails = db.query(EmailMessage).order_by(EmailMessage.email_id).all()

    for email in emails:
        result = classifier.classify(
            subject=email.subject,
            body=email.body,
            attachments=[document.attachment_path for document in email.documents],
        )
        email.category = result.category
        email.classification_confidence = result.confidence
        email.classification_source = result.source
        email.classified_at = utc_now()
        record_classification(db, email)
        submission_service.upsert_for_email(db, email)

    db.commit()
    return {"status": "classified", "emails": len(emails)}


@router.get("/audit-events")
def audit_events(
    event_type: str | None = None,
    result: str | None = None,
    reviewer_status: str | None = None,
    email_id: str | None = None,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = Query(default=1),
    page_size: int = Query(default=50),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return list_events(
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/audit-events/{event_id}")
def audit_event_detail(event_id: int, db: Session = Depends(get_db)) -> dict:
    event = db.get(AuditEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Audit event not found")
    return serialize_detail(db, event)


@router.post("/import-input-data")
def import_input_data(
    reset: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict[str, int | str]:
    if reset:
        reset_database()

    result = InputDataImporter().import_all(db)
    return {
        "status": "imported",
        "emails": result["emails"],
        "documents": result["documents"],
    }


@router.get("/extractions")
def list_extractions(db: Session = Depends(get_db)) -> list[dict]:
    extractions = db.query(Extraction).order_by(Extraction.id).all()
    return [ExtractionService.serialize(record) for record in extractions]


@router.post("/extract/{email_id}")
def extract_email(email_id: str, db: Session = Depends(get_db)) -> dict:
    email = (
        db.query(EmailMessage)
        .filter(EmailMessage.email_id == email_id)
        .one_or_none()
    )
    if email is None:
        raise HTTPException(status_code=404, detail="Email not found")

    result = ExtractionService().process_email(db, email)
    verification = VerificationService().verify_email(db, email)
    SubmissionService().upsert_for_email(db, email, verification)
    db.commit()
    result["verification"] = serialize_verification(verification)
    return result


@router.post("/extract-all")
def extract_all(db: Session = Depends(get_db)) -> dict[str, int | str | list]:
    email_ids = (
        db.query(Document.email_id)
        .filter(Document.document_type.in_(("SI", "BL")))
        .distinct()
        .order_by(Document.email_id)
        .all()
    )

    service = ExtractionService()
    verifier = VerificationService()
    submission_service = SubmissionService()
    results = []
    for (email_id,) in email_ids:
        email = (
            db.query(EmailMessage)
            .filter(EmailMessage.email_id == email_id)
            .one_or_none()
        )
        if email is None:
            continue
        result = service.process_email(db, email)
        verification = verifier.verify_email(db, email)
        submission_service.upsert_for_email(db, email, verification)
        db.commit()
        result["verification"] = serialize_verification(verification)
        results.append(result)

    return {
        "status": "extracted",
        "emails": len(results),
        "results": results,
    }


@router.post("/verify-bl-comparison")
def verify_bl_comparison(payload: dict, db: Session = Depends(get_db)) -> dict[str, int | str]:
    mode = str(payload.get("mode", "pending"))
    if mode not in ("all", "pending"):
        raise HTTPException(status_code=400, detail="mode must be all or pending")

    result = BLVerificationBatchService().run(db, mode)
    db.commit()
    return result


@router.get("/submission")
def get_submission(db: Session = Depends(get_db)) -> dict[str, dict]:
    return SubmissionService().export(db)


@router.get("/submission.json")
def download_submission_json(db: Session = Depends(get_db)) -> Response:
    payload = SubmissionService().export(db)
    return Response(
        content=json.dumps(payload, indent=2, sort_keys=True),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="submission.json"'},
    )


@router.post("/submission/refresh")
def refresh_submission(db: Session = Depends(get_db)) -> dict[str, int | str]:
    result = SubmissionService().refresh_all(db)
    db.commit()
    return {
        "status": "refreshed",
        "entries": result["upserted"],
        "removed": result["removed"],
    }


@router.get("/verification/{email_id}")
def get_verification(email_id: str, db: Session = Depends(get_db)) -> dict:
    verification = (
        db.query(Verification)
        .filter(Verification.email_id == email_id)
        .one_or_none()
    )
    if verification is None:
        raise HTTPException(status_code=404, detail="Verification not found")

    return serialize_verification(verification)


@router.post("/verification/{email_id}/review")
def review_verification(
    email_id: str,
    payload: dict,
    db: Session = Depends(get_db),
) -> dict:
    verification = (
        db.query(Verification)
        .filter(Verification.email_id == email_id)
        .one_or_none()
    )
    if verification is None:
        raise HTTPException(status_code=404, detail="Verification not found")

    action = str(payload.get("action", ""))
    corrected_fields = payload.get("corrected_fields")
    record = VerificationService().review(
        db,
        verification.id,
        action,
        corrected_fields,
    )
    db.commit()
    return serialize_verification(record)


@router.get("/verification/{email_id}/report.pdf")
def verification_report(email_id: str, db: Session = Depends(get_db)) -> Response:
    verification = (
        db.query(Verification)
        .filter(Verification.email_id == email_id)
        .one_or_none()
    )
    if verification is None:
        raise HTTPException(status_code=404, detail="Verification not found")

    email = (
        db.query(EmailMessage)
        .filter(EmailMessage.email_id == email_id)
        .one_or_none()
    )
    si = (
        db.query(Extraction)
        .filter(
            Extraction.email_id == email_id,
            Extraction.document_type == "SI",
        )
        .one_or_none()
    )
    bl = (
        db.query(Extraction)
        .filter(
            Extraction.email_id == email_id,
            Extraction.document_type == "BL",
        )
        .one_or_none()
    )

    pdf_bytes = generate_report(
        email_id=email_id,
        subject=email.subject if email else "",
        sender=email.sender if email else "",
        category=email.category if email else "",
        verification=serialize_verification(verification),
        si_fields=snake_to_display(si.fields) if si and si.fields else {},
        bl_fields=snake_to_display(bl.fields) if bl and bl.fields else {},
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{email_id}_report.pdf"'
        },
    )
