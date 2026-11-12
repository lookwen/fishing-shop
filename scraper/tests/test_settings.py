"""Unit tests for scraper configuration."""

import pytest

from scraper.src.settings import REPOSITORY_ROOT, get_settings


def set_valid_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPER_SOURCE_URL", "https://example.test/catalog/")
    monkeypatch.setenv("SCRAPER_OUTPUT_PATH", "build/products.json")
    monkeypatch.setenv("SCRAPER_LOG_PATH", "build/logs/scraper.log")
    monkeypatch.setenv("SCRAPER_USER_AGENT", "StudyScraper/1.0 (contact: team@example.test)")


def test_get_settings_reads_environment_and_resolves_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_environment(monkeypatch)

    settings = get_settings()

    assert settings.source_url == "https://example.test/catalog/"
    assert settings.output_path == (REPOSITORY_ROOT / "build/products.json").resolve()
    assert settings.log_path == (REPOSITORY_ROOT / "build/logs/scraper.log").resolve()
    assert settings.user_agent == "StudyScraper/1.0 (contact: team@example.test)"


@pytest.mark.parametrize("source_url", ["", "example.test", "ftp://example.test/"])
def test_get_settings_rejects_non_http_source_urls(
    monkeypatch: pytest.MonkeyPatch, source_url: str
) -> None:
    set_valid_environment(monkeypatch)
    monkeypatch.setenv("SCRAPER_SOURCE_URL", source_url)

    with pytest.raises(ValueError, match="absolute HTTP or HTTPS URL"):
        get_settings()


def test_get_settings_rejects_empty_user_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_environment(monkeypatch)
    monkeypatch.setenv("SCRAPER_USER_AGENT", "   ")

    with pytest.raises(ValueError, match="cannot be empty"):
        get_settings()
