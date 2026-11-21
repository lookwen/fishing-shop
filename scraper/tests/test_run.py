import os
from pathlib import Path
from types import SimpleNamespace

from scraper import run


def setup_run(monkeypatch, tmp_path, fresh=False):
    output = tmp_path / "products.json"
    monkeypatch.setattr(run, "REPOSITORY_ROOT", tmp_path)
    monkeypatch.setattr(
        run, "get_settings", lambda: SimpleNamespace(output_path=output)
    )
    monkeypatch.setattr(run.sys, "argv", ["run.py", "--fresh"] if fresh else ["run.py"])
    monkeypatch.setenv("SCRAPER_OUTPUT_PATH", str(output))
    return output


def test_partial_export_continues_to_images(monkeypatch, tmp_path):
    output = setup_run(monkeypatch, tmp_path)
    calls = []

    def execute(command, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            output.write_text("{}", encoding="utf-8")
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run.subprocess, "run", execute)
    assert run.main() == 0
    assert len(calls) == 2
    assert Path(calls[1][1]).name == "images.py"


def test_stale_export_does_not_start_images(monkeypatch, tmp_path):
    output = setup_run(monkeypatch, tmp_path)
    output.write_text("old", encoding="utf-8")
    calls = []

    def execute(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(run.subprocess, "run", execute)
    assert run.main() == 1
    assert len(calls) == 1
    assert output.read_text(encoding="utf-8") == "old"


def test_fresh_run_preserves_existing_results_and_isolates_cache(monkeypatch, tmp_path):
    output = setup_run(monkeypatch, tmp_path, fresh=True)
    output.write_text("old", encoding="utf-8")
    environments = []

    def execute(command, **kwargs):
        environment = kwargs["env"]
        environments.append(environment)
        target = Path(environment["SCRAPER_OUTPUT_PATH"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(run.subprocess, "run", execute)
    assert run.main() == 0
    assert len(environments) == 2
    assert environments[0] == environments[1]
    directory = Path(environments[0]["SCRAPER_OUTPUT_PATH"]).parent
    assert directory.name.startswith("run-")
    assert Path(environments[0]["SCRAPER_CACHE_DIR"]) == directory / "pages"
    assert output.read_text(encoding="utf-8") == "old"
    assert os.environ["SCRAPER_OUTPUT_PATH"] == str(output)


def test_image_failure_is_returned(monkeypatch, tmp_path):
    output = setup_run(monkeypatch, tmp_path)
    calls = []

    def execute(command, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            output.write_text("{}", encoding="utf-8")
            return SimpleNamespace(returncode=0)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(run.subprocess, "run", execute)
    assert run.main() == 1
    assert len(calls) == 2
