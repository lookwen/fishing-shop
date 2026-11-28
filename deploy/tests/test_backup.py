import json
import subprocess
from types import SimpleNamespace

import pytest

from deploy import backup, restore


def settings():
    return json.loads(backup.SETTINGS.read_text(encoding="utf-8"))


class Store:
    def __init__(self, public, fail_dump=False):
        self.public = public
        self.calls = []
        self.fail_dump = fail_dump
        self.exported = {
            "settings": public["settings"],
            "counts": {"product": 915, "image": 965},
            "prestashop_version": "8.2.8",
        }

    def run(self, *args, **options):
        self.calls.append(args)
        if args[0] == "ps":
            return SimpleNamespace(stdout=b"db\nshop\n")
        if args[:3] == ("exec", "-T", "db") and "stdout" in options:
            if self.fail_dump:
                raise subprocess.CalledProcessError(1, ["mysqldump"])
            options["stdout"].write(b"CREATE TABLE restored (id INT);\n")
        return SimpleNamespace(stdout=b"")

    def php(self, action, public=None, helper=False):
        self.calls.append(("php", action))
        return self.exported

    def tar(self, path, destination, restore=False):
        self.calls.append(("tar", destination, restore))
        if not restore:
            path.write_bytes(b"archive data")


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    public = settings()
    monkeypatch.setattr(backup, "SETTINGS", tmp_path / "public-settings.json")
    directory = tmp_path / "backup"
    store = Store(public)
    backup.create_backup(store, directory)
    return directory, store


def test_backup_has_complete_checksums_and_only_public_settings(snapshot):
    directory, store = snapshot
    manifest = backup.validate_backup(directory)
    assert manifest["counts"] == {"product": 915, "image": 965}
    assert set(manifest["files"]) == set(backup.FILES)
    public = json.loads(backup.SETTINGS.read_text(encoding="utf-8"))
    assert set(public) == {"version", "settings"}
    assert set(public["settings"]) == backup.PUBLIC_KEYS
    assert store.calls.index(("stop", "shop")) < store.calls.index(("php", "export"))
    assert store.calls[-1] == ("start", "shop")


def test_changed_backup_is_rejected_before_restore(snapshot, monkeypatch):
    directory, store = snapshot
    (directory / "database.sql").write_bytes(b"changed")
    calls = []
    monkeypatch.setattr(
        restore, "require_empty_project", lambda project: calls.append(project)
    )
    with pytest.raises(ValueError, match="checksum mismatch"):
        restore.restore_backup(store, directory, "new-shop")
    assert calls == []


def test_failed_dump_restarts_original_shop(tmp_path, monkeypatch):
    public = settings()
    monkeypatch.setattr(backup, "SETTINGS", tmp_path / "public-settings.json")
    store = Store(public, fail_dump=True)
    directory = tmp_path / "backup"
    with pytest.raises(subprocess.CalledProcessError):
        backup.create_backup(store, directory)
    assert store.calls[-1] == ("start", "shop")
    assert not (directory / "manifest.json").exists()
    assert not backup.SETTINGS.exists()


def test_settings_export_rejects_secrets_and_unknown_keys():
    public = settings()
    public["settings"]["PS_MAIL_PASSWD"] = "must-not-be-exported"
    with pytest.raises(ValueError, match="Invalid public"):
        backup.validate_settings(public)


@pytest.mark.parametrize("existing", ["containers", "volumes", "unlabelled-volume"])
def test_restore_rejects_existing_target(monkeypatch, existing):
    def run(command, **options):
        if command[1] == "ps":
            return SimpleNamespace(
                stdout=b"container" if existing == "containers" else b"", returncode=0
            )
        if command[1:3] == ["volume", "ls"]:
            return SimpleNamespace(
                stdout=b"volume" if existing == "volumes" else b"", returncode=0
            )
        return SimpleNamespace(
            stdout=b"", returncode=0 if existing == "unlabelled-volume" else 1
        )

    monkeypatch.setattr(restore.subprocess, "run", run)
    with pytest.raises(ValueError, match="already"):
        restore.require_empty_project("restore-shop")


def test_restore_rejects_invalid_project_without_docker(monkeypatch):
    with pytest.raises(ValueError, match="Invalid Compose"):
        restore.require_empty_project("../deploy")


def test_restore_imports_files_and_verifies_records(snapshot, monkeypatch):
    directory, store = snapshot
    store.calls.clear()
    checked = []
    monkeypatch.setattr(
        restore, "require_empty_project", lambda project: checked.append(project)
    )
    result = restore.restore_backup(store, directory, "new-shop")
    assert checked == ["new-shop"]
    assert result["counts"] == {"product": 915, "image": 965}
    assert ("tar", "/var/www/html", True) in store.calls
    assert ("tar", "/etc/apache2/local-tls", True) in store.calls
    assert store.calls[-1] == ("up", "-d", "--wait", "--wait-timeout", "300")


def test_wrong_restored_counts_do_not_start_shop(snapshot, monkeypatch):
    directory, store = snapshot
    store.calls.clear()
    store.exported["counts"] = {"product": 1, "image": 1}
    monkeypatch.setattr(restore, "require_empty_project", lambda project: None)
    with pytest.raises(ValueError, match="counts"):
        restore.restore_backup(store, directory, "new-shop")
    assert not any(
        call[:4] == ("up", "-d", "--wait", "--wait-timeout") and call[-1] == "300"
        for call in store.calls
    )


def test_existing_backup_is_not_overwritten(snapshot):
    directory, store = snapshot
    before = (directory / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        backup.create_backup(store, directory)
    assert (directory / "manifest.json").read_bytes() == before
