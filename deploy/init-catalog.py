"""Prepare the scraper export and stream it to the running PrestaShop service."""

import argparse
import json
import logging
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from hashlib import sha256
from pathlib import Path

from dotenv import dotenv_values
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scraper"))

from src.catalog import validate_catalog
from src.fetcher import PageFetcher
from src.images import (
    download_images,
    image_name,
    local_images,
    restore_archive,
    valid_image,
)
from src.settings import get_settings

RESULTS = ROOT / "scraper-results"
CACHE = ROOT / "deploy" / "cache" / "catalog"
LOGGER = logging.getLogger("deploy.catalog")
COMPOSE = [
    "docker",
    "compose",
    "--env-file",
    "deploy/.env",
    "-f",
    "deploy/compose.yaml",
]
IMPORT = """
set -eu
stage=$(mktemp -d)
trap 'rm -f "$stage/catalog.json" "$stage"/images/*.jpg; rmdir "$stage/images" "$stage" 2>/dev/null || true' EXIT
tar -xf - -C "$stage"
php /usr/local/share/fishing-shop/import-catalog.php "$stage"
"""


def prepare_catalog(catalog):
    """Check source relationships and put parents before their children."""
    categories = {entry["source_id"]: entry for entry in catalog["categories"]}
    products = {entry["source_id"]: entry for entry in catalog["products"]}
    if len(categories) != len(catalog["categories"]) or len(products) != len(
        catalog["products"]
    ):
        raise ValueError("Duplicate category or product source_id")

    ordered = {}
    visiting = set()

    def add_category(source_id):
        if source_id in ordered:
            return
        if source_id in visiting or source_id not in categories:
            raise ValueError(f"Cycle or unknown parent category: {source_id}")
        visiting.add(source_id)
        entry = categories[source_id]
        parent = entry["parent_source_id"]
        if parent is not None:
            add_category(parent)
        ordered[source_id] = entry
        visiting.remove(source_id)

    for source_id in categories:
        add_category(source_id)

    used = set()
    for product in products.values():
        for source_id in product["category_ids"]:
            if source_id not in categories:
                raise ValueError(
                    f"{product['source_id']}: unknown category {source_id}"
                )
            while source_id is not None and source_id not in used:
                used.add(source_id)
                source_id = categories[source_id]["parent_source_id"]

    populated_children = Counter(
        categories[source_id]["parent_source_id"] for source_id in used
    )
    qualifying = sum(
        populated_children[source_id] >= 2
        for source_id, entry in categories.items()
        if entry["parent_source_id"] is None
    )
    if qualifying < 4:
        raise ValueError(
            f"Only {qualifying} root categories have two populated subcategories"
        )

    for source_id, entry in ordered.items():
        entry["active"] = source_id in used
    catalog["categories"] = list(ordered.values())

    # Rank by a stable hash to get an exact share, including after input reordering.
    ranked = sorted(products, key=lambda key: (sha256(key.encode()).digest(), key))
    unavailable = round(len(ranked) / 10)
    for index, source_id in enumerate(ranked):
        digest = sha256(source_id.encode()).digest()
        products[source_id]["quantity"] = (
            0 if index < unavailable else 1 + int.from_bytes(digest[-4:], "big") % 10
        )

    discovered = len(catalog.get("product_listings", []))
    LOGGER.info(
        "Export: %d products, %d listings, %d categories, %d qualifying roots, %d out of stock",
        len(products),
        discovered,
        len(categories),
        qualifying,
        unavailable,
    )
    if len(products) < 1000:
        LOGGER.info(
            "Export contains %d products (below the 1000-product target); "
            "catalog coverage is documented in README.",
            len(products),
        )


def prepare_images(catalog, directory, archive_url):
    settings = get_settings()
    fetcher = PageFetcher(
        settings.user_agent,
        settings.request_timeout_seconds,
        settings.max_retries,
    )
    directory.mkdir()
    cache = CACHE / "images"
    cache.mkdir(parents=True, exist_ok=True)
    reused = set()
    for product in catalog["products"]:
        for image in product["images"]:
            name = image_name(product, image)
            for origin in (cache, RESULTS / "images"):
                if valid_image(origin / name):
                    shutil.copyfile(origin / name, directory / name)
                    if origin == cache:
                        reused.add(name)
                    break

    if archive_url:
        # A fully prepared local cache also makes reruns independent of the network.
        counts = [
            len(
                {
                    image_name(product, image)
                    for image in product["images"]
                    if (directory / image_name(product, image)).is_file()
                }
            )
            for product in catalog["products"]
        ]
        if 0 in counts or sum(count >= 2 for count in counts) < 50:
            try:
                restore_archive(archive_url, fetcher, catalog, directory)
            except RuntimeError as error:
                LOGGER.warning(
                    "Cannot restore ZIP entries. Using source images: %s", error
                )

    for product in catalog["products"]:
        for image in product["images"]:
            name = image_name(product, image)
            image["local_path"] = (
                f"images/{name}" if valid_image(directory / name) else None
            )
        product["images"].sort(
            key=lambda image: (not image["local_path"], image["position"])
        )
    report = download_images(catalog, fetcher, directory, max_workers=settings.workers)
    for product in catalog["products"]:
        prepared = {path.name for path in local_images(product, directory)}
        by_name = {}
        for image in sorted(product["images"], key=lambda entry: entry["position"]):
            name = image_name(product, image)
            if name in prepared:
                by_name.setdefault(
                    name, {"file": name, "source_url": image["source_url"]}
                )
        product["prepared_images"] = list(by_name.values())

    # Keep successfully prepared files even if another product is missing an image.
    for file in directory.glob("*.jpg"):
        if file.name not in reused and valid_image(file):
            with tempfile.NamedTemporaryFile(dir=cache, delete=False) as output:
                temporary = Path(output.name)
                with file.open("rb") as source:
                    shutil.copyfileobj(source, output)
            try:
                temporary.replace(cache / file.name)
            finally:
                temporary.unlink(missing_ok=True)
    return report


def import_catalog(catalog, directory):
    with tempfile.TemporaryFile() as payload:
        (directory / "catalog.json").write_text(
            json.dumps(catalog, ensure_ascii=False),
            encoding="utf-8",
        )
        with tarfile.open(fileobj=payload, mode="w") as archive:
            archive.add(directory / "catalog.json", arcname="catalog.json")
            for product in catalog["products"]:
                for image in product["prepared_images"]:
                    name = image["file"]
                    archive.add(directory / "images" / name, arcname=f"images/{name}")
        payload.seek(0)
        subprocess.run(
            [*COMPOSE, "exec", "-T", "--user", "www-data", "shop", "sh", "-c", IMPORT],
            cwd=ROOT,
            stdin=payload,
            check=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive-url", help="Override CATALOG_IMAGES_ARCHIVE_URL in deploy/.env"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.getLogger("scraper.fetcher").setLevel(logging.WARNING)
    try:
        catalog = json.loads((RESULTS / "products.json").read_text(encoding="utf-8"))
        validate_catalog(catalog, ROOT / "scraper" / "schema.json")
        prepare_catalog(catalog)
        config = dotenv_values(ROOT / "deploy" / ".env", interpolate=False)
        archive_url = args.archive_url or config.get("CATALOG_IMAGES_ARCHIVE_URL")
        subprocess.run(
            [
                *COMPOSE,
                "exec",
                "-T",
                "--user",
                "www-data",
                "shop",
                "test",
                "-r",
                "/usr/local/share/fishing-shop/import-catalog.php",
            ],
            cwd=ROOT,
            check=True,
        )
        CACHE.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=CACHE) as work:
            directory = Path(work)
            report = prepare_images(catalog, directory / "images", archive_url)
            LOGGER.info(
                "Images: %d prepared, %d products without a photo, %d with at least two, %d download errors",
                sum(len(product["prepared_images"]) for product in catalog["products"]),
                len(report["products_without_image"]),
                report["products_with_two_images"],
                len(report["errors"]),
            )
            if (
                report["products_without_image"]
                or report["products_with_two_images"] < 50
            ):
                raise ValueError(
                    f"Image requirements failed. Missing: {report['products_without_image']}"
                )
            import_catalog(catalog, directory)
    except subprocess.CalledProcessError as error:
        LOGGER.error(
            "PrestaShop command failed (exit %d). Check the output above.",
            error.returncode,
        )
        return 1
    except (OSError, ValueError, ValidationError) as error:
        LOGGER.error("Catalog initialization failed: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
