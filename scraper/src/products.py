"""Extract product details and report records that cannot enter the catalog."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
from pathlib import Path
from threading import Lock

from bs4 import BeautifulSoup
from jsonschema import Draft202012Validator, FormatChecker

if __package__:
    from .catalog import CachedPageSource, _absolute_http_url, _clean_text
    from .fetcher import FetchError
else:
    from catalog import CachedPageSource, _absolute_http_url, _clean_text
    from fetcher import FetchError

LOGGER = logging.getLogger("scraper.products")
_PROGRESS_LOCK = Lock()


def _text(value: object) -> str:
    if value is None:
        return ""
    soup = BeautifulSoup(str(value), "html.parser")
    for node in soup.select("script, style"):
        node.decompose()
    return _clean_text(soup.get_text(" ", strip=True))


def _number(value: object) -> float | None:
    """Read nonnegative finite amounts, including Polish thousands separators."""
    if value is None or isinstance(value, bool):
        return None
    raw = re.sub(r"\s+", "", str(value))
    match = re.fullmatch(r"([+-]?\d+(?:[.,]\d+)*)(?:PLN|zł|%)?", raw)
    if not match:
        return None
    raw = match[1]
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        number = Decimal(raw)
        return float(number) if number.is_finite() and number >= 0 else None
    except InvalidOperation:
        return None


def _node_text(soup: BeautifulSoup, selector: str) -> str:
    node = soup.select_one(selector)
    return _text(node) if node else ""


def _embedded_product(soup: BeautifulSoup) -> dict:
    node = soup.select_one("#product-details[data-product]")
    if node:
        try:
            data = json.loads(node["data-product"])
            if isinstance(data, dict):
                return data
        except (ValueError, TypeError):
            LOGGER.warning("Invalid embedded product JSON; using visible HTML")
    return {}


def _attributes(soup: BeautifulSoup, data: dict) -> list[dict[str, str]]:
    result = []

    def add(name: object, value: object) -> None:
        name, value = _text(name).rstrip(":"), _text(value)
        item = {"name": name, "value": value}
        if name and value and item not in result:
            result.append(item)

    for feature in data.get("features", []) or []:
        if isinstance(feature, dict):
            add(feature.get("name"), feature.get("value"))
    for row in soup.select(".product-features li"):
        add(_node_text(row, ".name"), _node_text(row, ".value"))
    for name in soup.select(".product-features dt"):
        value = name.find_next_sibling("dd")
        if value:
            add(name, value)
    for group in soup.select(".product-variants-item"):
        label = _node_text(group, ".control-label").rstrip(":")
        values = [_text(n) for n in group.select("select option") if n.get("value")]
        if not values:
            values = [
                n.get("title") or n.get("aria-label") for n in group.select("input")
            ]
        values = list(dict.fromkeys(_text(v) for v in values if _text(v)))
        if values:
            add(label, ", ".join(values))
    return result


def _weight(data: dict, attributes: list[dict], description: str) -> float | None:
    # PrestaShop's zero often means an unset shipping weight.
    number = _number(data.get("weight"))
    if number is not None and number > 0:
        return number
    candidates = list(attributes)
    # Only explicit weight labels: a line's grain class is not product weight.
    match = re.search(
        r"\b(?:waga|masa|weight)\s*(?:produktu\s*)?[:=-]?\s*"
        r"(\d+(?:[.,]\d+)?\s*(?:kg|mg|g|lbs?|oz))\b",
        description,
        re.IGNORECASE,
    )
    if match:
        candidates.append({"name": "weight", "value": match[1]})
    for item in candidates:
        if not re.match(r"^(waga|masa|weight)(?:\b|_)", item["name"], re.IGNORECASE):
            continue
        match = re.fullmatch(
            r"\s*(\d+(?:[.,]\d+)?)\s*(kg|g|mg|lb|lbs|oz)\s*",
            item["value"],
            re.IGNORECASE,
        )
        if match:
            factors = {
                "kg": 1,
                "g": 0.001,
                "mg": 0.000001,
                "lb": 0.45359237,
                "lbs": 0.45359237,
                "oz": 0.028349523125,
            }
            return round(_number(match[1]) * factors[match[2].lower()], 9)
    return None


def _images(soup: BeautifulSoup, data: dict, url: str) -> list[dict]:
    urls = []

    def add(value: object) -> None:
        absolute = _absolute_http_url(url, value) if isinstance(value, str) else None
        if absolute and absolute not in urls:
            urls.append(absolute)

    for image in data.get("images", []) or []:
        if not isinstance(image, dict):
            continue
        sizes = [s for s in (image.get("bySize") or {}).values() if isinstance(s, dict)]
        if sizes:
            best = max(
                sizes,
                key=lambda s: (
                    (_number(s.get("width")) or 0) * (_number(s.get("height")) or 0)
                ),
            )
            add(best.get("url"))
        else:
            add((image.get("large") or {}).get("url"))
    if not urls:
        for image in soup.select(
            ".product-cover img, .product-images img, .images-container img, "
            ".pro_gallery_thumbs img"
        ):
            add(
                image.get("data-image-large-src")
                or image.get("data-large")
                or image.get("data-src")
                or image.get("src")
            )
    return [
        {"source_url": value, "position": index}
        for index, value in enumerate(urls, start=1)
    ]


def _variants(soup: BeautifulSoup, source_id: str) -> list[dict]:
    variants = []
    seen = set()
    for table in soup.select("table.atribute-table"):
        headers = [_text(cell) for cell in table.select("thead th")]
        if "Cena" not in headers or "Dostępność" not in headers:
            continue
        price_index, availability_index = (
            headers.index("Cena"),
            headers.index("Dostępność"),
        )
        for row in table.select("tbody tr"):
            cells = row.find_all("td", recursive=False)
            link = row.select_one("[data-id-product-attribute]")
            if len(cells) != len(headers) or link is None:
                continue
            identifier = str(link.get("data-id-product-attribute", ""))
            if not identifier or identifier in seen:
                continue
            price_node = cells[price_index].select_one("span:not(.regular-price)")
            price = _number(_text(price_node or cells[price_index]))
            variant = {
                "source_id": f"{source_id}-variant-{identifier}",
                "attributes": {
                    header: _text(cells[index])
                    for index, header in enumerate(headers)
                    if header
                    and index not in {price_index, availability_index}
                    and _text(cells[index])
                },
                "price_gross": price,
                "availability_text": _text(cells[availability_index]) or None,
            }
            variants.append(variant)
            seen.add(identifier)
    return variants


def parse_product(html: str, listing: dict) -> dict:
    """Build a schema-shaped record, leaving missing values visible to validation."""
    soup = BeautifulSoup(html, "html.parser")
    data = _embedded_product(soup)
    url = str(listing["url"])
    source_id = str(listing["source_id"])
    attributes = _attributes(soup, data)
    descriptions = []
    for value in (
        data.get("description_short")
        or _node_text(soup, "[id^='product-description-short']"),
        data.get("description")
        or _node_text(soup, "#description .product-description"),
    ):
        value = _text(value)
        if value and value not in descriptions:
            descriptions.append(value)
    price_node = soup.select_one(".product-prices [itemprop='price']")
    price = _number(data.get("price_amount"))
    if price is None and price_node:
        price = _number(price_node.get("content") or _text(price_node))
    if price is None:
        price = _number(data.get("price"))
    currency_node = soup.select_one(".product-prices [itemprop='priceCurrency']")
    currency = currency_node.get("content") if currency_node else None
    if not currency and "zł" in str(data.get("price", "")):
        currency = "PLN"
    vat = _number(data.get("rate"))
    if vat is None:
        match = re.search(
            r"(?:VAT|PTU)[^%\n]{0,25}?(\d+(?:[.,]\d+)?)\s*%",
            str(data.get("tax_name", "")),
            re.IGNORECASE,
        )
        vat = _number(match[1]) if match else None
    brand = data.get("manufacturer_name")
    if not brand:
        brand_node = soup.select_one(".product-manufacturer [itemprop='name'][content]")
        brand_image = soup.select_one(".product-manufacturer img[alt]")
        brand = (
            brand_node.get("content")
            if brand_node
            else brand_image.get("alt")
            if brand_image
            else None
        )
    return {
        "source_id": source_id,
        "url": url,
        "name": _text(data.get("name")) or _node_text(soup, "h1"),
        "description": "\n\n".join(descriptions),
        "price_gross": price,
        "price_net": _number(data.get("price_tax_exc"))
        if data.get("price_tax_exc") is not None
        else _number(
            _node_text(soup, ".product-prices .price_netto").replace("Netto", "")
        ),
        "currency": currency,
        "vat_rate": vat,
        "weight_kg": _weight(data, attributes, " ".join(descriptions)),
        "brand": _text(brand) or None,
        "reference": _text(data.get("reference"))
        or _node_text(soup, "#product-details .product-reference span")
        or None,
        "category_ids": list(listing.get("category_ids", [])),
        "attributes": attributes,
        "variants": _variants(soup, source_id),
        "images": _images(soup, data, url),
    }


def _product_results(
    listings: list[dict], page_source: CachedPageSource, max_workers: int
):
    """Bound in-flight work and retain listing order despite concurrent downloads."""

    def load(listing):
        try:
            html = page_source.get(listing["url"]).decode("utf-8", errors="replace")
            return listing, parse_product(html, listing), None
        except (FetchError, OSError, ValueError, TypeError) as exc:
            return listing, None, exc

    remaining = iter(listings)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        pending = deque()
        for _ in range(max_workers):
            listing = next(remaining, None)
            if listing is not None:
                pending.append(executor.submit(load, listing))
        while pending:
            result = pending.popleft().result()
            listing = next(remaining, None)
            if listing is not None:
                pending.append(executor.submit(load, listing))
            yield result


def extract_products(
    catalog: dict,
    page_source: CachedPageSource,
    schema_path: Path,
    max_workers: int = 10,
    progress_path: Path | None = None,
) -> dict:
    """Fill products with valid records and return a separate, lossless issue report."""
    if not 1 <= max_workers <= 16:
        raise ValueError("max_workers must be between 1 and 16")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(
        schema["properties"]["products"]["items"], format_checker=FormatChecker()
    )
    products_by_id: dict[str, dict] = {}
    issues_by_id: dict[str, dict] = {}
    if progress_path is not None and progress_path.is_file():
        try:
            saved = json.loads(progress_path.read_text(encoding="utf-8"))
            if saved.get("version") == 1:
                products_by_id = {
                    item["source_id"]: item
                    for item in saved.get("products", [])
                    if isinstance(item, dict) and isinstance(item.get("source_id"), str)
                }
                issues_by_id = {
                    item["source_id"]: item
                    for item in saved.get("issues", [])
                    if isinstance(item, dict) and isinstance(item.get("source_id"), str)
                }
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            LOGGER.warning("Ignoring invalid progress file %s: %s", progress_path, exc)

    def save_progress() -> None:
        if progress_path is None:
            return
        with _PROGRESS_LOCK:
            progress_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": 1,
                "products": list(products_by_id.values()),
                "issues": list(issues_by_id.values()),
            }
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=progress_path.name + ".", suffix=".tmp", dir=progress_path.parent
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                    json.dump(payload, stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                for attempt in range(5):
                    try:
                        Path(temporary_name).replace(progress_path)
                        break
                    except PermissionError:
                        if attempt == 4:
                            raise PermissionError(
                                f"Windows nie może podmienić pliku postępu {progress_path}. "
                                "Zamknij inne procesy korzystające z tego pliku i ponów uruchomienie."
                            )
                        time.sleep(0.2 * (attempt + 1))
            finally:
                Path(temporary_name).unlink(missing_ok=True)

    listings = catalog.get("product_listings", [])
    pending_listings = [
        item for item in listings
        if item["source_id"] not in products_by_id and item["source_id"] not in issues_by_id
    ]
    for listing, product, exc in _product_results(
        pending_listings, page_source, max_workers
    ):
        identifier = listing["source_id"]
        if exc is not None:
            LOGGER.error("Product extraction failed for %s: %s", listing["url"], exc)
            issues_by_id[identifier] = {
                "source_id": identifier,
                "url": listing["url"],
                "error": str(exc),
                "missing_required_fields": [],
                "validation_errors": [],
                "partial_product": None,
                "retryable": isinstance(exc, (FetchError, OSError)),
            }
            save_progress()
            continue
        errors = sorted(validator.iter_errors(product), key=lambda e: str(list(e.path)))
        if errors:
            missing = [
                field for field in validator.schema["required"]
                if product.get(field) is None or product.get(field) == "" or product.get(field) == []
            ]
            issues_by_id[identifier] = {
                "source_id": identifier,
                "url": listing["url"],
                "error": None,
                "missing_required_fields": missing,
                "validation_errors": [
                    {"path": ".".join(map(str, error.path)), "message": error.message}
                    for error in errors
                ],
                "partial_product": product,
                "retryable": False,
            }
            LOGGER.warning("Invalid product %s; missing fields: %s", listing["url"], missing)
        else:
            products_by_id[identifier] = product
            issues_by_id.pop(identifier, None)
        save_progress()

    # Transient fetch failures are recorded for the report, then retried on the next run.
    issues_by_id = {
        key: value for key, value in issues_by_id.items() if key in {x["source_id"] for x in listings}
    }
    products = [products_by_id[x["source_id"]] for x in listings if x["source_id"] in products_by_id]
    issues = [issues_by_id[x["source_id"]] for x in listings if x["source_id"] in issues_by_id]
    retryable_ids = {x["source_id"] for x in issues if x.get("retryable")}
    for identifier in retryable_ids:
        issues_by_id.pop(identifier, None)
    if retryable_ids:
        save_progress()
    catalog["products"] = products
    return {
        "total": len(listings),
        "exported": len(products),
        "rejected": len(issues),
        "issues": [{k: v for k, v in issue.items() if k != "retryable"} for issue in issues],
    }
