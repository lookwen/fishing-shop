import argparse
import base64
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "deploy/shop-settings.json"
FILES = ("database.sql", "shop.tar.gz", "tls.tar.gz", "settings.json")
PUBLIC_KEYS = {
    "PS_SHOP_NAME",
    "PS_WEIGHT_UNIT",
    "PS_TAX",
    "PS_INVOICE",
    "PS_CONDITIONS",
    "PS_SHIPPING_FREE_PRICE",
    "PS_SHIPPING_FREE_WEIGHT",
    "PS_SHIPPING_HANDLING",
    "PS_DETECT_LANG",
    "PS_DETECT_COUNTRY",
    "PS_CATALOG_MODE",
}


def validate_settings(data):
    if data.get("version") != 1 or set(data.get("settings", {})) != PUBLIC_KEYS:
        raise ValueError("Invalid public settings export")
    if any(
        not isinstance(value, (str, int, float, bool))
        for value in data["settings"].values()
    ):
        raise ValueError("Invalid public setting value")
    return data


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_backup(directory):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != 1 or set(manifest.get("files", {})) != set(FILES):
        raise ValueError("Invalid or incomplete backup")
    for name in FILES:
        if checksum(directory / name) != manifest["files"][name]:
            raise ValueError(f"Backup checksum mismatch: {name}")
    validate_settings(
        json.loads((directory / "settings.json").read_text(encoding="utf-8"))
    )
    return manifest


class Store:
    def __init__(self, project=None, env_file=ROOT / "deploy/.env"):
        env_file = Path(env_file).resolve()
        if not env_file.is_file():
            raise ValueError(f"Missing configuration: {env_file}")
        self.command = ["docker", "compose", "--env-file", str(env_file)]
        if project:
            self.command += ["--project-name", project]
        self.command += ["-f", str(ROOT / "deploy/compose.yaml")]

    def run(self, *arguments, **options):
        return subprocess.run(
            self.command + list(arguments), cwd=ROOT, check=True, **options
        )

    def php(self, action, settings=None, helper=False):
        payload = base64.b64encode(json.dumps(settings or {}).encode()).decode()
        environment = [
            "-e",
            f"FISHING_BACKUP_ACTION={action}",
            "-e",
            f"FISHING_BACKUP_SETTINGS={payload}",
        ]
        if helper:
            command = [
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "--user",
                "www-data",
                "--entrypoint",
                "php",
                *environment,
                "shop",
            ]
        else:
            command = ["exec", "-T", "--user", "www-data", *environment, "shop", "php"]
        result = self.run(
            *command,
            input=(ROOT / "deploy/backup-settings.php").read_bytes(),
            stdout=subprocess.PIPE,
        )
        return json.loads(result.stdout)

    def tar(self, path, destination, restore=False):
        mode = "rb" if restore else "wb"
        with path.open(mode) as stream:
            self.run(
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "--entrypoint",
                "tar",
                "shop",
                *(
                    ["-xzf", "-", "-C", destination]
                    if restore
                    else [
                        "--exclude=./var/cache/*",
                        "--exclude=./var/logs/*",
                        "-czf",
                        "-",
                        "-C",
                        destination,
                        ".",
                    ]
                ),
                **({"stdin": stream} if restore else {"stdout": stream}),
            )


def create_backup(store, directory):
    running = (
        store.run("ps", "--status", "running", "--services", stdout=subprocess.PIPE)
        .stdout.decode()
        .split()
    )
    if not {"db", "shop"} <= set(running):
        raise ValueError("Start the database and shop before creating a backup")
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    store.run("stop", "shop")
    try:
        exported = store.php("export", helper=True)
        public = validate_settings({"version": 1, "settings": exported["settings"]})
        (directory / "settings.json").write_text(
            json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        with (directory / "database.sql").open("wb") as output:
            store.run(
                "exec",
                "-T",
                "db",
                "bash",
                "-euc",
                'MYSQL_PWD="$MYSQL_PASSWORD" exec mysqldump --user="$MYSQL_USER" '
                "--single-transaction --routines --events --triggers --no-tablespaces "
                '--set-gtid-purged=OFF --hex-blob "$MYSQL_DATABASE"',
                stdout=output,
            )
        store.tar(directory / "shop.tar.gz", "/var/www/html")
        store.tar(directory / "tls.tar.gz", "/etc/apache2/local-tls")
        manifest = {
            "version": 1,
            "created_at": datetime.now().astimezone().isoformat(),
            "prestashop_version": exported["prestashop_version"],
            "counts": exported["counts"],
            "fingerprints": exported.get("fingerprints", {}),
            "files": {name: checksum(directory / name) for name in FILES},
        }
        (directory / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        SETTINGS.write_text(
            json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    finally:
        store.run("start", "shop")
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project")
    parser.add_argument("--env-file", type=Path, default=ROOT / "deploy/.env")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    name = datetime.now().strftime("backup-%Y%m%d-%H%M%S-%f")
    directory = (args.output or ROOT / "deploy/backups" / name).resolve()
    try:
        manifest = create_backup(Store(args.project, args.env_file), directory)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Backup failed: {error}")
        return 1
    print(f"Backup: {directory}")
    print(f"Records: {manifest['counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
