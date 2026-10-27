import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pytest import MonkeyPatch
from typer.testing import CliRunner

from coworld.certifier import load_executable_transcript
from coworld.cli import app
from coworld.runner.runner import EpisodeArtifacts
from coworld.upload import _certification_cache_key, _certified_manifest_cache_path


def _example_manifest(tmp_path: Path) -> Path:
    return _materialized_template(
        tmp_path,
        Path(__file__).resolve().parents[1]
        / "src"
        / "coworld"
        / "examples"
        / "paintarena"
        / "coworld_manifest_template.json",
    )


def _materialized_template(tmp_path: Path, template_path: Path) -> Path:
    manifest = json.loads(template_path.read_text(encoding="utf-8"))
    manifest["game"]["version"] = "0.1.0"
    image_placeholders = {
        "paintarena": {"{{PAINTARENA_IMAGE}}": "coworld-paintarena:latest"},
    }
    placeholders = image_placeholders[template_path.parent.name]
    game_image = manifest["game"]["runnable"]["image"]
    if game_image in placeholders:
        manifest["game"]["runnable"]["image"] = placeholders[game_image]
    for section in ("player", "commissioner", "grader", "diagnoser", "optimizer"):
        if section in manifest:
            for runnable in manifest[section]:
                image = runnable["image"]
                if image in placeholders:
                    runnable["image"] = placeholders[image]
    manifest_path = tmp_path / template_path.parent.name / "coworld_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    viewer = manifest_path.parent / manifest["game"]["replay_viewer"]["bundle"]
    viewer.mkdir(parents=True)
    (viewer / "index.html").write_text("<html></html>", encoding="utf-8")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


@pytest.mark.parametrize("payload", ["wasm", "viewer", "manifest"])
@pytest.mark.parametrize("fails", [False, True])
def test_certify_caches_exact_snapshot_during_source_mutation(
    tmp_path: Path, monkeypatch: MonkeyPatch, payload: str, fails: bool
) -> None:
    manifest_path = _example_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    manifest["reporter"] = [
        {
            "wasm": "reporter.wasm",
            "id": "recap",
            "attributes": {
                "purpose": "Summary",
                "world": "softmax:reporter@0.1.0",
                "outputs": [{"name": "summary", "type": "text", "description": "Summary"}],
            },
        }
    ]
    manifest["game"]["replay_viewer"] = {"bundle": "viewer"}
    manifest_path.write_text(json.dumps(manifest))
    root = manifest_path.parent
    (root / "reporter.wasm").write_bytes(b"certified-wasm")
    (root / "viewer").mkdir()
    (root / "viewer/index.html").write_bytes(b"certified-viewer")
    relative = {"wasm": "reporter.wasm", "viewer": "viewer/index.html", "manifest": manifest_path.name}[payload]
    original_bytes = (root / relative).read_bytes()
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr("coworld.upload._local_image_client_hash", lambda image: "sha256:runtime")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("coworld.runner.runner._repo_root", lambda: tmp_path)
    before = _certification_cache_key(manifest_path)
    observed: list[bytes] = []
    certified_keys: list[str] = []
    workspaces: list[Path] = []

    def certify(path: Path, **kwargs: object) -> SimpleNamespace:
        certified_keys.append(_certification_cache_key(path))
        workspaces.append(cast(Path, kwargs["workspace"]))
        changed = original_bytes + b"\n" if payload == "manifest" else b"rebuilt"
        (root / relative).write_bytes(changed)
        observed.append((path.parent / relative).read_bytes())
        if fails:
            raise RuntimeError("certification failed")
        return SimpleNamespace(
            transcript=load_executable_transcript(),
            step_results=[],
            reporter_references=[],
            artifacts=EpisodeArtifacts.create(cast(Path, kwargs["workspace"])),
        )

    monkeypatch.setattr("coworld.cli.certify_coworld", certify)
    result = CliRunner().invoke(app, ["certify", str(manifest_path), "--no-open-report"])
    assert result.exit_code == int(fails), result.output
    assert (workspaces[0] / "certification_report.html").is_file()
    assert certified_keys == [before]
    assert observed == [original_bytes]
    assert _certification_cache_key(manifest_path) != before
    if fails:
        assert not _certified_manifest_cache_path().exists()
    else:
        assert json.loads(_certified_manifest_cache_path().read_text()) == {before: "certified"}
