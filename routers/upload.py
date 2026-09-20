import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, get_settings
from app.database import get_db
from models.document import Document
from models.email_message import EmailMessage, utc_now
from services.email_classifier import EmailClassifier
from services.input_importer import infer_document_type
from services.audit_service import record_classification, record_document_registration


router = APIRouter(tags=["upload"])
templates = Jinja2Templates(directory="templates")


@router.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request):
    return templates.TemplateResponse(request, "upload.html", {"error": None, "active_page": "upload"})


@router.post("/upload")
async def upload_documents(
    request: Request,
    email_json: UploadFile = File(...),
    si_file: UploadFile | None = File(default=None),
    bl_file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
):
    try:
        email = await _read_email_json(email_json)
        email_id = str(email["email_id"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        return templates.TemplateResponse(
            request,
            "upload.html",
            {"error": f"Invalid email JSON: {exc}", "active_page": "upload"},
            status_code=400,
        )

    saved_paths = []
    for upload_file, document_type in ((si_file, "SI"), (bl_file, "BL")):
        if upload_file and upload_file.filename:
            saved_paths.append(
                await _save_attachment(email_id, upload_file, document_type)
            )

    attachment_paths = list(email.get("attachments", [])) + saved_paths
    email["attachments"] = attachment_paths

    email_record = _upsert_email(db, email)
    for attachment_path in attachment_paths:
        document, created = _upsert_document(db, email_id, attachment_path)
        if created:
            record_document_registration(db, email_record, document)

    _classify_email(email_record, attachment_paths)
    record_classification(db, email_record)

    db.commit()
    return RedirectResponse(url=f"/inbox/{email_id}", status_code=303)


async def _read_email_json(upload_file: UploadFile) -> dict[str, Any]:
    content = await upload_file.read()
    email = json.loads(content.decode("utf-8"))
    if not isinstance(email, dict):
        raise ValueError("root value must be an object")
    if "email_id" not in email:
        raise KeyError("email_id")
    return email


async def _save_attachment(
    email_id: str,
    upload_file: UploadFile,
    document_type: str,
) -> str:
    settings = get_settings()
    upload_root = settings.upload_dir
    if not upload_root.is_absolute():
        upload_root = PROJECT_ROOT / upload_root

    safe_name = _safe_filename(upload_file.filename or f"{document_type}.dat")
    target_dir = upload_root / email_id
    target_dir.mkdir(parents=True, exist_ok=True)

    target_path = target_dir / safe_name
    target_path.write_bytes(await upload_file.read())

    return str(target_path.relative_to(PROJECT_ROOT)).replace("\\", "/")


def _safe_filename(filename: str) -> str:
    name = Path(filename).name.strip().replace(" ", "_")
    if not name:
        raise HTTPException(status_code=400, detail="Uploaded file needs a filename")
    return name


def _upsert_email(db: Session, email: dict[str, Any]) -> EmailMessage:
    record = (
        db.query(EmailMessage)
        .filter(EmailMessage.email_id == email["email_id"])
        .one_or_none()
    )
    if record is None:
        record = EmailMessage(email_id=email["email_id"])
        db.add(record)

    attachments = email.get("attachments", [])
    record.sender = email.get("from", "uploaded")
    record.subject = email.get("subject", "")
    record.body = email.get("body", "")
    record.attachment_count = len(attachments)
    return record


def _classify_email(record: EmailMessage, attachment_paths: list[str]) -> None:
    result = EmailClassifier().classify(
        subject=record.subject,
        body=record.body,
        attachments=attachment_paths,
    )
    record.category = result.category
    record.classification_confidence = result.confidence
    record.classification_source = result.source
    record.classified_at = utc_now()


def _upsert_document(
    db: Session,
    email_id: str,
    attachment_path: str,
) -> tuple[Document, bool]:
    record = (
        db.query(Document)
        .filter(Document.attachment_path == attachment_path)
        .one_or_none()
    )
    created = record is None
    if record is None:
        record = Document(attachment_path=attachment_path)
        db.add(record)

    path = Path(attachment_path)
    full_path = PROJECT_ROOT / attachment_path
    record.email_id = email_id
    record.filename = path.name
    record.document_type = infer_document_type(attachment_path)
    record.file_extension = path.suffix.lower().lstrip(".") or "unknown"
    record.file_size_bytes = full_path.stat().st_size if full_path.exists() else None
    record.status = "uploaded"
    return record, created
