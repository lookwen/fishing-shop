import argparse
import json
import re
import subprocess
from pathlib import Path
from time import perf_counter

if __package__:
    from .backup import ROOT, SETTINGS, Store, validate_backup, validate_settings
else:
    from backup import ROOT, SETTINGS, Store, validate_backup, validate_settings


def require_empty_project(project):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project):
        raise ValueError("Invalid Compose project name")
    result = subprocess.run(
        [
            "docker",
            "ps",
            "--all",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ],
        check=True,
        stdout=subprocess.PIPE,
    )
    if result.stdout.strip():
        raise ValueError(
            "The target project already has containers; use a new project name"
        )
    result = subprocess.run(
        [
            "docker",
            "volume",
            "ls",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ],
        check=True,
        stdout=subprocess.PIPE,
    )
    if result.stdout.strip():
        raise ValueError(
            "The target project already has volumes; use a new project name"
        )
    for name in ("db_data", "shop_data", "shop_tls"):
        result = subprocess.run(
            ["docker", "volume", "inspect", f"{project}_{name}"],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            raise ValueError("The target volume already exists; use a new project name")


def restore_backup(store, directory, project):
    manifest = validate_backup(directory)
    require_empty_project(project)
    store.run("build", "shop")
    store.run("up", "-d", "--wait", "--wait-timeout", "180", "db")
    with (directory / "database.sql").open("rb") as source:
        store.run(
            "exec",
            "-T",
            "db",
            "bash",
            "-euc",
            'MYSQL_PWD="$MYSQL_PASSWORD" exec mysql --user="$MYSQL_USER" "$MYSQL_DATABASE"',
            stdin=source,
        )
    store.tar(directory / "shop.tar.gz", "/var/www/html", restore=True)
    store.tar(directory / "tls.tar.gz", "/etc/apache2/local-tls", restore=True)
    settings = json.loads((directory / "settings.json").read_text(encoding="utf-8"))
    restored = store.php("restore", settings, helper=True)
    if (
        any(
            restored["counts"].get(name) != count
            for name, count in manifest["counts"].items()
        )
        or any(
            restored.get("fingerprints", {}).get(name) != value
            for name, value in manifest.get("fingerprints", {}).items()
        )
        or restored["prestashop_version"] != manifest["prestashop_version"]
    ):
        raise ValueError(
            "Restored record counts, fingerprints or PrestaShop version do not match the backup"
        )
    store.run("up", "-d", "--wait", "--wait-timeout", "300")
    return restored


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path, nargs="?")
    parser.add_argument("--project")
    parser.add_argument("--env-file", type=Path, default=ROOT / "deploy/.env")
    parser.add_argument("--settings-only", action="store_true")
    args = parser.parse_args()
    if not args.settings_only and (not args.backup or not args.project):
        parser.error("Provide a backup directory and a new --project name")
    started = perf_counter()
    try:
        store = Store(args.project, args.env_file)
        if args.settings_only:
            settings = validate_settings(
                json.loads(SETTINGS.read_text(encoding="utf-8"))
            )
            restored = store.php("apply", settings)
        else:
            restored = restore_backup(store, args.backup.resolve(), args.project)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Restore failed: {error}")
        return 1
    print(f"Restored records: {restored['counts']}")
    print(f"Restore time: {(perf_counter() - started) / 60:.2f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
