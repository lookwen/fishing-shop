"""Parser tests use checked-in HTML fixtures and never access the network."""

from pathlib import Path

from scraper.src.catalog import (
    parse_category_menu,
    parse_pagination_links,
    parse_product_listings,
    validate_catalog,
)

FIXTURES = Path(__file__).parents[1] / "examples"
BASE_URL = "https://flyhouse.pl/pl/"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_category_menu_keeps_names_urls_and_parent_relationships() -> None:
    categories = parse_category_menu(read_fixture("category-menu.html"), BASE_URL)

    assert [category["name"] for category in categories] == [
        "Wędki",
        "Wędki Orvis",
        "Wędki jednoręczne",
        "Wędki ECHO",
    ]
    assert categories[0]["url"] == "https://flyhouse.pl/pl/wedki/"
    assert categories[0]["parent_source_id"] is None
    assert categories[1]["parent_source_id"] == categories[0]["source_id"]
    assert categories[2]["parent_source_id"] == categories[1]["source_id"]
    assert categories[3]["parent_source_id"] == categories[0]["source_id"]


def test_parse_product_listing_cards_returns_unique_product_names_and_urls() -> None:
    products = parse_product_listings(
        read_fixture("category-listing.html"),
        "https://flyhouse.pl/pl/wedki-orvis/",
        "category-orvis",
    )

    assert [product["name"] for product in products] == [
        "Wędka Orvis Model One",
        "Wędka Orvis Model Two",
    ]
    assert products[0]["url"] == "https://flyhouse.pl/pl/wedki-orvis/model-one.html"
    assert all(product["category_ids"] == ["category-orvis"] for product in products)


def test_parse_pagination_links_resolves_next_page_url() -> None:
    links = parse_pagination_links(
        read_fixture("category-listing.html"),
        "https://flyhouse.pl/pl/wedki-orvis/",
    )

    assert links == ["https://flyhouse.pl/pl/wedki-orvis/?page=2"]


def test_discovered_catalog_records_validate_against_export_schema() -> None:
    categories = parse_category_menu(read_fixture("category-menu.html"), BASE_URL)
    products = parse_product_listings(
        read_fixture("category-listing.html"),
        "https://flyhouse.pl/pl/wedki-orvis/",
        str(categories[1]["source_id"]),
    )
    catalog = {
        "source": {"name": "Flyhouse", "base_url": "https://flyhouse.pl"},
        "categories": categories,
        "products": [],
        "product_listings": products,
    }

    validate_catalog(catalog, Path(__file__).parents[1] / "schema.json")
