# Averis Veritas

Phase 1 FastAPI foundation for Averis Veritas.

## Run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then open `http://127.0.0.1:8000`.

## Configuration

Application settings are loaded from `.env` in this project folder. The file is
ignored by git so secrets stay local. Use `.env.example` as the template.

Set your DeepSeek key in `.env`:

```env
DEEPSEEK_API_KEY="paste-your-key-here"
```

Supported settings:

- `APP_NAME`
- `APP_VERSION`
- `DATABASE_URL`
- `DATA_SOURCE`
- `UPLOAD_DIR`
- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_MODEL`
- `DEEPSEEK_TIMEOUT_SECONDS`
- `OCR_PROVIDER`
- `OCR_LANG`
- `OPENAI_API_KEY`
- `OPENAI_OCR_MODEL`

## Import the hackathon input data

The root bundle contains `loader.py`, `inbox/`, `attachments/`, and
`sample_submission.json`. By default this app reads from the parent folder:

```bash
python scripts/import_input_data.py --reset
```

Use `DATA_SOURCE` in `.env` if the bundle lives somewhere else:

```env
DATA_SOURCE="C:\path\to\sdoc-hackathon-bundle"
```

After importing, check:

- `GET /emails`
- `GET /emails/email_004`
- `GET /documents`

## Structure

- `app/`: FastAPI entrypoint, configuration, and database setup.
- `models/`: SQLAlchemy ORM models for documents and verifications.
- `routers/`: Dashboard, document, and API routes.
- `services/`: Email classification, parsing, OCR, LLM, and comparison service seams.
- `templates/` and `static/`: Initial dashboard page assets.
