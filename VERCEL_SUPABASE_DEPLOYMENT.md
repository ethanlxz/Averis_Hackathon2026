# Vercel + Supabase Deployment Checklist

Use this setup when the live demo should read preloaded data from Supabase and
does not need to re-run import, extraction, OCR, or verification on Vercel.

## Target Architecture

- Run the full pipeline locally or in a controlled environment.
- Store final app data in Supabase Postgres.
- Deploy the FastAPI UI/API to Vercel.
- Let Vercel read from Supabase during the demo.

## 1. Use Supabase Postgres

Do not use the local SQLite database on Vercel.

Local SQLite:

```text
averis.db
```

Production database:

```env
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/postgres
```

Add the Postgres driver to deployment dependencies:

```text
psycopg[binary]>=3.2
```

## 2. Preload Supabase Before the Demo

Run the import, extraction, verification, and submission refresh before the live
demo, with `DATABASE_URL` pointed at Supabase.

Example:

```powershell
$env:DATABASE_URL="postgresql+psycopg://USER:PASSWORD@HOST:5432/postgres"
.\.venv\Scripts\python.exe -c "from app.database import init_db; init_db()"
```

Then run the local workflow needed to populate:

- `email_messages`
- `documents`
- `extractions`
- `verifications`
- `submission_entries`
- any audit rows you want visible

For the demo, Vercel should only display this preloaded data.

## 3. Do Not Depend On Local Files In Production

These local files are not suitable as production dependencies on Vercel:

```text
averis.db
inbox/
attachments/
uploads/
.env
```

If Supabase is already populated, the deployed app does not need the hackathon
bundle files to show the dashboard, classifications, verification results, audit
data, or submission JSON.

## 4. Keep Vercel Dependencies Lightweight

For a preloaded demo, avoid deploying heavy OCR/PDF extraction dependencies unless
you truly need live extraction on Vercel.

Avoid or remove for Vercel demo builds:

```text
easyocr
PyMuPDF
pdfplumber
pypdf
Pillow
```

Keep dependencies needed for the web app and Supabase:

```text
fastapi>=0.115
uvicorn[standard]>=0.30
sqlalchemy>=2.0
pydantic>=2.0
jinja2>=3.1
python-multipart>=0.0.20
psycopg[binary]>=3.2
python-docx>=1.1
openpyxl>=3.1
reportlab>=4.0
```

## 5. Add A Vercel Python Entrypoint

Create `pyproject.toml` in `Averis_Project`:

```toml
[project]
name = "averis-demo"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "sqlalchemy>=2.0",
  "pydantic>=2.0",
  "jinja2>=3.1",
  "python-multipart>=0.0.20",
  "psycopg[binary]>=3.2",
  "python-docx>=1.1",
  "openpyxl>=3.1",
  "reportlab>=4.0"
]

[project.scripts]
app = "app.main:app"
```

## 6. Configure Vercel Environment Variables

Set these in the Vercel project settings:

```env
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/postgres
UPLOAD_DIR=/tmp/uploads
DATA_SOURCE=disabled
DEEPSEEK_API_KEY=
```

`DEEPSEEK_API_KEY` is optional for a read-only preloaded demo. Add it only if you
want live classification or extraction-assisted LLM calls.

## 7. Avoid Reset Or Heavy Processing Routes During Demo

For a preloaded live demo, avoid using routes/actions that reset or recompute the
database:

```text
POST /api/import-input-data?reset=true
POST /api/extract-all
POST /api/classify-imported-emails
```

Safe demo routes include:

```text
GET /
GET /classification
GET /audit
GET /api/submission
GET /api/classification-summary
GET /api/verification/{email_id}
```

## 8. Deploy From The Project Folder

Install and log in to Vercel:

```powershell
npm i -g vercel
vercel login
```

Deploy from `Averis_Project`:

```powershell
cd C:\Users\ethan\Downloads\sdoc-hackathon-bundle\Averis_Project
vercel
vercel --prod
```

## Demo Rule Of Thumb

Use this flow:

```text
Local pipeline -> Supabase DB filled -> Vercel reads Supabase -> live UI demo
```

That keeps the demo fast, stable, and free from serverless file-system or OCR
runtime issues.
