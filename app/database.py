from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import get_settings


settings = get_settings()

connect_args = (
    {"check_same_thread": False, "timeout": 30}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(settings.database_url, connect_args=connect_args)


if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _configure_sqlite(connection, _connection_record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db() -> None:
    import models.email_message  # noqa: F401
    import models.document  # noqa: F401
    import models.extraction  # noqa: F401
    import models.verification  # noqa: F401
    import models.audit_event  # noqa: F401
    import models.submission_entry  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_email_classification_columns()
    _ensure_extraction_columns()
    _ensure_verification_columns()


def _ensure_email_classification_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    inspector = inspect(engine)
    if "email_messages" not in inspector.get_table_names():
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns("email_messages")
    }
    migrations = {
        "category": "ALTER TABLE email_messages ADD COLUMN category VARCHAR(50)",
        "classification_confidence": (
            "ALTER TABLE email_messages ADD COLUMN classification_confidence FLOAT"
        ),
        "classification_source": (
            "ALTER TABLE email_messages ADD COLUMN classification_source VARCHAR(50)"
        ),
        "classified_at": "ALTER TABLE email_messages ADD COLUMN classified_at DATETIME",
    }

    with engine.begin() as connection:
        for column_name, statement in migrations.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))


def _ensure_extraction_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    inspector = inspect(engine)
    if "extractions" not in inspector.get_table_names():
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns("extractions")
    }
    migrations = {
        "status": "ALTER TABLE extractions ADD COLUMN status VARCHAR(50)",
        "detected_document_type": (
            "ALTER TABLE extractions ADD COLUMN detected_document_type VARCHAR(50)"
        ),
        "errors": "ALTER TABLE extractions ADD COLUMN errors JSON",
        "warnings": "ALTER TABLE extractions ADD COLUMN warnings JSON",
        "normalized_fields": (
            "ALTER TABLE extractions ADD COLUMN normalized_fields JSON"
        ),
    }

    with engine.begin() as connection:
        for column_name, statement in migrations.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))


def _ensure_verification_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    inspector = inspect(engine)
    if "verifications" not in inspector.get_table_names():
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns("verifications")
    }
    migrations = {
        "si_document_id": (
            "ALTER TABLE verifications ADD COLUMN si_document_id INTEGER"
        ),
        "bl_document_id": (
            "ALTER TABLE verifications ADD COLUMN bl_document_id INTEGER"
        ),
        "mismatch_details": (
            "ALTER TABLE verifications ADD COLUMN mismatch_details JSON"
        ),
        "review_details": (
            "ALTER TABLE verifications ADD COLUMN review_details JSON"
        ),
        "missing_fields": (
            "ALTER TABLE verifications ADD COLUMN missing_fields JSON"
        ),
        "corrected_fields": (
            "ALTER TABLE verifications ADD COLUMN corrected_fields JSON"
        ),
        "verification_hash": (
            "ALTER TABLE verifications ADD COLUMN verification_hash VARCHAR(64)"
        ),
        "reviewed_at": "ALTER TABLE verifications ADD COLUMN reviewed_at DATETIME",
    }

    with engine.begin() as connection:
        for column_name, statement in migrations.items():
            if column_name not in existing_columns:
                connection.execute(text(statement))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
