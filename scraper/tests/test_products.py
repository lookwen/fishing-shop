"""Product parsing and report tests; no network access or disk output."""

import json
from html import escape
from itertools import pairwise
from pathlib import Path

import pytest

from scraper.src.catalog import validate_catalog
from scraper.src.fetcher import FetchError
from scraper.src.products import _number, extract_products, parse_product

SCHEMA = Path(__file__).parents[1] / "schema.json"
LISTING = {
    "source_id": "product-existing-id",
    "name": "Listing name",
    "url": "https://flyhouse.pl/pl/product.html",
    "category_ids": ["category-1"],
}


def page(**overrides):
    data = {
        "name": "Wędka testowa",
        "description_short": "<p>Krótki opis</p>",
        "description": "<p>Pełny <b>opis</b>.</p>",
        "price_amount": 1230,
        "price_tax_exc": 1000,
        "rate": 23,
        "price": "1 230,00 zł",
        "reference": "ABC",
        "manufacturer_name": "Orvis",
        "features": [{"name": "Waga", "value": "250 g"}],
        "images": [
            {
                "bySize": {
                    "small": {"url": "/small.jpg", "width": 100, "height": 100},
                    "large": {"url": "/large.jpg", "width": 1200, "height": 1200},
                }
            }
        ],
    }
    data.update(overrides)
    return (
        '<div id="product-details" data-product="'
        + escape(json.dumps(data))
        + '"></div>'
    )


def catalog():
    return {
        "source": {"name": "Flyhouse", "base_url": "https://flyhouse.pl"},
        "categories": [
            {
                "source_id": "category-1",
                "name": "Test",
                "url": "https://flyhouse.pl/pl/test/",
                "parent_source_id": None,
            }
        ],
        "products": [],
        "product_listings": [dict(LISTING)],
    }


class Pages:
    def __init__(self, html=None, error=None):
        self.html, self.error = html, error
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        if self.error:
            raise self.error
        return self.html.encode("utf-8")


def test_embedded_details_preserve_ids_and_validate():
    result = parse_product(page(), LISTING)
    assert result["source_id"] == LISTING["source_id"]
    assert result["category_ids"] == LISTING["category_ids"]
    assert result["description"] == "Krótki opis\n\nPełny opis ."
    assert result["price_gross"] == 1230
    assert result["vat_rate"] == 23
    assert result["weight_kg"] == 0.25
    assert result["images"] == [
        {"source_url": "https://flyhouse.pl/large.jpg", "position": 1}
    ]
    data = catalog()
    data["products"] = [result]
    validate_catalog(data, SCHEMA)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1\u00a0234,56 zł", 1234.56),
        ("1.234,56 PLN", 1234.56),
        ("439.02439", 439.02439),
        (0, 0),
        ("-2", None),
        ("NaN", None),
        ("Infinity", None),
        (True, None),
        ("23%", 23),
    ],
)
def test_number_formats(value, expected):
    assert _number(value) == expected


def test_missing_required_fields_are_reported_with_partial_record():
    data = catalog()
    report = extract_products(
        data, Pages(page(description="", description_short="", images=[])), SCHEMA
    )
    assert data["products"] == []
    assert report["rejected"] == 1
    assert report["issues"][0]["missing_required_fields"] == ["description", "images"]
    assert report["issues"][0]["partial_product"]["name"] == "Wędka testowa"
    validate_catalog(data, SCHEMA)


def test_zero_price_and_missing_optional_fields_are_valid():
    data = catalog()
    source = Pages(page(price_amount=0, rate=None, tax_name="", weight=0, features=[]))
    report = extract_products(data, source, SCHEMA)
    assert report["rejected"] == 0
    assert source.calls == [LISTING["url"]]
    assert data["products"][0]["price_gross"] == 0
    assert data["products"][0]["vat_rate"] is None
    assert data["products"][0]["weight_kg"] is None


def test_fetch_failure_does_not_stop_other_products():
    class MixedPages:
        def get(self, url):
            if url == LISTING["url"]:
                raise FetchError("HTTP 404")
            return page().encode("utf-8")

    data = catalog()
    data["product_listings"].append(
        dict(LISTING, source_id="second", url="https://flyhouse.pl/second.html")
    )
    report = extract_products(data, MixedPages(), SCHEMA)
    assert report["exported"] == report["rejected"] == 1
    assert report["issues"][0]["error"] == "HTTP 404"
    assert data["products"][0]["source_id"] == "second"


def test_extract_products_resumes_from_utf8_progress_without_fetching_saved_records(tmp_path):
    data = catalog()
    second = dict(LISTING, source_id="product-second", url="https://flyhouse.pl/second.html")
    data["product_listings"].append(second)
    checkpoint = tmp_path / "products-progress.json"
    checkpoint.write_text(
        json.dumps(
            {"version": 1, "products": [parse_product(page(), LISTING)], "issues": []},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    resumed_source = Pages(page())
    resumed = catalog()
    resumed["product_listings"].append(second)
    report = extract_products(resumed, resumed_source, SCHEMA, progress_path=checkpoint)
    assert resumed_source.calls == [second["url"]]
    assert report["exported"] == 2
    raw = checkpoint.read_bytes()
    assert "Wędka".encode() in raw
    assert json.loads(raw.decode("utf-8"))["products"][0]["name"] == "Wędka testowa"


def test_transient_fetch_failure_is_retried_on_resume(tmp_path):
    checkpoint = tmp_path / "progress.json"
    failed = extract_products(catalog(), Pages(error=FetchError("temporary")), SCHEMA,
                              progress_path=checkpoint)
    assert failed["rejected"] == 1
    succeeding = Pages(page())
    recovered = extract_products(catalog(), succeeding, SCHEMA, progress_path=checkpoint)
    assert succeeding.calls == [LISTING["url"]]
    assert recovered["exported"] == 1


def test_html_fallback_ignores_related_product_prices_and_images():
    html = """<h1>Produkt</h1><div id="description"><div class="product-description">Opis</div></div>
    <div class="product-prices"><meta itemprop="priceCurrency" content="PLN">
    <span itemprop="price" content="123">123,00 zł</span><p class="price_netto">100,00 zł Netto</p></div>
    <div class="product-cover"><img data-image-large-src="/product.jpg"></div>
    <article class="product-miniature"><span itemprop="price" content="999"></span><img src="/other.jpg"></article>"""
    product = parse_product(html, LISTING)
    assert product["price_gross"] == 123
    assert product["price_net"] == 100
    assert product["images"] == [
        {"source_url": "https://flyhouse.pl/product.jpg", "position": 1}
    ]


def test_variants_keep_real_combinations_and_current_price():
    html = (
        page()
        + """<table class="atribute-table"><thead><tr>
    <th></th><th>Klasa</th><th>Dostępność</th><th>Cena</th><th></th></tr></thead><tbody>
    <tr><td></td><td>WF 3</td><td>14 dni</td><td><span class="regular-price">600,00 zł</span>
    <span>540,00 zł</span></td><td><a data-id-product-attribute="550"></a></td></tr>
    </tbody></table>"""
    )
    product = parse_product(html, LISTING)
    assert product["variants"] == [
        {
            "source_id": "product-existing-id-variant-550",
            "attributes": {"Klasa": "WF 3"},
            "price_gross": 540,
            "availability_text": "14 dni",
        }
    ]


def test_invalid_currency_is_reported_without_assuming_pln():
    html = (
        page(price="123 EUR")
        + '<div class="product-prices"><meta itemprop="priceCurrency" content="EUR"></div>'
    )
    report = extract_products(catalog(), Pages(html), SCHEMA)
    assert report["rejected"] == 1
    assert report["issues"][0]["validation_errors"][0]["path"] == "currency"


def test_missing_product_name_is_not_hidden_by_listing_fallback():
    report = extract_products(catalog(), Pages(page(name="")), SCHEMA)
    assert "name" in report["issues"][0]["missing_required_fields"]


def test_malformed_embedded_json_falls_back_to_html():
    result = parse_product(
        '<div id="product-details" data-product="broken"></div><h1>Produkt</h1>',
        LISTING,
    )
    assert result["name"] == "Produkt"
    assert result["price_gross"] is None


def test_brand_is_read_from_product_manufacturer_not_recommendations():
    html = (
        page(manufacturer_name=None)
        + """<div class="product-manufacturer">
    <a itemprop="brand"><meta itemprop="name" content="Orvis"></a></div>
    <article class="product-miniature"><a itemprop="brand">
    <meta itemprop="name" content="Other"></a></article>"""
    )
    assert parse_product(html, LISTING)["brand"] == "Orvis"


def test_explicit_weight_in_description_is_converted_without_using_line_class():
    product = parse_product(
        page(features=[], description="<p>Waga: 180 g.</p>"), LISTING
    )
    assert product["weight_kg"] == 0.18
    product = parse_product(
        page(features=[], description="<p>Głowica 180 grain, 15 m</p>"), LISTING
    )
    assert product["weight_kg"] is None


def test_four_downloads_run_concurrently_and_keep_export_order():
    from threading import Barrier

    barrier = Barrier(4)

    class ConcurrentPages:
        def get(self, url):
            barrier.wait(timeout=5)
            return page(name="Produkt testowy").encode("utf-8")

    data = catalog()
    data["product_listings"] = [
        dict(LISTING, source_id=f"product-{i}", url=f"https://flyhouse.pl/{i}.html")
        for i in range(4)
    ]
    report = extract_products(data, ConcurrentPages(), SCHEMA, max_workers=4)
    assert report["exported"] == 4
    assert [p["source_id"] for p in data["products"]] == [
        f"product-{i}" for i in range(4)
    ]


def test_parallel_export_equals_sequential_export():
    sequential, parallel = catalog(), catalog()
    listings = [dict(LISTING, source_id=f"product-{i}") for i in range(9)]
    sequential["product_listings"] = parallel["product_listings"] = listings
    first = extract_products(sequential, Pages(page()), SCHEMA, max_workers=1)
    second = extract_products(parallel, Pages(page()), SCHEMA, max_workers=4)
    assert first == second
    assert sequential == parallel


def test_concurrent_requests_share_one_rate_limit(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace

    from scraper.src import fetcher

    now, starts = [1.0], []

    def advance(seconds):
        now[0] += seconds

    def monotonic():
        return now[0]

    monkeypatch.setattr(
        fetcher, "time", SimpleNamespace(monotonic=monotonic, sleep=advance)
    )
    client = fetcher.PageFetcher("TestScraper/1.0")

    # The second monotonic read in each limiter call records its reserved start.
    def recorded_monotonic():
        value = monotonic()
        starts.append(value)
        return value

    monkeypatch.setattr(fetcher.time, "monotonic", recorded_monotonic)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _: client._wait_for_rate_limit(), range(8)))
    reserved = starts[1::2]
    assert len(reserved) == 8
    assert all(b - a >= 0.5 for a, b in pairwise(reserved))


def test_concurrent_robots_checks_fetch_policy_once(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from email.message import Message

    from scraper.src.fetcher import PageFetcher, PageResponse

    client = PageFetcher("TestScraper/1.0")
    calls = []

    def policy(url, **kwargs):
        calls.append(url)
        return PageResponse(
            url, 200, Message(), b"User-agent: *\nDisallow: /private/\n"
        )

    monkeypatch.setattr(client, "_request_following_redirects", policy)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(client._check_robots, [LISTING["url"]] * 8))
    assert calls == ["https://flyhouse.pl/robots.txt"]
    with pytest.raises(FetchError, match="robots.txt disallows"):
        client._check_robots("https://flyhouse.pl/private/page")
