import argparse
import os
import shutil
import subprocess
import sys
from time import perf_counter

if __package__:
    from .src.settings import REPOSITORY_ROOT, get_settings
else:
    from src.settings import REPOSITORY_ROOT, get_settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--restart-fresh", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    environment = os.environ.copy()
    output = settings.output_path
    fresh_directory = REPOSITORY_ROOT / "scraper/cache/fresh-run"
    if args.fresh or args.restart_fresh:
        if (args.restart_fresh or not fresh_directory.exists()) and fresh_directory.exists():
            shutil.rmtree(fresh_directory)
        fresh_directory.mkdir(parents=True, exist_ok=True)
        environment.update(
            {
                "SCRAPER_CACHE_DIR": str(fresh_directory / "pages"),
                "SCRAPER_LOG_PATH": str(fresh_directory / "scraper.log"),
                "SCRAPER_PROGRESS_PATH": str(fresh_directory / "products-progress.json"),
            }
        )
    cache_path = environment.get("SCRAPER_CACHE_DIR")
    if cache_path is None:
        cache_path = str(getattr(settings, "cache_dir", REPOSITORY_ROOT / "scraper/cache/pages"))
    print(f"Wyniki: {output.parent}; cache: {cache_path}", flush=True)
    marker = fresh_directory / "export-ready" if (args.fresh or args.restart_fresh) else None
    had_ready_export = marker is not None and marker.exists()
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
    data_returncode = result.returncode
    new_export = output.exists() and output.stat().st_mtime_ns != previous
    if result.returncode not in (0, 1) or not output.exists() or (not new_export and not had_ready_export):
        print("Brak poprawnego eksportu. Sprawdź log etapu danych.", flush=True)
        return 1
    if marker is not None:
        marker.touch()
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
    if marker is not None and result.returncode == 0 and data_returncode == 0:
        shutil.rmtree(fresh_directory, ignore_errors=True)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
