import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, cast
from urllib.parse import urlparse
from urllib.request import url2pathname

import pytest
from pytest import MonkeyPatch
from pytest_httpserver import HTTPServer
from typer.testing import CliRunner

from coworld.certifier import load_executable_transcript
from coworld.cli import app
from coworld.runner.runner import EpisodeArtifacts
from coworld.types import CoworldEpisodeJobSpec, CoworldPlayerFileSpec, StepResult
from coworld.upload import _certification_cache_key, _certified_manifest_cache_path

COWORLD_ID = "cow_00000000-0000-0000-0000-000000000001"
COWORLD_PATH = f"/v2/coworlds/{COWORLD_ID}"


def test_coworld_play_accepts_backend_coworld_path(httpserver: HTTPServer, monkeypatch: MonkeyPatch) -> None:
    manifest = {"game": {"name": "downloaded"}}
    httpserver.expect_request(COWORLD_PATH).respond_with_json({"manifest": manifest})
    captured: dict[str, object] = {}

    def fake_play_coworld(manifest_path: Path, **kwargs: object) -> SimpleNamespace:
        captured["manifest"] = json.loads(manifest_path.read_text())
        artifacts = SimpleNamespace(
            workspace=Path("/tmp/workspace"),
            results_path=Path("/tmp/results.json"),
            replay_path=Path("/tmp/replay.json"),
            logs_dir=Path("/tmp/logs"),
        )
        return SimpleNamespace(session=SimpleNamespace(artifacts=artifacts), results={})

    monkeypatch.setattr("coworld.cli.play_coworld", fake_play_coworld)

    result = CliRunner().invoke(app, ["play", COWORLD_PATH, "--server", httpserver.url_for("")])

    assert result.exit_code == 0, result.output
    assert captured["manifest"] == manifest


def test_coworld_replay_resolves_coworld_id_against_site_api_server(
    tmp_path: Path, httpserver: HTTPServer, monkeypatch: MonkeyPatch
) -> None:
    manifest = {"game": {"name": "downloaded"}}
    replay_path = tmp_path / "replay.json"
    replay_path.write_text('{"events":[]}', encoding="utf-8")
    httpserver.expect_request(f"/api/observatory{COWORLD_PATH}").respond_with_json({"manifest": manifest})
    captured: dict[str, object] = {}

    def fake_replay_coworld(
        resolved_manifest_path: Path,
        resolved_replay_path: Path,
        **_kwargs: object,
    ) -> SimpleNamespace:
        captured["manifest"] = json.loads(resolved_manifest_path.read_text())
        captured["replay_path"] = resolved_replay_path
        return SimpleNamespace(artifacts=SimpleNamespace(logs_dir=Path("/tmp/logs")))

    monkeypatch.setattr("coworld.cli.replay_coworld", fake_replay_coworld)

    result = CliRunner().invoke(
        app,
        ["replay", COWORLD_ID, str(replay_path), "--server", httpserver.url_for("/api")],
    )

    assert result.exit_code == 0, result.output
    assert captured["manifest"] == manifest
    assert captured["replay_path"] == replay_path.resolve()


def test_coworld_certify_failure_writes_failed_report(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    opened_urls: list[str] = []
    manifest_path = _example_manifest(tmp_path)
    transcript = load_executable_transcript()
    step_by_id = {step.id: step for step in transcript.steps}

    def fake_certify_coworld(_manifest_path: Path, **kwargs: object) -> SimpleNamespace:
        on_step = cast(Callable[[StepResult, object], None], kwargs["on_step"])
        on_step(
            StepResult(id="matriculate", kind=step_by_id["matriculate"].kind, status="pass"),
            step_by_id["matriculate"],
        )
        on_step(
            StepResult(
                id="images-reachable",
                kind=step_by_id["images-reachable"].kind,
                status="fail",
                failure_reason="image_unreachable",
                feedback="missing image ghcr.io/example/missing:latest\ncheck registry credentials",
            ),
            step_by_id["images-reachable"],
        )
        raise RuntimeError("image validation failed")

    monkeypatch.setattr("coworld.cli.certify_coworld", fake_certify_coworld)
    monkeypatch.setattr("coworld.cli.webbrowser.open", opened_urls.append)

    result = CliRunner().invoke(app, ["certify", str(manifest_path)])

    assert result.exit_code == 1, result.output
    assert "Failure reason: image_unreachable" in result.output
    report_path = Path(url2pathname(urlparse(opened_urls[0]).path))
    html = report_path.read_text(encoding="utf-8")
    assert "image_unreachable" in html
    assert "Passed" not in html


def test_coworld_certify_error_without_failed_step_marks_report_failed(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    opened_urls: list[str] = []
    manifest_path = _example_manifest(tmp_path)
    transcript = load_executable_transcript()
    step_by_id = {step.id: step for step in transcript.steps}

    def fake_certify_coworld(_manifest_path: Path, **kwargs: object) -> SimpleNamespace:
        on_step = cast(Callable[[StepResult, object], None], kwargs["on_step"])
        on_step(
            StepResult(id="matriculate", kind=step_by_id["matriculate"].kind, status="pass"),
            step_by_id["matriculate"],
        )
        raise RuntimeError("runner crashed before verdict")

    monkeypatch.setattr("coworld.cli.certify_coworld", fake_certify_coworld)
    monkeypatch.setattr("coworld.cli.webbrowser.open", opened_urls.append)

    result = CliRunner().invoke(app, ["certify", str(manifest_path)])

    assert result.exit_code == 1, result.output
    report_path = Path(url2pathname(urlparse(opened_urls[0]).path))
    html = report_path.read_text(encoding="utf-8")
    assert "runner crashed before verdict" in html
    assert "Passed" not in html


def test_coworld_certify_schema_failure_prints_actionable_detail(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    manifest_path = tmp_path / "coworld_manifest.json"
    manifest_path.write_text('{"tags": ["test", "multiplayer", "real-time"]}\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["certify", str(manifest_path), "--no-open-report"])

    assert result.exit_code == 1, result.output
    assert "Failure reason: manifest_invalid" in result.output


def test_run_episode_downloads_missing_coworld_id_cache(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = json.loads(_example_manifest(tmp_path).read_text(encoding="utf-8"))
    downloads: list[tuple[str, Path, str, bool]] = []
    captured: dict[str, object] = {}

    def fake_download_coworld_cmd(
        coworld_ref: str,
        output_dir: Path,
        *,
        server: str,
        refresh: bool = False,
    ) -> None:
        downloads.append((coworld_ref, output_dir, server, refresh))
        manifest_path = output_dir / coworld_ref / "coworld_manifest.json"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        (output_dir / coworld_ref / "coworld_images.json").write_text('{"images": []}', encoding="utf-8")

    def fake_run_coworld_episode(spec: CoworldEpisodeJobSpec, artifacts: object, **_kwargs: object) -> None:
        captured["spec"] = spec
        captured["artifacts"] = artifacts

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("coworld.cli.download_coworld_cmd", fake_download_coworld_cmd)
    monkeypatch.setattr("coworld.cli.run_coworld_episode", fake_run_coworld_episode)

    result = CliRunner().invoke(app, ["run-episode", COWORLD_ID, "--server", "http://example.test"])

    assert result.exit_code == 0, result.output
    assert downloads == [(COWORLD_ID, Path("./coworld"), "http://example.test", False)]
    assert cast(CoworldEpisodeJobSpec, captured["spec"]).manifest.game.name == manifest["game"]["name"]
    assert cast(EpisodeArtifacts, captured["artifacts"]).workspace == (tmp_path / "coworld" / COWORLD_ID / "results")


def test_run_episode_passes_exact_game_hosted_player_paths(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    manifest_path = _game_hosted_manifest(tmp_path)
    first = tmp_path / "first.wasm"
    second = tmp_path / "second.wasm"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    spec, kwargs = _invoke_run_episode(monkeypatch, tmp_path, str(manifest_path), str(first), str(second))

    assert all(isinstance(player, CoworldPlayerFileSpec) for player in spec.players)
    assert [cast(CoworldPlayerFileSpec, player).content_hash for player in spec.players] == [
        hashlib.sha256(b"first").hexdigest(),
        hashlib.sha256(b"second").hexdigest(),
    ]
    assert kwargs["player_file_paths"] == [first, second]


def test_run_episode_defaults_game_hosted_paths_to_certification_files(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    manifest_path = _game_hosted_manifest(tmp_path)

    _spec, kwargs = _invoke_run_episode(monkeypatch, tmp_path, str(manifest_path))

    assert kwargs["player_file_paths"] == [manifest_path.parent / "players/player.wasm"] * 2


@pytest.mark.parametrize(
    "args",
    [
        ["--run", "python"],
        ["--secret-env", "TOKEN=value"],
        ["--use-llm"],
    ],
)
def test_run_episode_rejects_image_options_for_game_hosted_manifest(
    monkeypatch: MonkeyPatch, tmp_path: Path, args: list[str]
) -> None:
    manifest_path = _game_hosted_manifest(tmp_path)

    result = CliRunner().invoke(app, ["run-episode", str(manifest_path), *args])

    assert result.exit_code != 0
    assert "game-hosted Coworlds do not support" in result.output


def test_run_episode_player_image_override_does_not_invent_manifest_env(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec, _kwargs = _invoke_run_episode(
        monkeypatch,
        tmp_path,
        str(_cogs_vs_clips_manifest(tmp_path)),
        "custom-policy-player:latest",
        "--run",
        "python",
        "--run",
        "/app/player.py",
    )

    assert [player.image for player in spec.players] == ["custom-policy-player:latest"] * 8
    assert [player.run for player in spec.players] == [["python", "/app/player.py"]] * 8
    assert [player.env for player in spec.players] == [{}] * 8


def test_run_episode_accepts_episode_request_file_with_per_slot_env(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest_path = _example_manifest(tmp_path)
    request_path = _write_episode_request(tmp_path, manifest_path)

    spec, _kwargs = _invoke_run_episode(monkeypatch, tmp_path, str(manifest_path), str(request_path))

    assert spec.game_config["max_ticks"] == 3
    assert [player.image for player in spec.players] == ["slot-zero:latest", "slot-one:latest"]
    assert [player.run for player in spec.players] == [["python", "/slot-zero.py"], ["python", "/slot-one.py"]]
    assert [player.env for player in spec.players] == [{"PLAYER_SLOT": "0"}, {"PLAYER_SLOT": "1"}]
    assert spec.game_config["players"] == [{"name": "slot-zero:v1"}, {"name": "slot-one:v1"}]


def test_run_episode_runs_multiple_local_episodes_with_seed_variation(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: list[tuple[CoworldEpisodeJobSpec, EpisodeArtifacts, dict[str, object]]] = []

    def fake_run_coworld_episode(spec: CoworldEpisodeJobSpec, artifacts: object, **kwargs: object) -> None:
        captured.append((spec, cast(EpisodeArtifacts, artifacts), kwargs))

    monkeypatch.setattr("coworld.cli.run_coworld_episode", fake_run_coworld_episode)
    manifest_path = _cogs_vs_clips_manifest(tmp_path)
    artifacts_root = (manifest_path.parent / "results").resolve()

    result = CliRunner().invoke(
        app,
        [
            "run-episode",
            str(manifest_path),
            "my-player:latest",
            "--run",
            "python",
            "--run",
            "/app/player.py",
            "--episodes",
            "2",
        ],
    )

    assert result.exit_code == 0, result.output
    assert [spec.game_config["seed"] for spec, _artifacts, _kwargs in captured] == [0, 1]
    assert [artifacts.workspace for _spec, artifacts, _kwargs in captured] == [
        artifacts_root / "episode-0001",
        artifacts_root / "episode-0002",
    ]


def _invoke_run_episode(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    *args: str,
) -> tuple[CoworldEpisodeJobSpec, dict[str, object]]:
    captured: dict[str, object] = {}

    def fake_run_coworld_episode(spec: CoworldEpisodeJobSpec, _artifacts: object, **kwargs: object) -> None:
        captured["spec"] = spec
        captured["kwargs"] = kwargs

    monkeypatch.setattr("coworld.cli.run_coworld_episode", fake_run_coworld_episode)
    result = CliRunner().invoke(
        app,
        ["run-episode", *args, "--output-dir", str(tmp_path / "episode")],
    )

    assert result.exit_code == 0, result.output
    return cast(CoworldEpisodeJobSpec, captured["spec"]), cast(dict[str, object], captured["kwargs"])


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


def _game_hosted_manifest(tmp_path: Path) -> Path:
    manifest_path = _example_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["game"]["player_runtime"] = "game-hosted"
    for player in manifest["player"]:
        player.pop("image")
        player["file"] = "players/player.wasm"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    player_path = manifest_path.parent / "players/player.wasm"
    player_path.parent.mkdir(parents=True)
    player_path.write_bytes(b"fixture-player")
    return manifest_path


def _cogs_vs_clips_manifest(tmp_path: Path) -> Path:
    players = [{"name": f"Player {slot + 1}"} for slot in range(8)]
    game_config = {
        "players": players,
        "mission": "machina_1",
        "max_steps": 10000,
        "seed": 0,
        "step_seconds": 0.02,
    }
    manifest_path = tmp_path / "cogs_vs_clips" / "coworld_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "tags": ["strategy", "multiplayer", "real-time"],
                "game": {
                    "name": "cogs_vs_clips",
                    "version": "0.1.0",
                    "description": "Cogs vs Clips CLI fixture.",
                    "owner": "cogames@softmax.com",
                    "runnable": {"type": "game", "image": "coworld-cogs-vs-clips-game:latest"},
                    "config_schema": {
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "type": "object",
                        "required": ["tokens", "players"],
                        "properties": {
                            "tokens": {
                                "type": "array",
                                "minItems": 8,
                                "maxItems": 8,
                                "items": {"type": "string", "minLength": 1},
                            },
                            "players": {
                                "type": "array",
                                "minItems": 8,
                                "maxItems": 8,
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": ["name"],
                                    "properties": {"name": {"type": "string", "minLength": 1}},
                                },
                            },
                        },
                    },
                    "results_schema": {},
                    "protocols": {
                        "player": {"type": "uri", "value": "https://example.com/player.md"},
                        "global": {"type": "uri", "value": "https://example.com/global.md"},
                    },
                    "docs": {
                        "readme": {"type": "uri", "value": "https://example.com/README.md"},
                        "pages": [],
                    },
                },
                "player": [
                    {
                        "id": "reference-player",
                        "name": "Reference Player",
                        "type": "player",
                        "image": "coworld-cogs-vs-clips-reference-player:latest",
                        "run": ["python", "/app/coworld_reference_player.py"],
                        "description": "Cogs vs Clips CLI player fixture.",
                    }
                ],
                "commissioner": [],
                "reporter": [],
                "grader": [],
                "diagnoser": [],
                "optimizer": [],
                "variants": [
                    {
                        "id": "machina-1-daily",
                        "name": "Machina 1 Daily",
                        "game_config": game_config,
                        "description": "Cogs vs Clips CLI variant fixture.",
                    }
                ],
                "certification": {
                    "game_config": {**game_config, "mission": "cogsguard", "max_steps": 3},
                    "players": [{"player_id": "reference-player"} for _slot in range(8)],
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


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


def _write_episode_request(tmp_path: Path, manifest_path: Path) -> Path:
    request_path = tmp_path / "episode_request.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    request_path.write_text(
        json.dumps(
            {
                "manifest": manifest,
                "game_config": {
                    "width": 12,
                    "height": 8,
                    "max_ticks": 3,
                    "tick_rate": 5,
                    "player_connect_timeout_seconds": 0.1,
                    "players": [{"name": "slot-zero:v1"}, {"name": "slot-one:v1"}],
                },
                "players": [
                    {
                        "type": "player",
                        "image": "slot-zero:latest",
                        "run": ["python", "/slot-zero.py"],
                        "env": {"PLAYER_SLOT": "0"},
                    },
                    {
                        "type": "player",
                        "image": "slot-one:latest",
                        "run": ["python", "/slot-one.py"],
                        "env": {"PLAYER_SLOT": "1"},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return request_path


def test_run_episode_rejects_digest_referenced_player_files_from_a_backend_manifest(
    httpserver: HTTPServer,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = json.loads(_game_hosted_manifest(tmp_path).read_text(encoding="utf-8"))
    for player in manifest["player"]:
        player["file"] = f"sha256:{'a' * 64}"
    httpserver.expect_request(COWORLD_PATH).respond_with_json({"manifest": manifest})
    monkeypatch.setattr(
        "coworld.cli.run_coworld_episode",
        lambda *_args, **_kwargs: pytest.fail("run-episode started without player files"),
    )
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["run-episode", COWORLD_PATH, "--server", httpserver.url_for("")])

    assert result.exit_code != 0
    assert "coworld download" in result.output


def test_run_episode_overrides_do_not_require_the_bundled_fixture(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    manifest_path = _game_hosted_manifest(tmp_path)
    (manifest_path.parent / "players/player.wasm").unlink()
    overrides = [tmp_path / "first.wasm", tmp_path / "second.wasm"]
    overrides[0].write_bytes(b"first")
    overrides[1].write_bytes(b"second")
    captured: dict[str, object] = {}

    def fake_run_coworld_episode(spec: CoworldEpisodeJobSpec, artifacts: object, **kwargs: object) -> None:
        captured["spec"] = spec
        captured["kwargs"] = kwargs

    monkeypatch.setattr("coworld.cli.run_coworld_episode", fake_run_coworld_episode)

    result = CliRunner().invoke(app, ["run-episode", str(manifest_path), str(overrides[0]), str(overrides[1])])

    assert result.exit_code == 0, result.output
    spec = cast(CoworldEpisodeJobSpec, captured["spec"])
    assert [cast(CoworldPlayerFileSpec, player).content_hash for player in spec.players] == [
        hashlib.sha256(b"first").hexdigest(),
        hashlib.sha256(b"second").hexdigest(),
    ]
    assert cast(dict[str, object], captured["kwargs"])["player_file_paths"] == overrides


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
