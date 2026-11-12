"""Load scraper settings from environment variables and config/.env."""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPOSITORY_ROOT / "scraper" / "config" / ".env"
load_dotenv(ENV_FILE, override=False)


def _path_from_env(name: str, default: str) -> Path:
    value = Path(os.getenv(name, default)).expanduser()
    return value.resolve() if value.is_absolute() else (REPOSITORY_ROOT / value).resolve()


@dataclass(frozen=True)
class Settings:
    source_url: str
    output_path: Path
    log_path: Path
    user_agent: str


def get_settings() -> Settings:
    source_url = os.getenv("SCRAPER_SOURCE_URL", "https://flyhouse.pl/pl/").strip()
    parsed_url = urlparse(source_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("SCRAPER_SOURCE_URL must be an absolute HTTP or HTTPS URL")

    user_agent = os.getenv(
        "SCRAPER_USER_AGENT",
        "FishingShopEducationalScraper/1.0 (contact: replace-with-team-contact)",
    ).strip()
    if not user_agent:
        raise ValueError("SCRAPER_USER_AGENT cannot be empty")

    return Settings(
        source_url=source_url,
        output_path=_path_from_env(
            "SCRAPER_OUTPUT_PATH", "scraper-results/products.json"
        ),
        log_path=_path_from_env(
            "SCRAPER_LOG_PATH", "scraper/logs/scraper.log"
        ),
        user_agent=user_agent,
    )
