from io import BytesIO
from random import Random
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from PIL import Image

from scraper.src.fetcher import FetchError
from scraper.src.images import (
    MAX_BYTES,
    create_archive,
    download_images,
    image_name,
    prepare_image,
    restore_archive,
    valid_image,
)


def image_bytes(size=(1000, 900), mode="RGB"):
    output = BytesIO()
    Image.new(mode, size, "white").save(output, "PNG")
    return output.getvalue()


def product(identifier, count=2):
    return {
        "source_id": identifier,
        "images": [
            {
                "source_url": f"https://example.test/{identifier}/{i}.jpg",
                "position": i + 1,
            }
            for i in range(count)
        ],
    }


class Fetcher:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def fetch_page(self, url):
        self.calls.append(url)
        response = self.responses.get(url, image_bytes())
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(body=response)


@pytest.mark.parametrize("size", [(2400, 1800), (900, 1200), (800, 600)])
def test_resize_dimensions_format_and_size(size):
    result = prepare_image(image_bytes(size, "RGBA"))
    with Image.open(BytesIO(result)) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"
        assert 800 <= max(image.size) <= 1600
    assert len(result) <= MAX_BYTES


def test_compresses_detailed_image_below_limit():
    image = Image.frombytes("RGB", (1600, 1600), Random(1).randbytes(1600 * 1600 * 3))
    source = BytesIO()
    image.save(source, "PNG")
    result = prepare_image(source.getvalue())
    assert len(result) <= MAX_BYTES
    with Image.open(BytesIO(result)) as image:
        assert 800 <= max(image.size) <= 1600


def test_rejects_thumbnail_and_non_image():
    with pytest.raises(ValueError, match="below 800"):
        prepare_image(image_bytes((300, 200)))
    with pytest.raises(OSError):
        prepare_image(b"<html>Not an image</html>")


def test_download_counts_resume_and_archive(tmp_path):
    catalog = {"products": [product(str(i)) for i in range(55)]}
    directory = tmp_path / "images"
    fetcher = Fetcher()
    report = download_images(catalog, fetcher, directory)
    assert report["products_without_image"] == []
    assert report["products_with_two_images"] == 50
    assert len(fetcher.calls) == 105
    calls = list(fetcher.calls)
    for item in catalog["products"]:
        for image in item["images"]:
            image.pop("local_path", None)
    assert download_images(catalog, fetcher, directory) == report
    assert fetcher.calls == calls
    archive_path = tmp_path / "product-images.zip"
    create_archive(catalog, directory, archive_path)
    with ZipFile(archive_path) as archive:
        assert len(archive.namelist()) == 105
        assert all(name.startswith("images/") for name in archive.namelist())
    assert len(list((tmp_path / "sample-images").glob("*.jpg"))) == 20
    restored_directory = tmp_path / "restored" / "images"
    restore_archive(
        "https://example.test/archive.zip",
        Fetcher({"https://example.test/archive.zip": archive_path.read_bytes()}),
        catalog,
        restored_directory,
    )
    no_network = Fetcher()
    assert download_images(catalog, no_network, restored_directory) == report
    assert no_network.calls == []


def test_falls_back_to_next_source_and_next_double_product(tmp_path):
    first, second = product("first", 3), product("second")
    fetcher = Fetcher(
        {
            first["images"][0]["source_url"]: image_bytes((300, 300)),
            first["images"][1]["source_url"]: FetchError("HTTP 404"),
        }
    )
    catalog = {"products": [first, second]}
    report = download_images(catalog, fetcher, tmp_path / "images", double_count=1)
    assert report["products_without_image"] == []
    assert report["products_with_two_images"] == 1
    assert first["images"][2]["local_path"]
    assert all(image["local_path"] for image in second["images"])


def test_reports_unmet_requirements_and_deduplicates_urls(tmp_path):
    item = product("missing", 1)
    repeated = product("repeated", 1)
    repeated["images"].append(dict(repeated["images"][0], position=2))
    fetcher = Fetcher({item["images"][0]["source_url"]: FetchError("HTTP 404")})
    report = download_images(
        {"products": [item, repeated]}, fetcher, tmp_path / "images"
    )
    assert report["products_without_image"] == ["missing"]
    assert report["products_with_two_images"] == 0
    assert report["required_with_two_images"] == 50


def test_redownloads_corrupt_local_file_and_ignores_temporary_file(tmp_path):
    item = product("test", 1)
    directory = tmp_path / "images"
    directory.mkdir()
    path = directory / image_name(item, item["images"][0])
    path.write_bytes(b"broken")
    path.with_suffix(".tmp").write_bytes(b"partial download")
    assert not valid_image(path)
    fetcher = Fetcher()
    download_images({"products": [item]}, fetcher, directory, double_count=0)
    assert len(fetcher.calls) == 1
    assert valid_image(path)


def test_archive_failure_falls_back_to_source(tmp_path):
    catalog = {"products": [product("test", 1)]}
    fetcher = Fetcher({"https://example.test/archive.zip": FetchError("HTTP 404")})
    directory = tmp_path / "images"
    restore_archive("https://example.test/archive.zip", fetcher, catalog, directory)
    report = download_images(catalog, fetcher, directory, double_count=0)
    assert report["products_without_image"] == []
    assert len(fetcher.calls) == 2


def test_ten_image_downloads_can_run_concurrently(tmp_path):
    from threading import Barrier

    barrier = Barrier(10)

    class ConcurrentFetcher:
        def fetch_page(self, url):
            barrier.wait(timeout=5)
            return SimpleNamespace(body=image_bytes())

    catalog = {"products": [product(str(i), 1) for i in range(10)]}
    report = download_images(
        catalog,
        ConcurrentFetcher(),
        tmp_path / "images",
        double_count=0,
        max_workers=10,
    )
    assert report["products_without_image"] == []
    assert len(list((tmp_path / "images").glob("*.jpg"))) == 10
