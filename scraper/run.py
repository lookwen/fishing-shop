import argparse
import os
import subprocess
import sys
from time import perf_counter
from uuid import uuid4

if __package__:
    from .src.settings import REPOSITORY_ROOT, get_settings
else:
    from src.settings import REPOSITORY_ROOT, get_settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    environment = os.environ.copy()
    output = settings.output_path
    if args.fresh:
        directory = REPOSITORY_ROOT / "scraper/cache" / f"run-{uuid4().hex[:8]}"
        output = directory / "products.json"
        environment.update(
            {
                "SCRAPER_OUTPUT_PATH": str(output),
                "SCRAPER_CACHE_DIR": str(directory / "pages"),
                "SCRAPER_LOG_PATH": str(directory / "scraper.log"),
            }
        )
    print(f"Wyniki: {output.parent}", flush=True)
    previous = output.stat().st_mtime_ns if output.exists() else None
    started = perf_counter()
    result = subprocess.run(
        [sys.executable, str(REPOSITORY_ROOT / "scraper/src/main.py")],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=False,
    )
    data_minutes = (perf_counter() - started) / 60
    print(f"Dane: {data_minutes:.2f} min; kod: {result.returncode}", flush=True)
    if (
        result.returncode not in (0, 1)
        or not output.exists()
        or output.stat().st_mtime_ns == previous
    ):
        print("Brak nowego eksportu. Sprawdź log etapu danych.", flush=True)
        return 1
    images_started = perf_counter()
    result = subprocess.run(
        [sys.executable, str(REPOSITORY_ROOT / "scraper/src/images.py")],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=False,
    )
    print(
        f"Zdjęcia: {(perf_counter() - images_started) / 60:.2f} min; kod: {result.returncode}"
    )
    print(f"Łącznie: {(perf_counter() - started) / 60:.2f} min")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
