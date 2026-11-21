"""Scraper entry point and logging setup."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from catalog import CachedPageSource, discover_catalog, validate_catalog, write_catalog
from fetcher import FetchError, PageFetcher
from jsonschema.exceptions import ValidationError
from products import extract_products
from settings import get_settings

LOGGER = logging.getLogger(__name__)
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema.json"


def configure_logging(log_path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    file_handler = RotatingFileHandler(
        log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)


def main() -> int:
    try:
        settings = get_settings()
    except ValueError:
        logging.basicConfig(level=logging.ERROR)
        LOGGER.exception("Invalid scraper configuration")
        return 2

    configure_logging(settings.log_path)
    logger = logging.getLogger("scraper")
    logger.info("Scraper run started")
    logger.info("Source URL: %s", settings.source_url)
    logger.info("Configured output path: %s", settings.output_path)
    logger.info("Log file: %s", settings.log_path)
    logger.info("Page cache: %s", settings.cache_dir)
    logger.info("User-Agent: %s", settings.user_agent)
    logger.info("Request rate limit: at most 2 requests per second")
    logger.info("Product workers: %s", settings.workers)
    logger.info("Maximum retries per request: %s", settings.max_retries)
    fetcher = PageFetcher(
        user_agent=settings.user_agent,
        timeout_seconds=settings.request_timeout_seconds,
        max_retries=settings.max_retries,
    )
    try:
        page_source = CachedPageSource(fetcher, settings.cache_dir)
        catalog = discover_catalog(settings.source_url, page_source)
        report = extract_products(catalog, page_source, SCHEMA_PATH, settings.workers)
        report_path = settings.output_path.with_name(
            settings.output_path.stem + "-report.json"
        )
        write_catalog(report, report_path)
        logger.info("Product issues report written to %s", report_path)
        validate_catalog(catalog, SCHEMA_PATH)
        write_catalog(catalog, settings.output_path)
    except (FetchError, ValidationError, ValueError, OSError) as exc:
        logger.error("Catalog extraction failed: %s", exc)
        return 1

    logger.info("Discovered %s categories", len(catalog["categories"]))
    logger.info("Discovered %s product listing URLs", len(catalog["product_listings"]))
    logger.info("Exported %s products; rejected %s", report["exported"], report["rejected"])
    logger.info("UTF-8 catalog written to %s", settings.output_path)
    logger.info("Scraper run finished")
    return 1 if report["rejected"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
