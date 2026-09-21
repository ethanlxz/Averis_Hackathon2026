import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"


def load_env_file(env_file: Path = ENV_FILE) -> None:
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = _clean_env_value(value)
        if key:
            os.environ.setdefault(key, value)


def _clean_env_value(value: str) -> str:
    value = value.strip()
    if not value:
        return ""

    quote = value[0] if value[0] in {"'", '"'} else ""
    if quote:
        end = value.find(quote, 1)
        if end != -1:
            return value[1:end]

    return value.split("#", 1)[0].strip().strip("'\"")


load_env_file()


class Settings(BaseModel):
    app_name: str = Field(
        default_factory=lambda: os.getenv(
            "APP_NAME",
            "Averis Veritas",
        )
    )
    app_version: str = Field(default_factory=lambda: os.getenv("APP_VERSION", "0.1.0"))
    database_url: str = Field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./averis.db")
    )
    deepseek_api_key: str | None = Field(
        default_factory=lambda: os.getenv("DEEPSEEK_API_KEY") or None
    )
    deepseek_base_url: str = Field(
        default_factory=lambda: os.getenv(
            "DEEPSEEK_BASE_URL",
            "https://api.deepseek.com",
        )
    )
    deepseek_model: str = Field(
        default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    )
    deepseek_timeout_seconds: int = Field(
        default_factory=lambda: int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "20"))
    )
    ocr_provider: str = Field(default_factory=lambda: os.getenv("OCR_PROVIDER", "easyocr"))
    ocr_lang: str = Field(default_factory=lambda: os.getenv("OCR_LANG", "en"))
    openai_api_key: str | None = Field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY") or None
    )
    openai_ocr_model: str = Field(
        default_factory=lambda: os.getenv("OPENAI_OCR_MODEL", "gpt-5.5")
    )
    upload_dir: Path = Field(
        default_factory=lambda: Path(os.getenv("UPLOAD_DIR", "uploads"))
    )
    data_source: str = Field(
        default_factory=lambda: os.getenv("DATA_SOURCE", str(PROJECT_ROOT))
    )

    class Config:
        arbitrary_types_allowed = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
