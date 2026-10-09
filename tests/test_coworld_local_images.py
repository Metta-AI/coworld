from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from coworld.local_images import ensure_downloaded_images, pull_and_tag_image

PUBLIC_IMAGE = "public.ecr.aws/softmax/coworld@sha256:public-digest"
LOCAL_IMAGE = "coworld/cow_x/game-0.1.0-0:downloaded"


def _write_downloaded_package(directory: Path) -> Path:
    directory.mkdir(parents=True)
    manifest_path = directory / "coworld_manifest.json"
    manifest_path.write_text("{}\n", encoding="utf-8")
    (directory / "coworld_images.json").write_text(
        json.dumps({"images": [{"public_image_uri": PUBLIC_IMAGE, "local_image": LOCAL_IMAGE}]}), encoding="utf-8"
    )
    return manifest_path


def _record_docker(monkeypatch: pytest.MonkeyPatch, *, tag_exists: bool) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        inspect_missing = command[:3] == ["docker", "image", "inspect"] and not tag_exists
        return subprocess.CompletedProcess(command, 1 if inspect_missing else 0)

    monkeypatch.setattr("coworld.local_images.subprocess.run", fake_run)
    return calls


def test_missing_local_tag_is_pulled_and_tagged_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _write_downloaded_package(tmp_path / "cow_x")
    calls = _record_docker(monkeypatch, tag_exists=False)

    ensure_downloaded_images(manifest_path)

    assert calls == [
        ["docker", "image", "inspect", LOCAL_IMAGE],
        ["docker", "pull", PUBLIC_IMAGE],
        ["docker", "tag", PUBLIC_IMAGE, LOCAL_IMAGE],
    ]


def test_existing_local_tag_is_not_pulled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _write_downloaded_package(tmp_path / "cow_x")
    calls = _record_docker(monkeypatch, tag_exists=True)

    ensure_downloaded_images(manifest_path)

    assert calls == [["docker", "image", "inspect", LOCAL_IMAGE]]


def test_manifest_without_images_file_never_touches_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = tmp_path / "coworld_manifest.json"
    manifest_path.write_text("{}\n", encoding="utf-8")
    calls = _record_docker(monkeypatch, tag_exists=False)

    ensure_downloaded_images(manifest_path)

    assert calls == []


def test_public_ecr_pull_drops_stale_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "docker-config"
    source.mkdir()
    (source / "config.json").write_text(
        json.dumps({"auths": {"public.ecr.aws": {"auth": "stale"}}, "currentContext": "colima"}), encoding="utf-8"
    )
    monkeypatch.setenv("DOCKER_CONFIG", str(source))
    seen: list[dict[str, object]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        env = kwargs.get("env")
        if command[:2] == ["docker", "pull"]:
            assert isinstance(env, dict)
            seen.append(json.loads((Path(env["DOCKER_CONFIG"]) / "config.json").read_text(encoding="utf-8")))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("coworld.local_images.subprocess.run", fake_run)
    pull_and_tag_image(PUBLIC_IMAGE, LOCAL_IMAGE)
    assert seen == [{"currentContext": "colima"}]


def test_static_viewer_replay_runs_without_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace  # noqa: PLC0415

    from coworld.play import replay_coworld  # noqa: PLC0415

    replay = tmp_path / "replay.json"
    replay.write_text("{}")
    bundle = tmp_path / "viewer"
    bundle.mkdir()
    (bundle / "index.html").write_text("<html></html>")
    package = SimpleNamespace(
        manifest_path=tmp_path / "coworld_manifest.json",
        manifest=SimpleNamespace(game=SimpleNamespace(replay_viewer=SimpleNamespace(bundle="viewer"))),
    )
    monkeypatch.setattr("coworld.play.load_coworld_package", lambda *_args, **_kwargs: package)
    monkeypatch.setattr("coworld.play.source_replay_viewer_bundle", lambda _root, _bundle: bundle)
    monkeypatch.setattr("coworld.play.ensure_downloaded_images", lambda _: pytest.fail("static replay touched Docker"))

    class ViewerReady(Exception):
        pass

    def on_ready(_session: object) -> None:
        raise ViewerReady

    with pytest.raises(ViewerReady):
        replay_coworld(package.manifest_path, replay, workspace=tmp_path / "work", on_ready=on_ready)
