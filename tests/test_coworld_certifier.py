from __future__ import annotations

import asyncio
import importlib
import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from websockets.exceptions import ConnectionClosedOK

from coworld.certifier import (
    build_episode_request,
    build_game_config,
    build_manifest_episode_job_spec,
    build_player_launch_specs,
    certify_coworld,
    load_coworld_package,
    load_manifest_episode_job_spec,
    load_results,
    validate_source_references,
)
from coworld.play import BedrockAwsEnv, ReplaySession, build_play_links, play_coworld, replay_coworld
from coworld.runner.runner import (
    CONFIG_ENV_VAR,
    LOCAL_DOCKER_NETWORK,
    LOCAL_GAME_NETWORK_ALIAS_PREFIX,
    REPLAY_LOAD_ENV_VAR,
    REPLAY_SAVE_ENV_VAR,
    RESULTS_ENV_VAR,
    EpisodeArtifacts,
    _image_command,
    _require_bad_player_rejected,
    assert_docker_image_reachable,
    replay_client_url,
    replay_session_path,
)
from coworld.types import CoworldEpisodeJobSpec, CoworldManifest


def test_load_coworld_package_validates_inline_game_manifest(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(tmp_path)

    package = load_coworld_package(coworld_manifest_path)
    assert package.manifest_path == coworld_manifest_path.resolve()
    assert package.manifest.game.name == "unit-test-game"


def test_load_coworld_package_requires_protocol_uri_doc_urls(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(tmp_path)
    manifest = json.loads(coworld_manifest_path.read_text())
    manifest["game"]["protocols"] = {
        "player": {"type": "uri", "value": "game/docs/player_protocol_spec.md"},
        "global": {"type": "uri", "value": "https://example.com/global_protocol_spec.md"},
    }
    coworld_manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(JsonSchemaValidationError, match="not valid"):
        load_coworld_package(coworld_manifest_path)


def test_load_coworld_package_allows_public_protocol_doc_links(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(tmp_path)
    manifest = json.loads(coworld_manifest_path.read_text())
    manifest["game"]["protocols"] = {
        "player": {"type": "uri", "value": "https://example.com/player_protocol_spec.md"},
        "global": {"type": "uri", "value": "https://example.com/global_protocol_spec.md"},
    }
    coworld_manifest_path.write_text(json.dumps(manifest))

    package = load_coworld_package(coworld_manifest_path)

    assert package.protocols.player.type == "uri"
    assert package.protocols.player.value == "https://example.com/player_protocol_spec.md"


def test_load_coworld_package_allows_explicit_text_protocol_docs(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(tmp_path)
    manifest = json.loads(coworld_manifest_path.read_text())
    manifest["game"]["protocols"] = {
        "player": {"type": "text", "value": "# Player Protocol\n\nConnect over /player."},
        "global": {"type": "text", "value": "# Global Protocol\n\nConnect over /global."},
    }
    coworld_manifest_path.write_text(json.dumps(manifest))

    package = load_coworld_package(coworld_manifest_path)

    assert package.protocols.player.type == "text"
    assert package.protocols.player.value.startswith("# Player Protocol")


def test_load_coworld_package_allows_named_game_docs(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(tmp_path)
    manifest = json.loads(coworld_manifest_path.read_text())
    manifest["game"]["docs"] = {
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
            {
                "id": "optimizer",
                "title": "optimizer.md",
                "content": {"type": "text", "value": "# Optimizer\n\nImprove policies."},
            },
        ],
    }
    coworld_manifest_path.write_text(json.dumps(manifest))

    package = load_coworld_package(coworld_manifest_path)

    assert package.manifest.game.docs.readme is not None
    assert package.manifest.game.docs.readme.value == "https://example.com/README.md"
    assert package.manifest.game.docs.pages[0].title == "rules.md"
    assert package.manifest.game.docs.pages[0].content.value.startswith("# Rules")
    assert package.manifest.game.docs.pages[1].title == "play_unittest.md"
    assert package.manifest.game.docs.pages[1].content.value == "https://example.com/play_unittest.md"
    assert package.manifest.game.docs.pages[2].title == "optimizer.md"
    assert package.manifest.game.docs.pages[2].content.value.startswith("# Optimizer")


def test_load_coworld_package_rejects_invalid_certification_player_entry(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(
        tmp_path,
        certification={
            "game_config": {"difficulty": "easy"},
            "players": [{"role": "painter"}],
        },
    )

    with pytest.raises(JsonSchemaValidationError, match="player_id"):
        load_coworld_package(coworld_manifest_path)


def test_load_coworld_package_rejects_extra_certification_player_fields(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(
        tmp_path,
        certification={
            "game_config": {"difficulty": "easy"},
            "players": [{"player_id": "unit-test-player", "role": "painter"}],
        },
    )

    with pytest.raises(JsonSchemaValidationError, match="Additional properties are not allowed"):
        load_coworld_package(coworld_manifest_path)


def test_load_coworld_package_rejects_unknown_certification_player(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(
        tmp_path,
        certification={
            "game_config": {"difficulty": "easy"},
            "players": [{"player_id": "missing"}],
        },
    )

    with pytest.raises(ValueError, match="unknown certification player_id"):
        load_coworld_package(coworld_manifest_path)


def test_assert_docker_image_reachable_accepts_local_image(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout='[{"Os":"linux","Architecture":"amd64"}]', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert_docker_image_reachable("local-image:latest")

    assert calls == [["docker", "image", "inspect", "local-image:latest"]]


def test_assert_docker_image_reachable_accepts_remote_image(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1 if cmd[1:3] == ["image", "inspect"] else 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert_docker_image_reachable("ghcr.io/example/image:latest")

    assert calls == [
        ["docker", "image", "inspect", "ghcr.io/example/image:latest"],
        ["docker", "manifest", "inspect", "ghcr.io/example/image:latest"],
    ]


def test_assert_docker_image_reachable_rejects_missing_image(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="missing image")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="Missing image"):
        assert_docker_image_reachable("missing:latest", label="Missing image")


def test_assert_docker_image_reachable_rejects_unresolved_container_image_id(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_run(cmd, **kwargs):
        raise AssertionError(f"docker should not be invoked for an unresolved image id: {cmd}")

    monkeypatch.setattr(subprocess, "run", fail_run)

    with pytest.raises(RuntimeError, match="unresolved Coworld image id"):
        assert_docker_image_reachable("img_d62e1e60-f2a5-480f-a347-f31c748c5c2f", label="game.runnable.image")


def test_assert_docker_image_reachable_allows_local_image_named_like_id(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout='[{"Os":"linux","Architecture":"amd64"}]', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    # "img_game:latest" shares the prefix but is not an "img_<uuid>" backend id, so it must run normally.
    assert_docker_image_reachable("img_game:latest")

    assert calls == [["docker", "image", "inspect", "img_game:latest"]]


def test_assert_docker_image_reachable_rejects_wrong_local_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout='[{"Os":"linux","Architecture":"arm64"}]', stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="linux/arm64"):
        assert_docker_image_reachable("local-image:latest", label="Local image")


def test_validate_source_references_rejects_empty_github_source_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package_with_player_source_url(tmp_path, "https://github.com/Metta-AI/example/tree/main/empty")

    monkeypatch.setattr(
        "coworld.certifier.httpx.get",
        lambda *args, **kwargs: httpx.Response(200, json=[]),
    )

    with pytest.raises(ValueError) as excinfo:
        validate_source_references(package)

    message = str(excinfo.value)
    assert "Coworld player[0].source_url: Empty source directory" in message
    assert "Coworld player[0].source_url: No Dockerfile found" in message


def test_validate_source_references_accepts_github_repo_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = _package_with_player_source_url(tmp_path, "https://github.com/Metta-AI/optimizers")
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs["params"]))
        return httpx.Response(
            200,
            json=[
                {"type": "file", "name": "Dockerfile"},
                {"type": "file", "name": "README.md"},
            ],
        )

    monkeypatch.setattr("coworld.certifier.httpx.get", fake_get)

    validate_source_references(package)

    assert calls == [("https://api.github.com/repos/Metta-AI/optimizers/contents", {})]


def test_validate_source_references_accepts_ancestor_dockerfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package_with_player_source_url(
        tmp_path,
        "https://github.com/Metta-AI/coworld/tree/main/src/coworld/examples/paintarena/reporter",
    )
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs["params"]))
        if url.endswith("/contents/src/coworld/examples/paintarena/reporter"):
            return httpx.Response(200, json=[{"type": "file", "name": "paint_arena_summarizer.py"}])
        if url.endswith("/contents/src/coworld/examples/paintarena"):
            return httpx.Response(200, json=[{"type": "file", "name": "Dockerfile"}])
        raise AssertionError(url)

    monkeypatch.setattr("coworld.certifier.httpx.get", fake_get)

    validate_source_references(package)

    assert calls == [
        (
            "https://api.github.com/repos/Metta-AI/coworld/contents/src/coworld/examples/paintarena/reporter",
            {"ref": "main"},
        ),
        ("https://api.github.com/repos/Metta-AI/coworld/contents/src/coworld/examples/paintarena", {"ref": "main"}),
    ]


def test_validate_source_references_accepts_github_branch_names_with_slashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package_with_player_source_url(
        tmp_path, "https://github.com/Metta-AI/optimizers/tree/feature/foo/workbench"
    )
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs["params"]))
        if kwargs["params"] == {"ref": "feature"}:
            return httpx.Response(404)
        if kwargs["params"] == {"ref": "feature/foo"}:
            return httpx.Response(200, json=[{"type": "file", "name": "Dockerfile"}])
        raise AssertionError(kwargs["params"])

    monkeypatch.setattr("coworld.certifier.httpx.get", fake_get)

    validate_source_references(package)

    assert calls == [
        ("https://api.github.com/repos/Metta-AI/optimizers/contents/foo/workbench", {"ref": "feature"}),
        ("https://api.github.com/repos/Metta-AI/optimizers/contents/workbench", {"ref": "feature/foo"}),
    ]


def test_certify_coworld_checks_source_references_before_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coworld_manifest_path = _write_package_files(tmp_path)
    calls = []

    def fake_validate_source_references(package):
        calls.append("source")
        raise ValueError("bad source")

    def fake_validate_image_references(package):
        calls.append("image")

    monkeypatch.setattr("coworld.certifier.validate_source_references", fake_validate_source_references)
    monkeypatch.setattr("coworld.certifier.validate_image_references", fake_validate_image_references)

    with pytest.raises(ValueError, match="bad source"):
        certify_coworld(coworld_manifest_path)

    assert calls == ["source"]


def test_build_game_config_validates_after_tokens_are_injected_via_json_schema(tmp_path: Path) -> None:
    with pytest.raises(JsonSchemaValidationError):
        _write_package(tmp_path, config_schema_required=["tokens", "missing"])


def test_build_game_config_rejects_wrong_token_count(tmp_path: Path) -> None:
    package = _write_package(tmp_path)

    with pytest.raises(JsonSchemaValidationError):
        build_game_config(package, [])


def test_load_coworld_package_requires_fixed_token_count(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(tmp_path)
    manifest = json.loads(coworld_manifest_path.read_text())
    del manifest["game"]["config_schema"]["properties"]["tokens"]["maxItems"]
    coworld_manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="equal minItems and maxItems"):
        load_coworld_package(coworld_manifest_path)


def test_load_coworld_package_rejects_tokens_in_variant_game_config(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(tmp_path)
    manifest = json.loads(coworld_manifest_path.read_text())
    manifest["variants"][0]["game_config"]["tokens"] = ["token-0"]
    coworld_manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="must not include runner-managed tokens"):
        load_coworld_package(coworld_manifest_path)


def test_load_coworld_package_requires_certification_player_count_to_match_tokens(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(
        tmp_path,
        certification={
            "game_config": {"difficulty": "easy"},
            "players": [{"player_id": "unit-test-player"}, {"player_id": "unit-test-player"}],
        },
    )

    with pytest.raises(ValueError, match="certification.players must match"):
        load_coworld_package(coworld_manifest_path)


def test_load_results_validates_against_cogame_results_schema(tmp_path: Path) -> None:
    package = _write_package(tmp_path)
    artifacts = EpisodeArtifacts.create(tmp_path / "cert")
    artifacts.results_path.write_text(json.dumps({"winner": 0}))

    with pytest.raises(JsonSchemaValidationError, match="'scores' is a required property"):
        load_results(package, artifacts)


def test_build_episode_request_matches_runner_spec_shape(tmp_path: Path) -> None:
    package = _write_package(tmp_path)
    artifacts = EpisodeArtifacts.create(tmp_path / "cert")

    episode_request = build_episode_request(package, artifacts)

    assert CoworldManifest.model_validate(episode_request["manifest"]) == package.manifest
    assert episode_request["game_config"] == {"difficulty": "easy"}
    assert episode_request["players"] == [
        {
            "type": "player",
            "image": "unit-test-runtime:latest",
            "run": ["python", "-m", "unit_test.player"],
            "env": {"PLAYER_MODE": "test"},
        }
    ]
    assert "results_uri" not in episode_request
    assert "replay_uri" not in episode_request
    assert "logs_uri" not in episode_request


def test_build_manifest_episode_job_spec_can_use_variant_config(tmp_path: Path) -> None:
    package = _write_package(
        tmp_path,
        certification={
            "game_config": {"difficulty": "smoke"},
            "players": [{"player_id": "unit-test-player"}],
        },
        game_config={"difficulty": "watch"},
    )

    spec = build_manifest_episode_job_spec(package, variant_id="default")

    assert spec.game_config == {"difficulty": "watch"}


def test_build_manifest_episode_job_spec_defaults_to_certification_config(tmp_path: Path) -> None:
    package = _write_package(
        tmp_path,
        certification={
            "game_config": {"difficulty": "smoke"},
            "players": [{"player_id": "unit-test-player"}],
        },
        game_config={"difficulty": "watch"},
    )

    spec = build_manifest_episode_job_spec(package)

    assert spec.game_config == {"difficulty": "smoke"}


def test_build_manifest_episode_job_spec_deep_copies_config_and_player_env(tmp_path: Path) -> None:
    package = _write_package(
        tmp_path,
        certification={
            "game_config": {
                "players": [{"name": "one"}, {"name": "two"}],
            },
            "players": [{"player_id": "unit-test-player"}],
        },
        game_config={"difficulty": "watch"},
    )

    spec = build_manifest_episode_job_spec(package)
    spec.game_config["players"][0]["name"] = "mutated"
    spec.players[0].env["PLAYER_MODE"] = "mutated"

    next_spec = build_manifest_episode_job_spec(package)
    assert next_spec.game_config["players"][0]["name"] == "one"
    assert next_spec.players[0].env == {"PLAYER_MODE": "test"}


def test_load_manifest_episode_job_spec_uses_request_file(tmp_path: Path) -> None:
    coworld_manifest_path = _write_package_files(tmp_path)
    package = load_coworld_package(coworld_manifest_path)
    request_path = tmp_path / "episode_request.json"
    request_path.write_text(
        json.dumps(
            {
                "manifest": json.loads(coworld_manifest_path.read_text(encoding="utf-8")),
                "game_config": {"difficulty": "request"},
                "players": [
                    {
                        "type": "player",
                        "image": "request-player:latest",
                        "run": ["python", "/request-player.py"],
                        "env": {"PLAYER_MODE": "request"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    spec = load_manifest_episode_job_spec(package, request_path)

    assert spec.game_config == {"difficulty": "request"}
    assert spec.players[0].image == "request-player:latest"
    assert spec.players[0].run == ["python", "/request-player.py"]
    assert spec.players[0].env == {"PLAYER_MODE": "request"}


def test_build_manifest_episode_job_spec_rejects_unknown_variant(tmp_path: Path) -> None:
    package = _write_package(tmp_path)

    with pytest.raises(ValueError, match="unknown Coworld variant_id"):
        build_manifest_episode_job_spec(package, variant_id="missing")


def test_episode_request_allows_no_runner_managed_players() -> None:
    episode_request = {
        "manifest": _coworld_manifest(),
        "game_config": {"difficulty": "easy", "players": []},
        "players": [],
    }

    CoworldEpisodeJobSpec.model_validate(episode_request)
    assert build_player_launch_specs(episode_request) == []


def test_build_play_links_point_directly_at_engine_client_routes(tmp_path: Path) -> None:
    package = _write_package(
        tmp_path,
        game_config={"difficulty": "easy", "players": [{"role": "x", "difficulty": 2, "debug": True}]},
    )
    artifacts = EpisodeArtifacts.create(tmp_path / "cert")
    episode_request = build_episode_request(package, artifacts)
    players = build_player_launch_specs(episode_request)

    links = build_play_links(players, ["token-0"], game_port=1234)

    player_link = urlparse(links.players[0])
    assert player_link.scheme == "http"
    assert player_link.netloc == "127.0.0.1:1234"
    assert player_link.path == "/client/player"
    assert parse_qs(player_link.query) == {
        "slot": ["0"],
        "token": ["token-0"],
    }
    game_config = cast(dict[str, object], episode_request["game_config"])
    assert game_config["players"] == [{"role": "x", "difficulty": 2, "debug": True}]

    global_link = urlparse(links.global_)
    assert global_link.scheme == "http"
    assert global_link.netloc == "127.0.0.1:1234"
    assert global_link.path == "/client/global"
    assert global_link.query == ""

    admin_link = urlparse(links.admin)
    assert admin_link.scheme == "http"
    assert admin_link.netloc == "127.0.0.1:1234"
    assert admin_link.path == "/client/admin"
    assert admin_link.query == ""


def test_bad_player_probe_accepts_immediate_websocket_close(monkeypatch: pytest.MonkeyPatch) -> None:
    class ClosingWebSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def recv(self) -> bytes:
            raise ConnectionClosedOK(None, None)

    monkeypatch.setattr(
        "coworld.runner.runner.websockets.connect",
        lambda _url, **_kwargs: ClosingWebSocket(),
    )

    asyncio.run(_require_bad_player_rejected("ws://example.test/player?slot=0&token=bad"))


def test_bad_player_probe_rejects_live_websocket(monkeypatch: pytest.MonkeyPatch) -> None:
    class LiveWebSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def recv(self) -> bytes:
            return b"frame"

    monkeypatch.setattr(
        "coworld.runner.runner.websockets.connect",
        lambda _url, **_kwargs: LiveWebSocket(),
    )

    with pytest.raises(AssertionError, match="Bad player token was accepted"):
        asyncio.run(_require_bad_player_rejected("ws://example.test/player?slot=0&token=bad"))


def test_play_coworld_starts_certification_player_containers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    coworld_manifest_path = _write_package_files(
        tmp_path,
        certification={
            "game_config": {"difficulty": "smoke"},
            "players": [{"player_id": "unit-test-player"}],
        },
        game_config={"difficulty": "watch"},
    )
    ready_sessions = []
    popen_commands: list[list[str]] = []
    network_commands: list[list[str]] = []
    rm_commands: list[list[str]] = []
    waited_players: list[Path] = []

    class FakeProcess:
        def wait(self) -> int:
            return 0

    def fake_popen(cmd, **kwargs):
        popen_commands.append(cmd)
        return FakeProcess()

    def noop_wait_for_health(
        port: int, process: subprocess.Popen, stderr_path: Path, *, timeout_seconds: float
    ) -> None:
        pass

    def fake_wait_for_player_exit(player_process: subprocess.Popen[str], stderr_path: Path) -> None:
        waited_players.append(stderr_path)

    def fake_subprocess_run(cmd, **kwargs):
        if cmd[:2] == ["docker", "network"]:
            network_commands.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)
        rm_commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("coworld.play.assert_episode_images_reachable", lambda _job: None)
    monkeypatch.setattr("coworld.play._free_local_port", lambda: 1234)
    monkeypatch.setattr("coworld.play._wait_for_health", noop_wait_for_health)
    monkeypatch.setattr("coworld.play._wait_for_game_exit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("coworld.play._wait_for_player_exit", fake_wait_for_player_exit)
    monkeypatch.setattr("coworld.play.subprocess.Popen", fake_popen)
    monkeypatch.setattr("coworld.play.subprocess.run", fake_subprocess_run)
    monkeypatch.setattr("coworld.play.secrets.token_hex", lambda _bytes: "session-1")
    monkeypatch.setattr("coworld.runner.runner.secrets.token_urlsafe", lambda _bytes: "token-0")
    monkeypatch.setattr("coworld.play.load_results", lambda package, artifacts: {"scores": [1.0]})

    result = play_coworld(
        coworld_manifest_path,
        workspace=tmp_path / "play-workspace",
        on_ready=ready_sessions.append,
    )

    assert ready_sessions == [result.session]
    assert result.session.variant_id == "certification"
    assert json.loads((tmp_path / "play-workspace" / "config.json").read_text())["difficulty"] == "smoke"
    assert len(popen_commands) == 2
    game_command, player_command = popen_commands
    assert network_commands == [["docker", "network", "inspect", LOCAL_DOCKER_NETWORK]]
    assert "coworld-play-game-session-1" in game_command
    assert "--network" in game_command
    assert game_command[game_command.index("--network") + 1] == LOCAL_DOCKER_NETWORK
    assert "--network-alias" in game_command
    assert game_command[game_command.index("--network-alias") + 1] == f"{LOCAL_GAME_NETWORK_ALIAS_PREFIX}session-1"
    assert f"{CONFIG_ENV_VAR}=file:///coworld/config.json" in game_command
    assert "coworld-play-player-session-1-0" in player_command
    assert "--network" in player_command
    assert player_command[player_command.index("--network") + 1] == LOCAL_DOCKER_NETWORK
    assert "--add-host" not in player_command
    assert "host.docker.internal:host-gateway" not in player_command
    assert "PLAYER_MODE=test" in player_command
    assert "COWORLD_PLAYER_WS_URL=ws://coworld-game-session-1:8080/player?slot=0&token=token-0" in player_command
    assert _image_command_slice(player_command) == [
        "--entrypoint",
        "python",
        "unit-test-runtime:latest",
        "-m",
        "unit_test.player",
    ]
    assert waited_players == [tmp_path / "play-workspace" / "logs" / "policy_agent_0.log"]
    assert ["docker", "rm", "-f", "coworld-play-player-session-1-0"] in rm_commands
    assert ["docker", "rm", "-f", "coworld-play-game-session-1"] in rm_commands


@pytest.mark.parametrize("session_token", ["session-token", None])
def test_play_coworld_injects_bedrock_env_into_player_containers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    session_token: str | None,
) -> None:
    coworld_manifest_path = _write_package_files(
        tmp_path,
        certification={
            "game_config": {"difficulty": "smoke"},
            "players": [{"player_id": "unit-test-player"}],
        },
        game_config={"difficulty": "watch"},
    )
    popen_commands: list[list[str]] = []
    popen_envs: list[dict[str, str] | None] = []
    rm_commands: list[list[str]] = []
    events: list[str] = []

    class FakeProcess:
        def wait(self) -> int:
            return 0

    def fake_resolve_bedrock_aws_env(*, aws_profile: str | None, aws_region: str | None) -> BedrockAwsEnv:
        events.append("resolve")
        assert aws_profile == "bedrock-dev"
        assert aws_region == "us-east-1"
        return BedrockAwsEnv(
            access_key_id="access-key",
            secret_access_key="secret-key",
            session_token=session_token,
            region="us-east-1",
        )

    def fake_popen(cmd, **kwargs):
        events.append("popen")
        popen_commands.append(cmd)
        popen_envs.append(kwargs.get("env"))
        return FakeProcess()

    def fake_subprocess_run(cmd, **kwargs):
        if cmd[:2] != ["docker", "network"]:
            rm_commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    def fake_ensure_local_docker_network() -> None:
        events.append("network")

    monkeypatch.setattr("coworld.play.assert_episode_images_reachable", lambda _job: None)
    monkeypatch.setattr("coworld.play.ensure_local_docker_network", fake_ensure_local_docker_network)
    monkeypatch.setattr("coworld.play._free_local_port", lambda: 1234)
    monkeypatch.setattr("coworld.play._wait_for_health", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("coworld.play._wait_for_game_exit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("coworld.play._wait_for_player_exit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("coworld.play._resolve_bedrock_aws_env", fake_resolve_bedrock_aws_env)
    monkeypatch.setattr("coworld.play.subprocess.Popen", fake_popen)
    monkeypatch.setattr("coworld.play.subprocess.run", fake_subprocess_run)
    monkeypatch.setattr("coworld.play.secrets.token_hex", lambda _bytes: "session-1")
    monkeypatch.setattr("coworld.runner.runner.secrets.token_urlsafe", lambda _bytes: "token-0")
    monkeypatch.setattr("coworld.play.load_results", lambda package, artifacts: {"scores": [1.0]})

    play_coworld(
        coworld_manifest_path,
        use_bedrock=True,
        aws_profile="bedrock-dev",
        aws_region="us-east-1",
        workspace=tmp_path / f"play-workspace-{session_token or 'static'}",
        on_ready=lambda _session: None,
    )

    assert events[:3] == ["network", "resolve", "popen"]
    assert len(popen_commands) == 2
    game_command, player_command = popen_commands
    game_env, player_env = popen_envs

    assert game_env is None
    assert not any(arg.startswith(("USE_BEDROCK", "AWS_")) for arg in game_command)

    for key in ("USE_BEDROCK", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION", "AWS_DEFAULT_REGION"):
        assert key in player_command
    secret_value_prefixes = ("AWS_ACCESS_KEY_ID=", "AWS_SECRET_ACCESS_KEY=", "AWS_SESSION_TOKEN=")
    assert not any(arg.startswith(secret_value_prefixes) for arg in player_command)

    assert player_env is not None
    assert player_env["USE_BEDROCK"] == "true"
    assert player_env["AWS_ACCESS_KEY_ID"] == "access-key"
    assert player_env["AWS_SECRET_ACCESS_KEY"] == "secret-key"
    assert player_env["AWS_REGION"] == "us-east-1"
    assert player_env["AWS_DEFAULT_REGION"] == "us-east-1"
    if session_token is None:
        assert "AWS_SESSION_TOKEN" not in player_env
        assert "AWS_SESSION_TOKEN" not in player_command
    else:
        assert player_env["AWS_SESSION_TOKEN"] == "session-token"
        assert "AWS_SESSION_TOKEN" in player_command

    assert ["docker", "rm", "-f", "coworld-play-player-session-1-0"] in rm_commands
    assert ["docker", "rm", "-f", "coworld-play-game-session-1"] in rm_commands


def test_play_coworld_does_not_resolve_bedrock_env_when_docker_network_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coworld_manifest_path = _write_package_files(
        tmp_path,
        certification={
            "game_config": {"difficulty": "smoke"},
            "players": [{"player_id": "unit-test-player"}],
        },
        game_config={"difficulty": "watch"},
    )
    resolve_calls: list[tuple[str | None, str | None]] = []
    popen_commands: list[list[str]] = []

    def fake_resolve_bedrock_aws_env(*, aws_profile: str | None, aws_region: str | None) -> BedrockAwsEnv:
        resolve_calls.append((aws_profile, aws_region))
        return BedrockAwsEnv(
            access_key_id="access-key",
            secret_access_key="secret-key",
            session_token=None,
            region="us-east-1",
        )

    def fake_ensure_local_docker_network() -> None:
        raise RuntimeError("Docker network unavailable")

    def fake_popen(cmd, **_kwargs):
        popen_commands.append(cmd)
        raise AssertionError("Docker containers should not start when network setup fails")

    monkeypatch.setattr("coworld.play.assert_episode_images_reachable", lambda _job: None)
    monkeypatch.setattr("coworld.play.ensure_local_docker_network", fake_ensure_local_docker_network)
    monkeypatch.setattr("coworld.play._free_local_port", lambda: 1234)
    monkeypatch.setattr("coworld.play._resolve_bedrock_aws_env", fake_resolve_bedrock_aws_env)
    monkeypatch.setattr("coworld.play.subprocess.Popen", fake_popen)
    monkeypatch.setattr("coworld.play.secrets.token_hex", lambda _bytes: "session-1")
    monkeypatch.setattr("coworld.runner.runner.secrets.token_urlsafe", lambda _bytes: "token-0")

    with pytest.raises(RuntimeError, match="Docker network unavailable"):
        play_coworld(
            coworld_manifest_path,
            use_bedrock=True,
            aws_profile="bedrock-dev",
            aws_region="us-east-1",
            workspace=tmp_path / "play-workspace-network-failure",
            on_ready=lambda _session: None,
        )

    assert resolve_calls == []
    assert popen_commands == []


def test_replay_urls_match_canonical_runtime_contract() -> None:
    replay_link = urlparse(replay_client_url(1234))
    websocket_path = urlparse(replay_session_path())

    assert REPLAY_SAVE_ENV_VAR == "COGAME_SAVE_REPLAY_URI"
    assert REPLAY_LOAD_ENV_VAR == "COGAME_LOAD_REPLAY_URI"
    assert replay_link.scheme == "http"
    assert replay_link.netloc == "127.0.0.1:1234"
    assert replay_link.path == "/client/replay"
    assert replay_link.query == ""
    assert websocket_path.path == "/replay"
    assert websocket_path.query == ""


def test_replay_coworld_starts_replay_container_and_reports_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coworld_manifest_path = _write_package_files(tmp_path)
    replay_path = tmp_path / "replay.json"
    replay_path.write_text("{}")
    ready_sessions: list[ReplaySession] = []
    popen_commands: list[list[str]] = []

    class FakeProcess:
        def wait(self) -> int:
            return 0

    def fake_popen(cmd, **kwargs):
        popen_commands.append(cmd)
        return FakeProcess()

    def noop_assert_docker_image_reachable(image: str, *, label: str) -> None:
        pass

    def noop_wait_for_health(
        port: int, process: subprocess.Popen, stderr_path: Path, *, timeout_seconds: float
    ) -> None:
        pass

    async def fail_require_replay_message(url, *, timeout_seconds):
        raise AssertionError("ordinary local replay should not pre-consume the replay websocket")

    monkeypatch.setattr("coworld.play.assert_docker_image_reachable", noop_assert_docker_image_reachable)
    monkeypatch.setattr("coworld.play._free_local_port", lambda: 1234)
    monkeypatch.setattr("coworld.play._wait_for_health", noop_wait_for_health)
    monkeypatch.setattr("coworld.play._require_replay_message", fail_require_replay_message)
    monkeypatch.setattr("coworld.play.subprocess.Popen", fake_popen)
    monkeypatch.setattr("coworld.play.secrets.token_hex", lambda _bytes: "session-1")
    monkeypatch.setattr(
        "coworld.play.subprocess.run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0),
    )

    session = replay_coworld(
        coworld_manifest_path,
        replay_path,
        workspace=tmp_path / "replay-workspace",
        on_ready=ready_sessions.append,
    )

    assert session.link == "http://127.0.0.1:1234/client/replay"
    assert ready_sessions == [session]
    command = popen_commands[0]
    assert f"{REPLAY_LOAD_ENV_VAR}=file:///coworld-replay/replay.json" in command
    assert f"{tmp_path}:/coworld-replay:ro" in command
    assert _image_command_slice(command) == [
        "--entrypoint",
        "python",
        "unit-test-runtime:latest",
        "-m",
        "unit_test.game",
    ]


def _replay_coworld_with_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    probe_behavior,
    timeout_seconds: float = 60.0,
):
    """Run replay_coworld with the readiness-probe coroutine swapped for a controlled fake.

    `probe_behavior` is an async callable invoked as `await probe_behavior(url, timeout_seconds=...)`.
    Returns (replay_coworld result or raised exception, popen_commands, rm_commands, probe_calls).
    """
    coworld_manifest_path = _write_package_files(tmp_path)
    replay_path = tmp_path / "replay.json"
    replay_path.write_text("{}")
    popen_commands: list[list[str]] = []
    rm_commands: list[list[str]] = []
    probe_calls: list[tuple[str, float]] = []

    class FakeProcess:
        def wait(self) -> int:
            return 0

    def fake_popen(cmd, **kwargs):
        popen_commands.append(cmd)
        return FakeProcess()

    def noop_assert_docker_image_reachable(image: str, *, label: str) -> None:
        pass

    def noop_wait_for_health(
        port: int, process: subprocess.Popen, stderr_path: Path, *, timeout_seconds: float
    ) -> None:
        pass

    async def wrapped_probe(url, *, timeout_seconds):
        probe_calls.append((url, timeout_seconds))
        return await probe_behavior(url, timeout_seconds=timeout_seconds)

    def fake_run(cmd, **kwargs):
        rm_commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("coworld.play.assert_docker_image_reachable", noop_assert_docker_image_reachable)
    monkeypatch.setattr("coworld.play._free_local_port", lambda: 1234)
    monkeypatch.setattr("coworld.play._wait_for_health", noop_wait_for_health)
    monkeypatch.setattr("coworld.play.subprocess.Popen", fake_popen)
    monkeypatch.setattr("coworld.play.secrets.token_hex", lambda _bytes: "session-1")
    monkeypatch.setattr("coworld.play.subprocess.run", fake_run)
    monkeypatch.setattr("coworld.play._require_replay_message", wrapped_probe)

    ready_sessions: list[ReplaySession] = []

    try:
        result = replay_coworld(
            coworld_manifest_path,
            replay_path,
            workspace=tmp_path / "replay-workspace",
            on_ready=ready_sessions.append,
            timeout_seconds=timeout_seconds,
            verify_replay=True,
        )
    except BaseException as exc:
        return exc, popen_commands, rm_commands, probe_calls, ready_sessions

    return result, popen_commands, rm_commands, probe_calls, ready_sessions


def test_replay_coworld_verify_replay_probes_replay_websocket_after_health_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Probe is invoked with /replay using timeout_seconds, succeeds, replay_coworld returns ReplaySession."""

    async def succeed(url, *, timeout_seconds):
        return None

    result, _, _, probe_calls, ready_sessions = _replay_coworld_with_probe(
        tmp_path, monkeypatch, probe_behavior=succeed, timeout_seconds=42.0
    )

    assert isinstance(result, ReplaySession), f"expected ReplaySession, got {result!r}"
    assert len(probe_calls) == 1, f"probe should be called exactly once, got {probe_calls}"
    probe_url, probe_timeout = probe_calls[0]
    parsed = urlparse(probe_url)
    assert parsed.scheme == "ws"
    assert parsed.netloc == "127.0.0.1:1234"
    assert parsed.path == "/replay"
    assert parsed.query == ""
    assert probe_timeout == 42.0
    assert ready_sessions == [result]


def test_replay_coworld_verify_replay_raises_when_replay_probe_times_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Probe asyncio.TimeoutError surfaces as a RuntimeError naming COGAME_LOAD_REPLAY_URI."""

    async def time_out(url, *, timeout_seconds):
        raise asyncio.TimeoutError("no frame received")

    result, _, _, _, ready_sessions = _replay_coworld_with_probe(tmp_path, monkeypatch, probe_behavior=time_out)

    assert isinstance(result, RuntimeError), f"expected RuntimeError, got {result!r}"
    message = str(result)
    assert "COGAME_LOAD_REPLAY_URI" in message, message
    assert "replay mode" in message.lower(), message
    assert "file:///coworld-replay/replay.json" in message, message
    # The original error should be chained for debuggability.
    assert isinstance(result.__cause__, asyncio.TimeoutError)
    # Probe failure surfaces before on_ready, so the user never sees a bad URL.
    assert ready_sessions == []


@pytest.mark.parametrize(
    "exc_factory",
    [
        lambda: asyncio.TimeoutError("timed out"),
        lambda: ConnectionRefusedError("connection refused"),
        lambda: AssertionError("Replay viewer received an empty message from ws://..."),
        lambda: RuntimeError("upgrade rejected with HTTP 404"),
    ],
)
def test_replay_coworld_verify_replay_wraps_any_probe_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exc_factory
) -> None:
    """Any normal exception raised by the probe is wrapped in a single RuntimeError with our diagnostic message."""

    async def raise_specific(url, *, timeout_seconds):
        raise exc_factory()

    result, _, _, _, _ = _replay_coworld_with_probe(tmp_path, monkeypatch, probe_behavior=raise_specific)

    assert isinstance(result, RuntimeError)
    assert "COGAME_LOAD_REPLAY_URI" in str(result)


def test_replay_coworld_verify_replay_tears_down_container_on_probe_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On probe failure, docker rm -f for the replay container still runs via the finally block."""

    async def time_out(url, *, timeout_seconds):
        raise asyncio.TimeoutError("no frame")

    result, popen_commands, rm_commands, _, _ = _replay_coworld_with_probe(
        tmp_path, monkeypatch, probe_behavior=time_out
    )

    assert isinstance(result, RuntimeError)
    # The replay container was started.
    assert len(popen_commands) == 1
    # The replay container was torn down even though the probe failed.
    replay_container_names = [cmd[-1] for cmd in rm_commands if cmd[:3] == ["docker", "rm", "-f"]]
    assert replay_container_names, f"expected docker rm -f cleanup, got {rm_commands}"
    assert replay_container_names[0].startswith("coworld-replay-game-")


@pytest.mark.parametrize(
    "exc_factory",
    [
        lambda: KeyboardInterrupt(),
        lambda: SystemExit(1),
        lambda: asyncio.CancelledError(),
    ],
)
def test_replay_coworld_verify_replay_lets_interrupts_escape_probe_wrapper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exc_factory
) -> None:
    """Operator interrupts (Ctrl-C, SystemExit) and runner cancellation must propagate
    out of the readiness-probe wrapper, not get reported as a replay-server-mode failure."""

    async def interrupt(url, *, timeout_seconds):
        raise exc_factory()

    expected_exc_type = type(exc_factory())
    result, _, rm_commands, _, _ = _replay_coworld_with_probe(tmp_path, monkeypatch, probe_behavior=interrupt)

    assert isinstance(result, expected_exc_type), f"expected {expected_exc_type.__name__} to propagate, got {result!r}"
    # Even when an interrupt propagates, the container teardown finally still runs.
    assert any(cmd[:3] == ["docker", "rm", "-f"] for cmd in rm_commands), (
        f"expected docker rm -f cleanup even on interrupt, got {rm_commands}"
    )


def test_replay_coworld_verify_replay_does_not_call_on_ready_until_probe_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """on_ready must be invoked AFTER the readiness probe returns, so the user only sees a working URL."""

    order: list[str] = []

    async def record_probe(url, *, timeout_seconds):
        order.append("probe")
        return None

    coworld_manifest_path = _write_package_files(tmp_path)
    replay_path = tmp_path / "replay.json"
    replay_path.write_text("{}")

    class FakeProcess:
        def wait(self) -> int:
            order.append("wait")
            return 0

    monkeypatch.setattr("coworld.play.assert_docker_image_reachable", lambda image, *, label: None)
    monkeypatch.setattr("coworld.play._free_local_port", lambda: 1234)
    monkeypatch.setattr(
        "coworld.play._wait_for_health",
        lambda *args, **kwargs: order.append("health"),
    )
    monkeypatch.setattr("coworld.play.subprocess.Popen", lambda cmd, **kwargs: FakeProcess())
    monkeypatch.setattr("coworld.play.secrets.token_hex", lambda _bytes: "session-1")
    monkeypatch.setattr(
        "coworld.play.subprocess.run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0),
    )
    monkeypatch.setattr("coworld.play._require_replay_message", record_probe)

    def on_ready(_session):
        order.append("on_ready")

    replay_coworld(
        coworld_manifest_path,
        replay_path,
        workspace=tmp_path / "replay-workspace",
        on_ready=on_ready,
        verify_replay=True,
    )

    assert order.index("health") < order.index("probe") < order.index("on_ready") < order.index("wait"), order


def test_runnable_run_overrides_docker_entrypoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = _write_package(tmp_path)
    game_command = _image_command(package.game)
    player = build_player_launch_specs(build_episode_request(package, EpisodeArtifacts.create(tmp_path / "cert")))[0]
    player_command = _image_command(player)

    assert game_command == ["--entrypoint", "python", "unit-test-runtime:latest", "-m", "unit_test.game"]
    assert player_command == ["--entrypoint", "python", "unit-test-runtime:latest", "-m", "unit_test.player"]


def test_example_coworld_manifest_validates(tmp_path: Path) -> None:
    package = load_coworld_package(_materialized_template(tmp_path, _example_root() / "coworld_manifest_template.json"))
    config = build_game_config(package, ["token-0", "token-1"])
    assert package.game.image == "coworld-paintarena:latest"
    assert package.game.run == ("python", "-m", "coworld.examples.paintarena.game.server")
    assert (
        package.manifest.game.protocols.player.value
        == "https://github.com/Metta-AI/coworld/blob/main/src/coworld/examples/paintarena/game/docs/player_protocol_spec.md"
    )
    assert (
        package.manifest.game.protocols.global_.value
        == "https://github.com/Metta-AI/coworld/blob/main/src/coworld/examples/paintarena/game/docs/global_protocol_spec.md"
    )
    assert package.manifest.player[0].image == "coworld-paintarena:latest"
    assert package.manifest.player[0].run == ["python", "-m", "coworld.examples.paintarena.player.player"]
    assert config["tokens"] == ["token-0", "token-1"]


def test_paintarena_snapshots_are_independent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "tokens": ["token-0", "token-1"],
                "players": [{"name": "Sweep Painter 1"}, {"name": "Sweep Painter 2"}],
                "width": 12,
                "height": 8,
                "max_ticks": 100,
                "tick_rate": 5,
            }
        )
    )
    monkeypatch.setenv(CONFIG_ENV_VAR, config_path.as_uri())
    monkeypatch.setenv(RESULTS_ENV_VAR, (tmp_path / "results.json").as_uri())
    monkeypatch.setenv(REPLAY_SAVE_ENV_VAR, (tmp_path / "replay.json").as_uri())
    monkeypatch.delenv(REPLAY_LOAD_ENV_VAR, raising=False)

    server_module = _reload_paintarena_server()

    first_snapshot = server_module._snapshot()
    server_module._step()
    second_snapshot = server_module._snapshot()
    server_module._step()

    assert first_snapshot["positions"] == [[0, 0], [11, 7]]
    assert first_snapshot["tile_owners"] == [-1 for _ in range(96)]
    assert first_snapshot["scores"] == [0, 0]
    assert first_snapshot["player_names"] == ["Sweep Painter 1", "Sweep Painter 2"]
    assert server_module._replay_payload({"scores": [0.0, 0.0]})["player_names"] == [
        "Sweep Painter 1",
        "Sweep Painter 2",
    ]
    assert second_snapshot["positions"] == [[0, 0], [11, 7]]
    assert second_snapshot["tile_owners"][0] == 0
    assert second_snapshot["tile_owners"][-1] == 1
    assert second_snapshot["scores"] == [1, 1]


def test_paintarena_starts_after_player_connect_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.json"
    results_path = tmp_path / "results.json"
    replay_path = tmp_path / "replay.json"
    config_path.write_text(
        json.dumps(
            {
                "tokens": ["token-0", "token-1"],
                "players": [{"name": "Sweep Painter 1"}, {"name": "Sweep Painter 2"}],
                "width": 12,
                "height": 8,
                "max_ticks": 1,
                "tick_rate": 100,
                "player_connect_timeout_seconds": 0.01,
            }
        )
    )
    monkeypatch.setenv(CONFIG_ENV_VAR, config_path.as_uri())
    monkeypatch.setenv(RESULTS_ENV_VAR, results_path.as_uri())
    monkeypatch.setenv(REPLAY_SAVE_ENV_VAR, replay_path.as_uri())
    monkeypatch.delenv(REPLAY_LOAD_ENV_VAR, raising=False)

    server_module = _reload_paintarena_server()
    server_module_typed = cast(Any, server_module)
    server_module_typed.server = SimpleNamespace(should_exit=False)

    with TestClient(server_module_typed.app):
        deadline = time.monotonic() + 1
        while not results_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)

    assert json.loads(results_path.read_text()) == {"scores": [1.0, 1.0], "painted_tiles": [1, 1], "ticks": 1}
    assert json.loads(replay_path.read_text())["frames"][0]["started"] is True


def test_paintarena_disconnected_player_noops_after_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.json"
    results_path = tmp_path / "results.json"
    replay_path = tmp_path / "replay.json"
    config_path.write_text(
        json.dumps(
            {
                "tokens": ["token-0", "token-1"],
                "players": [{"name": "Sweep Painter 1"}, {"name": "Sweep Painter 2"}],
                "width": 12,
                "height": 8,
                "max_ticks": 1,
                "tick_rate": 100,
                "player_connect_timeout_seconds": 0.05,
            }
        )
    )
    monkeypatch.setenv(CONFIG_ENV_VAR, config_path.as_uri())
    monkeypatch.setenv(RESULTS_ENV_VAR, results_path.as_uri())
    monkeypatch.setenv(REPLAY_SAVE_ENV_VAR, replay_path.as_uri())
    monkeypatch.delenv(REPLAY_LOAD_ENV_VAR, raising=False)

    server_module = _reload_paintarena_server()
    server_module_typed = cast(Any, server_module)
    server_module_typed.server = SimpleNamespace(should_exit=False)

    with TestClient(server_module_typed.app) as client:
        with client.websocket_connect("/player?slot=0&token=token-0") as websocket:
            assert websocket.receive_json()["slot"] == 0
        deadline = time.monotonic() + 1
        while not results_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)

    assert json.loads(results_path.read_text()) == {"scores": [1.0, 1.0], "painted_tiles": [1, 1], "ticks": 1}
    assert json.loads(replay_path.read_text())["frames"][0]["started"] is True


def test_cogs_vs_clips_coworld_manifest_validates(tmp_path: Path) -> None:
    package = load_coworld_package(
        _materialized_template(tmp_path, _world_root("cogs_vs_clips") / "coworld_manifest_template.json")
    )
    tokens = [f"token-{index}" for index in range(8)]
    config = build_game_config(package, tokens)

    assert package.manifest.game.name == "cogs_vs_clips"
    assert package.game.image == "coworld-cogs-vs-clips-game:latest"
    assert package.game.run == ("python", "/app/server.py")
    assert package.manifest.game.runnable.source_url == "https://github.com/Metta-AI/coworld-cogs-vs-clips/tree/main"
    assert package.manifest.game.protocols.player.value == (
        "https://github.com/Metta-AI/coworld-cogs-vs-clips/blob/main/coworld/game/docs/player_protocol_spec.md"
    )
    assert package.manifest.game.protocols.global_.value == (
        "https://github.com/Metta-AI/coworld-cogs-vs-clips/blob/main/coworld/game/docs/global_protocol_spec.md"
    )
    assert package.manifest.game.docs.readme is not None
    assert (
        package.manifest.game.docs.readme.value
        == "https://github.com/Metta-AI/coworld-cogs-vs-clips/blob/main/README.md"
    )
    pages = {page.id: page.content.value for page in package.manifest.game.docs.pages}
    assert "rules.md" not in pages
    assert pages["play_cogsvsclips.md"] == "https://softmax.com/play_cogsvsclips.md"
    assert package.manifest.player[0].id == "reference-player"
    assert package.manifest.player[0].image == "coworld-cogs-vs-clips-reference-player:latest"
    assert package.manifest.player[0].run == ["python", "/app/coworld_reference_player.py"]
    assert package.manifest.player[0].source_url == (
        "https://github.com/Metta-AI/coworld-cogs-vs-clips/tree/main/coworld/player"
    )
    assert package.manifest.player[0].env == {}
    assert package.manifest.commissioner[0].id == "cogs-vs-clips-commissioner"
    assert package.manifest.commissioner[0].image == "coworld-cogs-vs-clips-commissioner:latest"
    assert package.manifest.commissioner[0].source_url == (
        "https://github.com/Metta-AI/commissioners/tree/main/commissioners/cogs_vs_clips/cogs_vs_clips_commissioner"
    )
    daily_variant = next(variant for variant in package.manifest.variants if variant.id == "machina-1-daily")
    assert daily_variant.game_config["max_steps"] == 10000
    assert config == {
        "players": [
            {"name": "Player 1"},
            {"name": "Player 2"},
            {"name": "Player 3"},
            {"name": "Player 4"},
            {"name": "Player 5"},
            {"name": "Player 6"},
            {"name": "Player 7"},
            {"name": "Player 8"},
        ],
        "mission": "cogsguard",
        "max_steps": 3,
        "seed": 0,
        "step_seconds": 0.02,
        "tokens": tokens,
    }


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True, timeout=10)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.mark.slow
@pytest.mark.skip(reason="Docker certifier integration is too slow for CI")
@pytest.mark.skipif(not _docker_available(), reason="Docker not available")
def test_paintarena_example_certifies_with_docker(tmp_path: Path) -> None:
    example_root = _example_root()
    subprocess.run(
        ["docker", "build", "-t", "coworld-paintarena:latest", "."],
        cwd=example_root,
        check=True,
        timeout=300,
    )

    result = certify_coworld(
        _materialized_template(tmp_path, _example_root() / "coworld_manifest_template.json"),
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


def _package_with_player_source_url(tmp_path: Path, source_url: str):
    coworld_manifest_path = _write_package_files(tmp_path)
    manifest = json.loads(coworld_manifest_path.read_text(encoding="utf-8"))
    manifest["player"][0]["source_url"] = source_url
    manifest["grader"][0].pop("source_url")
    coworld_manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return load_coworld_package(coworld_manifest_path)


def _materialized_template(tmp_path: Path, template_path: Path) -> Path:
    manifest = json.loads(template_path.read_text(encoding="utf-8"))
    manifest["game"]["version"] = "0.1.0"
    image_placeholders = {
        "cogs_vs_clips": {
            "{{GAME_IMAGE}}": "coworld-cogs-vs-clips-game:latest",
            "{{PLAYER_IMAGE}}": "coworld-cogs-vs-clips-reference-player:latest",
            "{{REPORTER_IMAGE}}": "coworld-default-reporter:latest",
            "{{COGS_VS_CLIPS_REPORTER_IMAGE}}": "coworld-cogs-vs-clips-summarizer:latest",
            "{{COGS_VS_CLIPS_COMMISSIONER_IMAGE}}": "coworld-cogs-vs-clips-commissioner:latest",
        },
        "paintarena": {"{{PAINTARENA_IMAGE}}": "coworld-paintarena:latest"},
    }
    if template_path.parent.name in image_placeholders:
        placeholders = image_placeholders[template_path.parent.name]
        game_image = manifest["game"]["runnable"]["image"]
        if game_image in placeholders:
            manifest["game"]["runnable"]["image"] = placeholders[game_image]
        for section in ("player", "commissioner", "reporter", "grader", "diagnoser", "optimizer"):
            if section in manifest:
                for runnable in manifest[section]:
                    image = runnable["image"]
                    if image in placeholders:
                        runnable["image"] = placeholders[image]
    manifest_path = tmp_path / template_path.parent.name / "coworld_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
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
        "reporter": [
            {
                "id": "unit-test-reporter",
                "name": "Unit Test Reporter",
                "type": "reporter",
                "image": "ghcr.io/metta-ai/reporters-default:latest",
                "description": "Default reporter stub for unit tests.",
                "purpose": "narrative",
                "output_format": "text/markdown",
            }
        ],
        "grader": [
            {
                "id": "unit-test-grader",
                "name": "Unit Test Grader",
                "type": "grader",
                "image": "ghcr.io/metta-ai/graders-default:latest",
                "source_url": "https://github.com/Metta-AI/graders/tree/main/graders/default/default_grader",
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


def _world_root(coworld_name: str) -> Path:
    return Path(__file__).resolve().parents[3] / "worlds" / coworld_name


def _reload_paintarena_server() -> Any:
    # Each test patches the COGAME_* env vars before calling this, and
    # server.py reads them at import time. import_module gets (or first-
    # loads) the module under the patched environment; reload re-runs the
    # module-level code on subsequent test cases.
    return importlib.reload(importlib.import_module("coworld.examples.paintarena.game.server"))


def _image_command_slice(command: list[str]) -> list[str]:
    entrypoint_index = command.index("--entrypoint")
    return command[entrypoint_index:]
