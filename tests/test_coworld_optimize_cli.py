from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest import MonkeyPatch
from typer.testing import CliRunner

from coworld.cli import app
from coworld.optimizer import runtime
from coworld.optimizer.runtime import (
    OptimizerOpenResult,
    OptimizerRepoSpec,
    OptimizerSetupError,
    _is_local_postgres_url,
    _postgres_user_and_db,
    parse_github_repo,
    resolve_optimizer_context,
    resolve_optimizer_repository,
)

DEFAULT_CLONE_URL = "https://github.com/Metta-AI/optimizers.git"


class FakeProc:
    def __init__(self) -> None:
        self.returncode = 0
        self.terminated = False

    def poll(self) -> int:
        return 0

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.terminated = True


def test_parse_github_repo_plain_url() -> None:
    clone_url, ref, slug = parse_github_repo("https://github.com/Metta-AI/optimizers")
    assert clone_url == DEFAULT_CLONE_URL
    assert ref == "main"
    assert slug == "metta-ai-optimizers"


def test_parse_github_repo_with_tree_ref_and_subpath() -> None:
    clone_url, ref, _ = parse_github_repo("https://github.com/Metta-AI/optimizers/tree/v1.2.0/packages/foo")
    assert clone_url == DEFAULT_CLONE_URL
    assert ref == "v1.2.0"


def test_parse_github_repo_strips_git_suffix() -> None:
    clone_url, _, slug = parse_github_repo("https://github.com/Org/Repo.git")
    assert clone_url == "https://github.com/Org/Repo.git"
    assert slug == "org-repo"


def test_parse_github_repo_rejects_non_github() -> None:
    with pytest.raises(OptimizerSetupError):
        parse_github_repo("https://gitlab.com/Org/repo")


def test_resolve_repository_defaults_without_manifest() -> None:
    spec = resolve_optimizer_repository(None)
    assert spec.clone_url == DEFAULT_CLONE_URL
    assert spec.ref == "main"


def test_resolve_repository_reads_manifest_repository_url(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, repository_url="https://github.com/Acme/custom-optimizer/tree/dev")
    spec = resolve_optimizer_repository(manifest_path)
    assert spec.clone_url == "https://github.com/Acme/custom-optimizer.git"
    assert spec.ref == "dev"


def test_resolve_repository_falls_back_when_field_absent(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, repository_url=None)
    spec = resolve_optimizer_repository(manifest_path)
    assert spec.clone_url == DEFAULT_CLONE_URL


def test_resolve_repository_override_wins(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path, repository_url="https://github.com/Acme/custom-optimizer")
    spec = resolve_optimizer_repository(
        manifest_path,
        override_repo="https://github.com/Other/repo",
        override_ref="release",
    )
    assert spec.clone_url == "https://github.com/Other/repo.git"
    assert spec.ref == "release"


def test_postgres_user_and_db_parsing() -> None:
    assert _postgres_user_and_db("postgres://coagent:coagent@localhost:5433/coagent") == ("coagent", "coagent")
    assert _postgres_user_and_db("postgresql://alice@localhost:5432/mydb") == ("alice", "mydb")
    assert _postgres_user_and_db("not-a-url") == ("coagent", "coagent")


def test_is_local_postgres_url() -> None:
    assert _is_local_postgres_url("postgres://coagent:coagent@localhost:5433/coagent") is True
    assert _is_local_postgres_url("postgresql://u@127.0.0.1:5432/db") is True
    assert _is_local_postgres_url("postgres://u@db.example.com:5432/db") is False
    assert _is_local_postgres_url("mysql://u@localhost/db") is False


def test_resolve_context_none_without_manifest() -> None:
    assert resolve_optimizer_context(None) is None


def test_resolve_context_derives_coworld_id_and_images(tmp_path: Path) -> None:
    coworld_dir = tmp_path / "coworld" / "cow_abc123"
    coworld_dir.mkdir(parents=True)
    manifest_path = coworld_dir / "coworld_manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    (coworld_dir / "coworld_images.json").write_text("{}", encoding="utf-8")

    context = resolve_optimizer_context(manifest_path)
    assert context is not None
    assert context.coworld_id == "cow_abc123"
    assert context.images_path == coworld_dir / "coworld_images.json"


def test_optimize_no_arg_opens_home_without_bootstrap(monkeypatch: MonkeyPatch) -> None:
    calls = _patch_runtime(monkeypatch)

    result = CliRunner().invoke(app, ["optimize", "--port", "4123"])

    assert result.exit_code == 0, result.output
    assert calls["repo_spec"].clone_url == DEFAULT_CLONE_URL
    assert calls["bootstrap"] == []
    assert calls["opened"] == ["http://127.0.0.1:4123/"]


def test_optimize_with_manifest_imports_and_opens_detail(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    calls = _patch_runtime(monkeypatch)
    coworld_dir = tmp_path / "coworld" / "cow_abc123"
    coworld_dir.mkdir(parents=True)
    manifest_path = coworld_dir / "coworld_manifest.json"
    manifest_path.write_text(
        json.dumps(_manifest_dict(repository_url="https://github.com/Acme/custom-optimizer")),
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["optimize", str(manifest_path), "--port", "4200"])

    assert result.exit_code == 0, result.output
    assert calls["repo_spec"].clone_url == "https://github.com/Acme/custom-optimizer.git"
    assert len(calls["bootstrap"]) == 1
    assert calls["bootstrap"][0].coworld_id == "cow_abc123"
    assert calls["opened"] == ["http://127.0.0.1:4200/games/game-test"]


def test_optimize_reports_missing_docker(monkeypatch: MonkeyPatch) -> None:
    def fail_prereqs() -> list[str]:
        raise OptimizerSetupError("Docker is not available. Start Docker Desktop (or the Docker daemon) and retry.")

    monkeypatch.setattr(runtime, "check_prerequisites", fail_prereqs)
    monkeypatch.setattr(runtime, "resolve_optimizer_repository", lambda *a, **k: _default_spec())

    result = CliRunner().invoke(app, ["optimize"])

    assert result.exit_code == 1
    assert "Docker is not available" in result.output


def _patch_runtime(monkeypatch: MonkeyPatch) -> dict[str, object]:
    calls: dict[str, object] = {"bootstrap": [], "opened": []}

    def fake_resolve_repository(manifest_path, *, override_repo=None, override_ref=None):
        spec = resolve_optimizer_repository(
            manifest_path, override_repo=override_repo, override_ref=override_ref
        )
        calls["repo_spec"] = spec
        return spec

    def fake_ensure_project(repo_spec, install_root, *, refresh):
        return Path(install_root) / repo_spec.slug / repo_spec.ref

    def fake_bootstrap(base_url, context):
        calls["bootstrap"].append(context)  # type: ignore[attr-defined]
        return OptimizerOpenResult(game_id="game-test", detail_url=f"{base_url}/games/game-test")

    def fake_open(url):
        calls["opened"].append(url)  # type: ignore[attr-defined]

    monkeypatch.setattr(runtime, "resolve_optimizer_repository", fake_resolve_repository)
    monkeypatch.setattr(runtime, "check_prerequisites", lambda: [])
    monkeypatch.setattr(runtime, "ensure_optimizer_project", fake_ensure_project)
    monkeypatch.setattr(runtime, "ensure_postgres", lambda install_dir, database_url=None: None)
    monkeypatch.setattr(runtime, "ensure_database_schema", lambda install_dir, env: None)
    monkeypatch.setattr(runtime, "start_optimizer_dev_server", lambda install_dir, env, port: FakeProc())
    monkeypatch.setattr(runtime, "wait_for_optimizer_ready", lambda base_url, proc, **kwargs: None)
    monkeypatch.setattr(runtime, "bootstrap_game", fake_bootstrap)
    monkeypatch.setattr(runtime.webbrowser, "open", fake_open)
    return calls


def _manifest_dict(*, repository_url: str | None) -> dict:
    optimizer_entry: dict[str, object] = {
        "id": "coworld-optimizer",
        "type": "optimizer",
        "name": "Optimizer",
        "description": "Workbench",
        "image": "softmax/default-optimizer:latest",
    }
    if repository_url is not None:
        optimizer_entry["repository_url"] = repository_url
    return {"game": {"name": "among_them"}, "optimizer": [optimizer_entry]}


def _write_manifest(tmp_path: Path, *, repository_url: str | None) -> Path:
    manifest_path = tmp_path / "coworld_manifest.json"
    manifest_path.write_text(json.dumps(_manifest_dict(repository_url=repository_url)), encoding="utf-8")
    return manifest_path


def _default_spec() -> OptimizerRepoSpec:
    return OptimizerRepoSpec(clone_url=DEFAULT_CLONE_URL, ref="main", slug="metta-ai-optimizers")
