"""Discover category hierarchy and product listing URLs from HTML pages."""

from __future__ import annotations

import json
import logging
import re
from hashlib import sha256
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag
from jsonschema import Draft202012Validator, FormatChecker

if __package__:
    from .fetcher import PageFetcher
else:
    from fetcher import PageFetcher

LOGGER = logging.getLogger("scraper.catalog")


def _clean_text(value: str | None) -> str:
    return " ".join((value or "").split())


def _stable_id(prefix: str, url: str) -> str:
    return f"{prefix}-{sha256(url.encode('utf-8')).hexdigest()[:16]}"


def _absolute_http_url(base_url: str, href: str | None) -> str | None:
    if not href:
        return None
    url = urljoin(base_url, href.strip())
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))


def _find_category_menu(soup: BeautifulSoup) -> Tag | None:
    for selector in (
        ".category-top-menu",
        "#_desktop_top_menu ul.top-menu",
        "#_mobile_top_menu ul.top-menu",
        "ul.top-menu",
        "ul[data-depth='0']",
    ):
        menu = soup.select_one(selector)
        if menu:
            return menu
    return None


def parse_category_menu(html: str, base_url: str) -> list[dict[str, str | None]]:
    """Return menu categories with deterministic ids and parent ids."""
    soup = BeautifulSoup(html, "html.parser")
    menu = _find_category_menu(soup)
    if menu is None:
        raise ValueError("Could not find a category menu in the source HTML")

    categories: list[dict[str, str | None]] = []
    seen: set[str] = set()

    depth_items = menu.select("li[data-depth]")
    if depth_items:
        depth_ids: list[str] = []
        for item in depth_items:
            try:
                depth = max(0, int(item.get("data-depth", "0")))
            except (TypeError, ValueError):
                depth = 0
            anchor = item.select_one(".acc_header a[href]") or item.find("a", href=True)
            if anchor:
                url = _absolute_http_url(base_url, anchor.get("href"))
                name = _clean_text(anchor.get("title") or anchor.get_text(" ", strip=True))
            else:
                url, name = None, ""
            if not url or not name or url in seen:
                continue
            parent_id = (
                depth_ids[depth - 1]
                if depth > 0 and depth - 1 < len(depth_ids)
                else None
            )
            source_id = _stable_id("category", url)
            categories.append(
                {
                    "source_id": source_id,
                    "name": name,
                    "url": url,
                    "parent_source_id": parent_id,
                }
            )
            seen.add(url)
            depth_ids = depth_ids[:depth]
            depth_ids.append(source_id)
        return categories

    anchors = menu.select("a[href][data-depth]")

    if anchors:
        depth_ids: list[str] = []
        for anchor in anchors:
            try:
                depth = max(0, int(anchor.get("data-depth", "0")))
            except (TypeError, ValueError):
                depth = 0
            url = _absolute_http_url(base_url, anchor.get("href"))
            name = _clean_text(anchor.get_text(" ", strip=True))
            if not url or not name or url in seen:
                continue
            parent_id = depth_ids[depth - 1] if depth > 0 and depth - 1 < len(depth_ids) else None
            source_id = _stable_id("category", url)
            categories.append(
                {
                    "source_id": source_id,
                    "name": name,
                    "url": url,
                    "parent_source_id": parent_id,
                }
            )
            seen.add(url)
            depth_ids = depth_ids[:depth]
            depth_ids.append(source_id)
        return categories

    def visit_list(list_element: Tag, parent_id: str | None = None) -> None:
        for item in list_element.find_all("li", recursive=False):
            anchor = item.find("a", href=True, recursive=False)
            if anchor:
                url = _absolute_http_url(base_url, anchor.get("href"))
                name = _clean_text(anchor.get_text(" ", strip=True))
                current_parent = parent_id
                if url and name and url not in seen:
                    current_id = _stable_id("category", url)
                    categories.append(
                        {
                            "source_id": current_id,
                            "name": name,
                            "url": url,
                            "parent_source_id": parent_id,
                        }
                    )
                    seen.add(url)
                    current_parent = current_id
            else:
                current_parent = parent_id
            child_list = item.find("ul", recursive=False)
            if child_list:
                visit_list(child_list, current_parent)

    if not anchors:
        visit_list(menu)
    return categories


def parse_product_listings(
    html: str, page_url: str, category_id: str
) -> list[dict[str, object]]:
    """Extract product-card names and URLs from one category page."""
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("article.product-miniature, .js-product-miniature")
    products: list[dict[str, object]] = []
    seen: set[str] = set()
    for card in cards:
        link = card.select_one(
            ".product-title a[href], h2 a[href], h3 a[href], a.product-thumbnail[href]"
        )
        if link is None:
            link = next(
                (
                    anchor
                    for anchor in card.select("a[href]")
                    if urlsplit(anchor.get("href", "")).path.lower().endswith(".html")
                ),
                None,
            )
        if link is None:
            continue
        url = _absolute_http_url(page_url, link.get("href"))
        name = _clean_text(link.get("title") or link.get_text(" ", strip=True))
        if not url or not name or url in seen:
            continue
        products.append(
            {
                "source_id": _stable_id("product", url),
                "name": name,
                "url": url,
                "category_ids": [category_id],
            }
        )
        seen.add(url)
    return products


def parse_pagination_links(html: str, page_url: str) -> list[str]:
    """Extract likely next-page URLs from standard PrestaShop pagination."""
    soup = BeautifulSoup(html, "html.parser")
    candidates = soup.select(
        "a[rel='next'][href], .pagination a[href], .page-list a[href]"
    )
    urls: list[str] = []
    for link in candidates:
        href = link.get("href", "")
        label = _clean_text(link.get_text(" ", strip=True)).lower()
        rel = link.get("rel", [])
        is_next = "next" in rel if isinstance(rel, list) else rel == "next"
        if not is_next and not re.search(r"(?:page|p)=\d+", href) and label not in {
            "następna",
            "next",
            "›",
            ">",
        }:
            continue
        absolute = _absolute_http_url(page_url, href)
        if absolute and absolute not in urls:
            urls.append(absolute)
    return urls


class CachedPageSource:
    """Load saved page bodies on reruns, fetching and caching unseen URLs."""

    def __init__(self, fetcher: PageFetcher, cache_dir: Path) -> None:
        self.fetcher = fetcher
        self.cache_dir = cache_dir

    def get(self, url: str) -> bytes:
        cache_path = self.cache_dir / f"{sha256(url.encode('utf-8')).hexdigest()}.html"
        if cache_path.is_file():
            LOGGER.info("Using cached page for %s", url)
            return cache_path.read_bytes()

        response = self.fetcher.fetch_page(url)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = cache_path.with_suffix(".tmp")
        temporary_path.write_bytes(response.body)
        temporary_path.replace(cache_path)
        return response.body


def discover_catalog(
    source_url: str,
    page_source: CachedPageSource,
) -> dict[str, object]:
    """Discover category hierarchy and product URLs from the source store."""
    home_html = page_source.get(source_url).decode("utf-8", errors="replace")
    categories = parse_category_menu(home_html, source_url)
    if not categories:
        raise ValueError("The source page did not contain any categories")

    products_by_url: dict[str, dict[str, object]] = {}
    for category in categories:
        category_id = str(category["source_id"])
        category_url = str(category["url"])
        pending_urls = [category_url]
        visited_pages: set[str] = set()
        while pending_urls:
            page_url = pending_urls.pop(0)
            if page_url in visited_pages:
                continue
            visited_pages.add(page_url)
            page_html = page_source.get(page_url).decode("utf-8", errors="replace")
            for product in parse_product_listings(page_html, page_url, category_id):
                existing = products_by_url.get(str(product["url"]))
                if existing:
                    category_ids = existing["category_ids"]
                    if category_id not in category_ids:
                        category_ids.append(category_id)
                else:
                    products_by_url[str(product["url"])] = product
            for next_url in parse_pagination_links(page_html, page_url):
                if next_url not in visited_pages and next_url not in pending_urls:
                    pending_urls.append(next_url)

    return {
        "source": {
            "name": "Flyhouse",
            "base_url": f"{urlsplit(source_url).scheme}://{urlsplit(source_url).netloc}",
        },
        "categories": categories,
        "products": [],
        "product_listings": list(products_by_url.values()),
    }


def validate_catalog(data: dict[str, object], schema_path: Path) -> None:
    """Validate the catalog export using the repository JSON Schema."""
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(data)


def write_catalog(data: dict[str, object], output_path: Path) -> None:
    """Write a deterministic UTF-8 JSON catalog export atomically."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary_path.replace(output_path)
