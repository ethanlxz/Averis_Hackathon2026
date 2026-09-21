# Averis Project Structure

Use this as the quick orientation map before changing code. The app is a FastAPI
MVP that imports the hackathon inbox, classifies shipping emails, extracts
SI/BL shipment fields (TXT / DOCX / PDF / XLSX + OCR), validates the extraction,
compares SI vs BL, persists a verification decision, supports human review,
records an append-only audit trail, and generates a PDF verification report.

## Start Here

- `app/main.py` is the FastAPI entrypoint. It creates the app, initializes the
  database on startup, mounts static files, and includes all routers.
- `app/config.py` loads configurable settings from `.env` and environment
  variables. Real environment variables override `.env` values.
- `app/database.py` owns the SQLAlchemy engine/session setup, table creation,
  and SQLite column migrations.
- `routers/api.py` contains machine-facing endpoints for import, classification,
  extraction, verification, review, audit events, and classification summaries.
- `GET /classification` is the human workbench for browsing classified emails,
  running SI/BL verification, reviewing exceptions, and opening audit history.
- `services/email_classifier.py` contains the high-level classification flow.
- `services/extraction_service.py` orchestrates the document-extraction pipeline.
- `services/comparison_engine.py` + `services/field_normalizer.py` implement
  SI vs BL comparison.
- `services/verification_service.py` persists comparison decisions and reviewer
  actions.
- `services/audit_service.py` creates immutable process/review snapshots and
  serves audit-trail queries.
- `services/pdf_report.py` generates downloadable verification reports.

## Directory Map

```text
Averis_Project/
├── app/
│   ├── main.py              FastAPI app setup, router registration, health check
│   ├── config.py            .env loading and Settings model
│   └── database.py          SQLAlchemy engine, sessions, init_db, migrations
├── models/
│   ├── email_message.py     EmailMessage ORM model and classification fields
│   ├── document.py          Document ORM model for imported/uploaded attachments
│   ├── extraction.py        Extraction ORM model (per-document field extraction)
│   ├── verification.py      Verification ORM model for SI/BL comparison results
│   └── audit_event.py       Append-only process/review audit events
├── routers/
│   ├── dashboard.py         HTML dashboard, classification workbench (+ search)
│   ├── upload.py            HTML upload page and upload handling
│   ├── emails.py            JSON email list/detail endpoints
│   ├── documents.py         JSON document list endpoint
│   └── api.py               Import, classify, extract, verify, audit, and report endpoints
├── services/
│   ├── classification_schema.py    Category constants and ClassificationResult
│   ├── classification_workbench.py Grouped/searchable data and email detail serialization
│   ├── email_classifier.py         DeepSeek-first classifier plus rule fallback
│   ├── llm_service.py              DeepSeek API (classify + shipment-field extraction)
│   ├── input_importer.py           Imports bundled inbox/attachments into SQLite
│   ├── inbox_service.py            Wrapper around bundled loader.py
│   ├── document_parser.py          Document-type detection + text/field extraction
│   ├── ocr_service.py              EasyOCR + PyMuPDF OCR for scanned PDFs/images
│   ├── document_validator.py       Extraction error/warning validation
│   ├── extraction_service.py       Extraction pipeline orchestration + persistence
│   ├── field_normalizer.py         Normalizes names, ports, counts, weights
│   ├── comparison_engine.py        SI vs BL comparison (uses field_normalizer)
│   ├── verification_service.py     Persists decisions and reviewer actions
│   ├── audit_service.py            Immutable audit snapshots and queries
│   └── pdf_report.py               Generates PDF verification reports
├── scripts/
│   └── import_input_data.py        CLI wrapper for importing inbox data
├── templates/
│   ├── base.html             Layout shell
│   ├── dashboard.html        Dashboard UI
│   ├── classification.html   Classified email workbench (queue + SI/BL actions)
│   ├── inbox.html            Inbox list
│   ├── inbox_detail.html     Single email detail
│   ├── library.html          Document library
│   ├── audit.html            Audit trail table and detail panel
│   └── upload.html           Upload UI
├── static/
│   ├── styles.css            Shared page styling
│   ├── app.js                Shared client-side behavior
│   └── icons.svg             SVG icon sprite
├── tests/
│   ├── test_email_classification.py   Classification unit tests
│   ├── test_classification_workbench.py  Workbench view-model tests
│   ├── test_field_normalizer.py       Normalization/comparison tests
│   └── test_audit_service.py          Audit snapshot/query tests
├── inbox/                   Bundled hackathon email JSON files
├── attachments/             Bundled SI/BL/email attachment files
├── loader.py                Hackathon input loader
├── sample_submission.json   Expected submission key shape
├── Dockerfile               Container image for judge setup
├── docker-compose.yml       One-command local Docker runner
├── requirements-docker.txt  Docker dependencies without local EasyOCR stack
├── .env                     Local secrets/config, ignored by git
├── .env.example             Safe template of supported config values
├── uploads/                 Runtime storage for manually uploaded attachments
│   └── <email_id>/          Per-email upload directory, created on demand
├── requirements.txt         Full local Python dependencies
└── README.md                Human setup/run notes
```

The project also creates local runtime state that is not part of the source
layout: `averis.db` stores SQLite data, `.venv/` stores the local environment,
and `__pycache__/` stores Python bytecode. These paths are local-only and
should not be committed.

## Runtime Flow

### App Startup

1. `uvicorn app.main:app --reload`
2. `app/main.py` loads `settings = get_settings()` from `app/config.py`.
3. Startup lifespan creates `settings.upload_dir`.
4. Startup calls `init_db()` from `app/database.py`, which creates all tables and
   applies SQLite column migrations (`_ensure_email_classification_columns`,
   `_ensure_extraction_columns`, `_ensure_verification_columns`).
5. Routers from `routers/` are mounted on the FastAPI app.

### Configuration Flow

1. `.env` is read by `app/config.py`.
2. Values are copied into `os.environ` only if they are not already set.
3. `Settings` exposes `APP_NAME`, `APP_VERSION`, `DATABASE_URL`, `DATA_SOURCE`,
   `UPLOAD_DIR`, `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`,
   `DEEPSEEK_TIMEOUT_SECONDS`.
4. `services/llm_service.py` uses the DeepSeek settings.
5. `services/ocr_service.py` reads `OCR_LANG` directly from the environment
   (default `"en"`).

### Import Bundle Data

Endpoint:

```text
POST /api/import-input-data?reset=true
```

Code path:

```text
routers/api.py
└── InputDataImporter.import_all()
    ├── InboxService.list_emails()   -> root loader.py reads inbox/*.json
    ├── _upsert_email()              -> models/email_message.py
    ├── _upsert_document()           -> models/document.py
    └── _classify_email()            -> EmailClassifier.classify()
```

CLI equivalent:

```text
scripts/import_input_data.py --reset
```

### Email Classification

Endpoints:

```text
POST /api/classify-email
POST /api/classify-imported-emails
GET  /api/classification-summary
GET  /classification
```

Code path:

```text
routers/api.py
└── EmailClassifier.classify()
    ├── no DEEPSEEK_API_KEY   -> category=null, source=missing_ai_key
    ├── key present           -> LLMService.classify_email()
    │                           POST {DEEPSEEK_BASE_URL}/chat/completions
    └── DeepSeek fails/invalid -> rule result, source=rules_fallback
```

Rule-only behavior is still available through
`EmailClassifier(prefer_llm=False)` and is covered by tests.

### Classified Email Workbench

Endpoints:

```text
GET /classification
GET /classification?category=SI_REQUEST
GET /classification?q=<search>
```

Code path:

```text
routers/dashboard.py
└── get_classification_view_model()
    └── services/classification_workbench.py
        ├── groups official categories
        ├── separates missing-key/null-category emails
        ├── serializes per-email documents, extraction values, and verification state
        ├── collects extraction errors/warnings for the detail panel
        └── searches across all categories via ?q=
```

The default category is `BL_COMPARISON`. The page is split into a left email
queue and a right detail panel. Queue rows keep the email ID, subject, sender,
file count, and current verification status in a fixed-height layout so long
content does not collapse the row. The detail panel shows summary metrics,
SI/BL verification actions, extraction issues, the latest verification result,
document tiles, message preview, and links to the full email and audit trail.
The old visible "Verification pipeline" card has been removed from the page.

### Manual Upload Flow

Endpoints:

```text
GET  /upload
POST /upload
```

Code path: `routers/upload.py` reads the uploaded email JSON, saves SI/BL files
into `UPLOAD_DIR`, upserts `EmailMessage`/`Document`, and classifies the email
the same way imported emails are classified.

### Email and Document Viewing

Endpoints:

```text
GET /emails
GET /emails/{email_id}
GET /documents
```

Code path:

```text
routers/emails.py      returns EmailMessage data plus classification fields
routers/documents.py   returns Document rows
```

### Document Extraction Pipeline

Endpoints:

```text
POST /api/extract/{email_id}   extract one email's SI/BL attachments
POST /api/extract-all          extract every email that has SI/BL attachments
GET  /api/extractions          list stored extraction records
```

Code path:

```text
routers/api.py
└── ExtractionService.process_email()
    ├── extract_document() per SI/BL document
    │   ├── read bytes (InboxService, then PROJECT_ROOT fallback)
    │   ├── DocumentParser.extract_text()
    │   │   ├── TXT   -> decode
    │   │   ├── DOCX  -> stdlib zip/XML
    │   │   ├── PDF   -> pdfplumber/pypdf/PyMuPDF text, else EasyOCR (pdf_ocr)
    │   │   ├── XLSX  -> stdlib zip/XML
    │   │   └── image -> EasyOCR (ocr)
    │   ├── DocumentParser.parse_text() -> ShipmentFields
    │   │   ("Label: value" recognition + field_normalizer count/weight parsing)
    │   ├── LLM fill gaps (extract_shipment_fields) when incomplete -> "+llm"
    │   ├── DocumentValidator.validate() -> status/errors/warnings
    │   └── upsert Extraction (id, extraction_method, processed_at, ...)
    └── VerificationService.verify_email()
        ├── compare SI and BL extracted fields
        ├── persist MATCH / MISMATCH / REVIEW decision
        └── attach verification data to the API response
```

`ShipmentFields` holds the seven fields: shipper, consignee, notify_party,
port_of_loading, port_of_discharge, container_count, gross_weight_kg. Display
keys map to Shipper / Consignee / Notify Party / Port of Loading / Port of
Discharge / Container Count / Gross Weight (kg).

### Extraction Validation

`services/document_validator.py` produces a `ValidationResult` persisted on each
`Extraction` row (`status`, `detected_document_type`, `errors`, `warnings`).

- `detect_document_class()` (in `document_parser.py`) classifies content as
  INVOICE / SI / BL.
- Error codes: `empty_text`, `wrong_document_type`, `unrecognized_layout`.
- Warning codes: `missing_field`, `document_type_mismatch`.
- `status` is `error` / `warning` / `ok`.

### SI/BL Verification and Comparison

`services/verification_service.py` calls
`services/comparison_engine.py`, which compares SI and BL `ShipmentFields` using
`services/field_normalizer.py`, then persists the decision in `Verification`:

- party names (shipper/consignee/notify) via `names_match` (fuzzy + legal-suffix
  synonyms)
- ports via `compare_ports` (LOCODE + city/country, `needs_review` for
  code/city inconsistencies)
- container count via `parse_container_count`
- gross weight via `parse_gross_weight_kg` (kg conversion + tolerance)

Returns `status` (OK / MISMATCH / NEEDS_REVIEW), `has_defect`, `defect_fields`,
`mismatch_details`, `missing_fields`, `review_reason`, `review_details`.

`VerificationService` maps those comparison statuses to `MATCH`, `MISMATCH`, or
`REVIEW`, calculates a confidence score, stores a verification hash, and resets
any previous reviewer decision when a fresh extraction changes the result.

Verification endpoints:

```text
GET  /api/verification/{email_id}
POST /api/verification/{email_id}/review
GET  /api/verification/{email_id}/report.pdf
```

The review endpoint accepts `{"action": "approve"}` or
`{"action": "correct", "corrected_fields": {...}}`. The PDF endpoint uses
`services/pdf_report.py` to render the email metadata, verdict, confidence,
review status, SI/BL field comparison, and mismatch or missing-field notes.

The classification workbench serializes the current verification and exposes it
to the UI for review actions and report downloads. Comparison behavior is
covered by `tests/test_field_normalizer.py`, including integration checks
against real SI/BL attachment pairs.

### Audit Trail

Endpoints:

```text
GET /audit
GET /api/audit-events
GET /api/audit-events/{event_id}
```

`services/audit_service.py` writes append-only `AuditEvent` rows for
classification, document registration, extraction completion, verification
completion, approval, and correction. Verification audit payloads snapshot the
SI/BL extraction fields, normalized values, mismatch details, missing fields,
review details, corrected fields, verification hash, and process timestamps at
the moment of the event.

The `/audit` page adds a Compliance section in the left navigation. It supports
search/filtering by event type, result, reviewer status, email ID, hash, and date
range. The detail panel shows the immutable payload, full hash with copy action,
UTC process timeline, field comparison, review notes, and a report download link
when a verification record exists.

## Data Model Links

- `EmailMessage` has many `Document` rows through `email_id`.
- `EmailMessage` has many `Extraction` rows through `email_id`.
- `EmailMessage` has many `Verification` rows through `email_id`.
- `AuditEvent` stores immutable process/review history for an email and may link
  to a document, extraction, or verification row.
- `Document` has many `Extraction` rows through `document_id`.
- `Document` may have many `Verification` rows through `document_id`.
- `Extraction` stores one document's extracted fields plus validation metadata
  (status, detected type, errors, warnings, method, processed_at).
- `Verification` stores the SI/BL comparison status, mismatch fields, confidence,
  reviewer status, corrected fields, and a hash of the compared extraction data.
- `Verification.reviewed_at` stores the latest human review timestamp; historical
  review events live in `AuditEvent`.

## Hackathon Bundle Links

The project folder contains the input bundle:

```text
loader.py
inbox/*.json
attachments/*
sample_submission.json
```

`DATA_SOURCE` points to the project folder by default. `InboxService` imports
`loader.py` dynamically from `DATA_SOURCE`. Docker sets `DATA_SOURCE=/app`.

## Common Commands

```powershell
# Run app (from Averis_Project)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload

# Import/reimport bundle data
.\.venv\Scripts\python.exe scripts\import_input_data.py --reset

# Run tests
.\.venv\Scripts\python.exe -m unittest discover -s tests

# Compile check
.\.venv\Scripts\python.exe -m compileall app models routers services scripts tests
```

## Agent Notes

- Do not commit `.env`, `averis.db`, `uploads/`, `.venv/`, or `__pycache__/`.
- Run the app from `Averis_Project` — `DATABASE_URL` is `sqlite:///./averis.db`
  and resolves relative to the current working directory.
- Add new user-facing API routes in `routers/api.py` unless they are HTML page
  routes.
- Add persistent entities in `models/`, import them in `app/database.py`
  `init_db()`, and add a `_ensure_*_columns()` migration for new columns on an
  existing table.
- Put business logic in `services/`, not directly in routers.
- Keep category names exactly as the hackathon contract expects:
  `BL_COMPARISON`, `SI_REQUEST`, `INVOICE_QUERY`, `GENERAL`, `SPAM`.
- OCR uses EasyOCR + PyMuPDF (no external binary); the first use downloads models
  to `~/.EasyOCR`. Scanned PDFs have no text layer and rely on this path.
- Verification logic lives in `verification_service.py`, with comparison helpers
  in `comparison_engine.py` + `field_normalizer.py`. It is invoked after
  extraction and exposed through the API and classification workbench.
- Audit events are append-only. Do not edit or delete `AuditEvent` rows for
  normal application workflows.
