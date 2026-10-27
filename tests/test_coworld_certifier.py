from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path
from typing import cast

import httpx
import pytest
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

import coworld.certifier as certifier_module
import coworld.player_files as player_files
from coworld.bundle import build_coworld_manifest
from coworld.certifier import (
    _run_local_certifier_episode,
    build_manifest_episode_job_spec,
    certify_coworld,
    load_coworld_package,
    load_executable_transcript,
    load_results,
    validate_reporter_references,
)
from coworld.play import _resolve_local_llm_env
from coworld.player_files import InvalidPlayerFile
from coworld.runner.io import RunnerEpisodeError
from coworld.runner.runner import (
    EpisodeArtifacts,
)
from coworld.types import (
    CoworldEpisodeJobSpec,
    SourceUrlResult,
    TranscriptStep,
)


def test_load_coworld_package_requires_tags_for_certification(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(tmp_path)
    manifest = json.loads(coworld_manifest_path.read_text())
    del manifest["tags"]
    coworld_manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="certification requires at least three manifest tags"):
        load_coworld_package(coworld_manifest_path, require_certification_tags=True)


def _wasm_reporter_reference(wasm: str, **attribute_overrides: object) -> dict[str, object]:
    attributes: dict[str, object] = {
        "purpose": "Summarize certification episodes.",
        "world": "softmax:reporter",
        "outputs": [{"name": "summary", "type": "markdown", "description": "Episode summary."}],
        **attribute_overrides,
    }
    return {"wasm": wasm, "id": "unit-test-reporter", "attributes": attributes}


def _package_with_reporters(tmp_path: Path, reporters: list[dict[str, object]]):
    coworld_manifest_path = _write_package_files(tmp_path)
    manifest = json.loads(coworld_manifest_path.read_text(encoding="utf-8"))
    manifest["reporter"] = reporters
    coworld_manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return load_coworld_package(coworld_manifest_path)


def test_validate_reporter_references_rejects_wasm_path_escaping_package(tmp_path: Path) -> None:
    package = _package_with_reporters(tmp_path, [_wasm_reporter_reference("../outside.wasm")])
    (tmp_path / "outside.wasm").write_bytes(b"\x00asm")

    with pytest.raises(ValueError, match="escapes the package root"):
        validate_reporter_references(package)


def _stub_executable_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "coworld.certifier.inspect_source_references",
        lambda package: [
            SourceUrlResult(
                runnable="game.runnable",
                source_url=None,
                status="not_declared",
                publicly_accessible=False,
                detail="No source_url declared.",
            )
        ],
    )
    monkeypatch.setattr("coworld.certifier.validate_image_references", lambda package: None)
    monkeypatch.setattr("coworld.certifier.validate_coworld_manifest_game_configs", lambda manifest: None)
    monkeypatch.setattr("coworld.certifier.build_episode_request", lambda package, artifacts: {})
    monkeypatch.setattr("coworld.certifier.build_coworld_episode_job_spec", lambda request: None)

    def fake_run_episode(_package, job, artifacts, timeout_seconds):
        artifacts.replay_path.write_text("{}")
        artifacts.results_path.write_text(json.dumps({"scores": [1.0]}), encoding="utf-8")
        artifacts.game_stdout_path.write_text("game started\n")
        artifacts.policy_log_path(0).write_text("player started\n")

    monkeypatch.setattr("coworld.certifier._run_local_certifier_episode", fake_run_episode)
    monkeypatch.setattr("coworld.certifier.load_results", lambda package, artifacts: {})
    monkeypatch.setattr(
        "coworld.certifier.verify_replay_loadable",
        lambda game, artifacts, *, network, timeout_seconds: None,
    )
    monkeypatch.setattr(
        "coworld.certifier.run_certification_supporting_roles",
        lambda package, artifacts, *, timeout_seconds: ([], "supporting roles passed"),
    )


def test_certify_coworld_rejects_transcript_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    coworld_manifest_path = _write_package_files(tmp_path)
    _stub_executable_pipeline(monkeypatch)

    transcript = load_executable_transcript()
    ghost = TranscriptStep.model_validate({"id": "ghost", "kind": "auto", "checks": "x", "pass": "y", "how": "z"})
    drifted = transcript.model_copy(update={"steps": [*transcript.steps, ghost]})
    monkeypatch.setattr("coworld.certifier.load_executable_transcript", lambda: drifted)

    with pytest.raises(ValueError, match="transcript"):
        certify_coworld(coworld_manifest_path, workspace=tmp_path / "cert")


def test_certify_coworld_rejects_player_without_launch_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    coworld_manifest_path = _write_package_files(tmp_path)
    _stub_executable_pipeline(monkeypatch)

    def fake_run_episode(_package, job, artifacts, timeout_seconds):
        artifacts.replay_path.write_text("{}")
        artifacts.game_stdout_path.write_text("game started\n")

    monkeypatch.setattr("coworld.certifier._run_local_certifier_episode", fake_run_episode)
    events: list[tuple[str, str, str | None]] = []

    with pytest.raises(ValueError, match="left no launch log"):
        certify_coworld(
            coworld_manifest_path,
            workspace=tmp_path / "cert",
            on_step=lambda result, step: events.append((result.id, result.status, result.failure_reason)),
        )

    assert events[-1] == ("players-run", "fail", "players_missing")


def test_certify_coworld_rejects_player_without_certification_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coworld_manifest_path = _write_package_files(tmp_path)
    manifest = json.loads(coworld_manifest_path.read_text(encoding="utf-8"))
    bench_player = dict(manifest["player"][0], id="bench-player", name="Bench Player")
    manifest["player"].append(bench_player)
    coworld_manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    _stub_executable_pipeline(monkeypatch)

    with pytest.raises(ValueError, match="'bench-player'.*no certification slot"):
        certify_coworld(coworld_manifest_path, workspace=tmp_path / "cert")


def test_load_results_validates_against_cogame_results_schema(tmp_path: Path) -> None:
    package = _write_package(tmp_path)
    artifacts = EpisodeArtifacts.create(tmp_path / "cert")
    artifacts.results_path.write_text(json.dumps({"winner": 0}))

    with pytest.raises(JsonSchemaValidationError, match="'scores' is a required property"):
        load_results(package, artifacts)


def test_local_certifier_runs_game_hosted_episode_with_fixture_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = _write_game_hosted_package(tmp_path)
    package = load_coworld_package(manifest_path)
    job = build_manifest_episode_job_spec(package)
    artifacts = EpisodeArtifacts.create(tmp_path / "cert")
    calls: list[tuple[CoworldEpisodeJobSpec, dict[str, object]]] = []

    def fake_run(spec: CoworldEpisodeJobSpec, _artifacts: EpisodeArtifacts, **kwargs: object) -> None:
        calls.append((spec, kwargs))

    monkeypatch.setattr("coworld.certifier.run_coworld_episode", fake_run)

    _run_local_certifier_episode(package, job, artifacts, 12.0)

    assert calls == [
        (
            job,
            {
                "timeout_seconds": 12.0,
                "verify_replay": False,
                "validate_results": False,
                "player_file_paths": [manifest_path.parent / "players/player.wasm"] * 2,
                "require_websocket_pong": True,
            },
        )
    ]


def test_local_certifier_rejects_hash_only_game_hosted_fixture(tmp_path: Path) -> None:
    manifest_path = _write_game_hosted_package(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["player"][0]["file"] = f"sha256:{'a' * 64}"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    package = load_coworld_package(manifest_path)
    job = build_manifest_episode_job_spec(package)

    with pytest.raises(InvalidPlayerFile, match="local certification needs package-relative player files") as excinfo:
        _run_local_certifier_episode(package, job, EpisodeArtifacts.create(tmp_path / "cert"), 12.0)
    assert certifier_module._step_failure_reason("smoke-episode", excinfo.value) == "players_missing"


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True, timeout=10)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.mark.slow
@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
@pytest.mark.parametrize("results_mode", ["valid", "missing", "malformed", "schema-invalid"])
def test_paintarena_example_certifies_with_docker(tmp_path: Path, results_mode: str) -> None:
    example_root = _example_root()
    manifest_path = build_coworld_manifest(
        example_root / "compose.yaml",
        example_root / "coworld_manifest_template.json",
        "0.1.0",
        tmp_path / "dist" / "coworld_manifest.json",
    )

    events: list[tuple[str, str, str | None]] = []
    if results_mode != "valid":
        manifest = json.loads(manifest_path.read_text())
        game = manifest["game"]["runnable"]
        game["env"] = game.get("env", {}) | {"CERTIFIER_RESULTS_MODE": results_mode}
        game["run"] = [
            "python",
            "-c",
            textwrap.dedent("""\
                import os
                import uvicorn
                from coworld.examples.paintarena.game import server as game

                original_write = game.write_data
                def write_data(uri, data, **kwargs):
                    if uri == game.RESULTS_URI:
                        mode = os.environ["CERTIFIER_RESULTS_MODE"]
                        if mode == "missing":
                            return
                        data = "not JSON" if mode == "malformed" else "{}"
                    original_write(uri, data, **kwargs)

                game.write_data = write_data
                game.server = uvicorn.Server(uvicorn.Config(game.app, host=game.GAME_HOST, port=game.GAME_PORT))
                game.server.run()
            """),
        ]
        manifest_path.write_text(json.dumps(manifest))
        error = {
            "missing": FileNotFoundError,
            "malformed": ValueError,
            "schema-invalid": JsonSchemaValidationError,
        }[results_mode]
        with pytest.raises(error):
            certify_coworld(
                manifest_path,
                workspace=tmp_path / "cert",
                timeout_seconds=60,
                on_step=lambda result, step: events.append((result.id, result.status, result.failure_reason)),
            )
        assert ("smoke-episode", "pass", None) in events
        assert events[-1] == (
            "results-conform",
            "fail",
            "results_missing" if results_mode == "missing" else "results_malformed",
        )
        return

    result = certify_coworld(
        manifest_path,
        workspace=tmp_path / "cert",
        timeout_seconds=60,
    )

    scores = cast(list[int], result.results["scores"])
    assert sum(scores) > 0
    assert result.artifacts.replay_path.exists()
    assert result.artifacts.game_stdout_path.exists()
    assert result.artifacts.game_stderr_path.exists()


def _write_package(
    tmp_path: Path,
    *,
    config_schema_required: list[str] | None = None,
    certification: dict[str, object] | None = None,
    game_config: dict[str, object] | None = None,
):
    return load_coworld_package(
        _write_package_files(
            tmp_path,
            config_schema_required=config_schema_required or ["tokens"],
            certification=certification,
            game_config=game_config,
        )
    )


def _write_package_files(
    tmp_path: Path,
    *,
    config_schema_required: list[str] | None = None,
    certification: dict[str, object] | None = None,
    game_config: dict[str, object] | None = None,
) -> Path:
    world_dir = tmp_path / "world"
    world_dir.mkdir(parents=True)
    coworld_manifest_path = world_dir / "coworld_manifest.json"
    coworld_manifest_path.write_text(
        json.dumps(
            _coworld_manifest(
                config_schema_required=config_schema_required or ["tokens"],
                certification=certification,
                game_config=game_config,
            )
        )
    )
    return coworld_manifest_path


def _write_game_hosted_package(tmp_path: Path) -> Path:
    manifest_path = _write_package_files(
        tmp_path,
        certification={
            "game_config": {"difficulty": "easy"},
            "players": [{"player_id": "unit-test-player"}, {"player_id": "unit-test-player"}],
        },
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["game"]["player_runtime"] = "game-hosted"
    manifest["game"]["config_schema"]["properties"]["tokens"]["maxItems"] = 2
    player = manifest["player"][0]
    player.pop("image")
    player["file"] = "players/player.wasm"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    player_path = manifest_path.parent / "players/player.wasm"
    player_path.parent.mkdir(parents=True)
    player_path.write_bytes(b"fixture-player")
    return manifest_path


def _coworld_manifest(
    *,
    config_schema_required: list[str] | None = None,
    certification: dict[str, object] | None = None,
    game_config: dict[str, object] | None = None,
) -> dict[str, object]:
    if certification is None:
        certification = {
            "game_config": game_config or {"difficulty": "easy"},
            "players": [{"player_id": "unit-test-player"}],
        }
    return {
        "tags": ["test", "multiplayer", "real-time"],
        "game": _game_manifest(config_schema_required=config_schema_required or ["tokens"]),
        "player": [
            {
                "id": "unit-test-player",
                "name": "Unit Test Player",
                "type": "player",
                "image": "unit-test-runtime:latest",
                "run": ["python", "-m", "unit_test.player"],
                "env": {"PLAYER_MODE": "test"},
                "description": "Unit test player.",
            }
        ],
        "reporter": [{"reporter": "softmax/default@1"}],
        "grader": [
            {
                "id": "unit-test-grader",
                "name": "Unit Test Grader",
                "type": "grader",
                "image": "ghcr.io/metta-ai/graders-default:latest",
                "source_url": "https://github.com/Metta-AI/coworld-tools/tree/e6b7863c2619d260bb29f14364baf09c578c9f30/graders/graders/default/default_grader",
                "description": "Default grader stub for unit tests.",
            }
        ],
        "variants": [
            {
                "id": "default",
                "name": "Default",
                "game_config": game_config or {"difficulty": "easy"},
                "description": "Default test variant.",
            }
        ],
        "certification": certification,
    }


def _game_manifest(*, config_schema_required: list[str] | None = None) -> dict[str, object]:
    required = config_schema_required or ["tokens"]
    return {
        "name": "unit-test-game",
        "version": "0.1.0",
        "description": "Unit test Coworld manifest.",
        "owner": "coworld@softmax.com",
        "runnable": {
            "type": "game",
            "image": "unit-test-runtime:latest",
            "run": ["python", "-m", "unit_test.game"],
            "env": {"GAME_MODE": "test"},
        },
        "config_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "required": required,
            "properties": {
                "tokens": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 1,
                    "items": {"type": "string", "minLength": 1},
                },
                "difficulty": {"type": "string"},
                "players": {"type": "array", "items": {"type": "object"}},
            },
        },
        "results_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": ["scores"],
            "properties": {"scores": {"type": "array", "items": {"type": "number"}}},
        },
        "protocols": {
            "player": {"type": "uri", "value": "https://example.com/player_protocol_spec.md"},
            "global": {"type": "uri", "value": "https://example.com/global_protocol_spec.md"},
        },
        "docs": {
            "readme": {"type": "uri", "value": "https://example.com/README.md"},
            "pages": [
                {
                    "id": "rules.md",
                    "title": "rules.md",
                    "content": {"type": "text", "value": "# Rules\n\nScore one point."},
                },
                {
                    "id": "play_unittest.md",
                    "title": "play_unittest.md",
                    "content": {"type": "uri", "value": "https://example.com/play_unittest.md"},
                },
            ],
        },
    }


def _example_root() -> Path:
    return Path(__file__).resolve().parents[1] / "src" / "coworld" / "examples" / "paintarena"


@pytest.mark.parametrize("status_code", [404, 429, 500, 502, 503])
def test_smoke_episode_api_failure_is_not_an_author_verdict(status_code):
    request = httpx.Request("POST", "https://platform.example/v2/episode-requests")
    error = httpx.HTTPStatusError(
        "Cannot dispatch episode", request=request, response=httpx.Response(status_code, request=request)
    )
    assert certifier_module._step_failure_reason("smoke-episode", error) == "platform_error"


def test_smoke_episode_typed_timeout_stays_inconclusive():
    error = RunnerEpisodeError("Player did not exit", error_type="episode_inconclusive")
    assert certifier_module._step_failure_reason("smoke-episode", error) == "episode_inconclusive"


@pytest.mark.parametrize("invalid", ["missing", "symlink", "escape", "oversize", "nested_symlink"])
def test_invalid_player_files_keep_author_attribution(tmp_path, monkeypatch, invalid):
    root = tmp_path / "package"
    root.mkdir()
    source = root / "player.wasm"
    if invalid != "missing":
        source.write_bytes(b"player")
    if invalid == "symlink":
        source.unlink()
        source.symlink_to(tmp_path / "outside")
    elif invalid == "escape":
        source = tmp_path / "outside"
        source.write_bytes(b"player")
    elif invalid == "oversize":
        monkeypatch.setattr(player_files, "PLAYER_FILE_MAX_BYTES", 1)
    elif invalid == "nested_symlink":
        source.unlink()
        source.mkdir()
        (source / "linked").symlink_to(tmp_path / "outside")
    with pytest.raises(InvalidPlayerFile) as excinfo:
        player_files.player_file_bytes(source, package_root=root)
    assert certifier_module._step_failure_reason("smoke-episode", excinfo.value) == "players_missing"


def test_local_llm_env_uses_endpoint_without_forwarding_provider_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COWORLD_LLM_ENDPOINT", "http://host.docker.internal:9100")
    monkeypatch.setenv("OPENROUTER_API_KEY", "must-not-forward")
    monkeypatch.setenv("COWORLD_LLM_MODEL", "anthropic/claude-haiku-4.5")
    assert _resolve_local_llm_env() == {
        "COWORLD_LLM_ENABLED": "true",
        "COWORLD_LLM_ENDPOINT": "http://host.docker.internal:9100",
        "COWORLD_LLM_MODEL": "anthropic/claude-haiku-4.5",
    }


def test_local_llm_env_requires_explicit_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COWORLD_LLM_ENDPOINT", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="--use-llm requires"):
        _resolve_local_llm_env()
