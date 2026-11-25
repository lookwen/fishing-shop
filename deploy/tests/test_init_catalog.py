import importlib.util
import json
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / "init-catalog.py"
SPEC = importlib.util.spec_from_file_location("init_catalog", SCRIPT)
init_catalog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(init_catalog)


def test_catalog_preparation_preserves_assignments_and_reproduces_stock():
    catalog = json.loads(
        (init_catalog.RESULTS / "products.json").read_text(encoding="utf-8")
    )
    reversed_catalog = deepcopy(catalog)
    reversed_catalog["categories"].reverse()
    reversed_catalog["products"].reverse()
    assignments = {p["source_id"]: p["category_ids"] for p in catalog["products"]}

    for dataset in (catalog, reversed_catalog):
        init_catalog.prepare_catalog(dataset)
        seen = {None}
        for category in dataset["categories"]:
            assert category["parent_source_id"] in seen
            seen.add(category["source_id"])
        assert {
            p["source_id"]: p["category_ids"] for p in dataset["products"]
        } == assignments

    quantities = {p["source_id"]: p["quantity"] for p in catalog["products"]}
    assert quantities == {
        p["source_id"]: p["quantity"] for p in reversed_catalog["products"]
    }
    assert set(quantities.values()) <= set(range(11))
    assert 0.05 <= list(quantities.values()).count(0) / len(quantities) <= 0.20


def test_unknown_parent_fails_preparation():
    catalog = {
        "categories": [{"source_id": "c", "parent_source_id": "unknown"}],
        "products": [],
    }
    with pytest.raises(ValueError, match="unknown parent category"):
        init_catalog.prepare_catalog(catalog)


def test_valid_archive_image_is_reused_and_missing_image_uses_source(
    tmp_path, monkeypatch
):
    product = {
        "source_id": "p",
        "images": [
            {"source_url": "https://example.test/first.jpg", "position": 1},
            {"source_url": "https://example.test/second.jpg", "position": 2},
        ],
    }
    archive_url = "https://example.test/product-images.zip"
    image_data = BytesIO()
    Image.new("RGB", (801, 200)).save(image_data, format="JPEG")
    first, second = [
        init_catalog.image_name(product, image) for image in product["images"]
    ]
    zip_data = BytesIO()
    with ZipFile(zip_data, "w") as archive:
        archive.writestr(f"images/{first}", image_data.getvalue())
        archive.writestr(f"images/{second}", b"invalid jpeg")
    seen = []

    class Fetcher:
        def fetch_page(self, url):
            seen.append(url)
            body = zip_data if url == archive_url else image_data
            return SimpleNamespace(body=body.getvalue())

    monkeypatch.setattr(init_catalog, "PageFetcher", lambda *_: Fetcher())
    monkeypatch.setattr(init_catalog, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(init_catalog, "CACHE", tmp_path / "cache")
    report = init_catalog.prepare_images(
        {"products": [product]}, tmp_path / "stage", archive_url
    )
    assert seen == [archive_url, product["images"][1]["source_url"]]
    assert report["products_without_image"] == []
    assert report["products_with_two_images"] == 1
    assert [image["file"] for image in product["prepared_images"]] == [first, second]
    for name in (first, second):
        assert init_catalog.valid_image(init_catalog.CACHE / "images" / name)
