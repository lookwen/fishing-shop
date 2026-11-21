import argparse
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from shutil import copyfile
from zipfile import ZIP_STORED, BadZipFile, ZipFile

from PIL import Image, ImageOps

if __package__:
    from .catalog import validate_catalog, write_catalog
    from .fetcher import FetchError, PageFetcher
    from .settings import get_settings
else:
    from catalog import validate_catalog, write_catalog
    from fetcher import FetchError, PageFetcher
    from settings import get_settings

LOGGER = logging.getLogger("scraper.images")
MAX_BYTES = 300_000


def image_name(product, image):
    key = product["source_id"] + ":" + image["source_url"]
    return sha256(key.encode("utf-8")).hexdigest()[:24] + ".jpg"


def valid_image(path):
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        return False
    try:
        with Image.open(path) as image:
            valid = image.format == "JPEG" and 800 <= max(image.size) <= 1600
            image.load()
            return valid
    except (OSError, ValueError):
        return False


def prepare_image(body):
    with Image.open(BytesIO(body)) as source:
        rgba = ImageOps.exif_transpose(source).convert("RGBA")
    if max(rgba.size) < 800:
        raise ValueError("Source image has a longest side below 800 px")
    image = Image.new("RGB", rgba.size, "white")
    image.paste(rgba, mask=rgba.getchannel("A"))
    for longest in (1600, 1200, 800):
        image.thumbnail((longest, longest), Image.Resampling.LANCZOS)
        for quality in (90, 80, 70, 60, 50, 40):
            output = BytesIO()
            image.save(output, format="JPEG", quality=quality, optimize=True)
            if output.tell() <= MAX_BYTES:
                return output.getvalue()
    raise ValueError("Cannot compress image to 300 KB")


def save_image(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(body)
    temporary.replace(path)


def download_product_images(product, fetcher, directory, minimum):
    errors, seen = [], set()
    downloaded = 0
    for image in product["images"]:
        url = image["source_url"]
        if url in seen:
            image.pop("local_path", None)
            continue
        seen.add(url)
        path = directory / image_name(product, image)
        image.pop("local_path", None)
        try:
            if not valid_image(path):
                save_image(path, prepare_image(fetcher.fetch_page(url).body))
            image["local_path"] = f"images/{path.name}"
            downloaded += 1
            if downloaded >= minimum:
                break
        except (FetchError, OSError, ValueError) as exc:
            LOGGER.warning(
                "Image failed for %s: %s (%s)", product["source_id"], url, exc
            )
            errors.append(
                {"source_id": product["source_id"], "url": url, "error": str(exc)}
            )
    return errors


def local_images(product, directory):
    return list(
        dict.fromkeys(
            directory / image_name(product, image)
            for image in product["images"]
            if image.get("local_path")
            and valid_image(directory / image_name(product, image))
        )
    )


def download_images(catalog, fetcher, directory, double_count=50, max_workers=10):
    products = catalog["products"]
    for product in products:
        for image in product["images"]:
            image.pop("local_path", None)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = executor.map(
            lambda product: download_product_images(product, fetcher, directory, 1),
            products,
        )
        errors = [error for result in results for error in result]
    doubled = 0
    for product in products:
        if doubled >= double_count:
            break
        if len({image["source_url"] for image in product["images"]}) < 2:
            continue
        errors.extend(download_product_images(product, fetcher, directory, 2))
        doubled += len(local_images(product, directory)) >= 2
    missing = [
        product["source_id"]
        for product in products
        if not local_images(product, directory)
    ]
    return {
        "total": len(products),
        "products_without_image": missing,
        "products_with_two_images": sum(
            len(local_images(product, directory)) >= 2 for product in products
        ),
        "required_with_two_images": double_count,
        "errors": errors,
    }


def restore_archive(url, fetcher, catalog, directory):
    try:
        with ZipFile(BytesIO(fetcher.fetch_page(url).body)) as archive:
            names = set(archive.namelist())
            for product in catalog["products"]:
                for image in product["images"]:
                    path = directory / image_name(product, image)
                    name = f"images/{path.name}"
                    if name in names and not valid_image(path):
                        save_image(path, archive.read(name))
    except (FetchError, OSError, BadZipFile) as exc:
        LOGGER.warning("Archive unavailable; downloading source images: %s", exc)


def create_archive(catalog, directory, archive_path):
    paths = list(
        dict.fromkeys(
            path
            for product in catalog["products"]
            for path in local_images(product, directory)
        )
    )
    if sum(path.stat().st_size for path in paths) + len(paths) * 200 > 1_000_000_000:
        raise ValueError("Image archive would exceed 1 GB")
    temporary = archive_path.with_suffix(".tmp")
    with ZipFile(temporary, "w", compression=ZIP_STORED) as archive:
        for path in paths:
            archive.write(path, f"images/{path.name}")
    if temporary.stat().st_size > 1_000_000_000:
        raise ValueError("Image archive exceeds 1 GB")
    temporary.replace(archive_path)
    samples = directory.parent / "sample-images"
    samples.mkdir(parents=True, exist_ok=True)
    for index, path in enumerate(paths[:20], start=1):
        copyfile(path, samples / f"{index:02}.jpg")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-url")
    args = parser.parse_args()
    settings = get_settings()
    settings.log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(
                settings.log_path.with_name("images.log"), encoding="utf-8"
            ),
        ],
    )
    catalog = json.loads(settings.output_path.read_text(encoding="utf-8"))
    schema = Path(__file__).resolve().parents[1] / "schema.json"
    validate_catalog(catalog, schema)
    directory = settings.output_path.parent / "images"
    fetcher = PageFetcher(
        settings.user_agent, settings.request_timeout_seconds, settings.max_retries
    )
    if args.archive_url:
        restore_archive(args.archive_url, fetcher, catalog, directory)
    LOGGER.info("Image workers: %s", settings.workers)
    report = download_images(catalog, fetcher, directory, max_workers=settings.workers)
    validate_catalog(catalog, schema)
    write_catalog(catalog, settings.output_path)
    write_catalog(report, settings.output_path.with_name("images-report.json"))
    if report["products_without_image"] or report["products_with_two_images"] < 50:
        LOGGER.error("Image requirements not met; see images-report.json")
        return 1
    archive_path = settings.output_path.parent / "product-images.zip"
    create_archive(catalog, directory, archive_path)
    LOGGER.info("Images ready: %s products; archive: %s", report["total"], archive_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
