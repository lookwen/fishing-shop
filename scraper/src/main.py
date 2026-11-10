"""Scraper entry point and logging setup."""

import logging
from logging.handlers import RotatingFileHandler

from settings import get_settings


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
        logging.exception("Invalid scraper configuration")
        return 2

    configure_logging(settings.log_path)
    logger = logging.getLogger("scraper")
    logger.info("Scraper run started")
    logger.info("Source URL: %s", settings.source_url)
    logger.info("Configured output path: %s", settings.output_path)
    logger.info("Log file: %s", settings.log_path)
    logger.info("User-Agent configured: %s", settings.user_agent)
    logger.info(
        "Setup is ready; product fetching and output generation are not implemented yet"
    )
    logger.info("Scraper run finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
