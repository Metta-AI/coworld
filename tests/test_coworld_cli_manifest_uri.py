import json
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, cast

from pytest import MonkeyPatch
from pytest_httpserver import HTTPServer
from typer.testing import CliRunner

from coworld.cli import app
from coworld.runner.runner import EpisodeArtifacts
from coworld.types import CoworldEpisodeJobSpec

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
            compressed_replay_path=Path("/tmp/replay.json.z"),
            logs_dir=Path("/tmp/logs"),
        )
        return SimpleNamespace(session=SimpleNamespace(artifacts=artifacts), results={})

    monkeypatch.setattr("coworld.cli.play_coworld", fake_play_coworld)

    result = CliRunner().invoke(app, ["play", COWORLD_PATH, "--server", httpserver.url_for("")])

    assert result.exit_code == 0, result.output
    assert captured["manifest"] == manifest


def test_coworld_play_prefers_cached_coworld_id_manifest(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    manifest = {"game": {"name": "cached"}}
    manifest_path = tmp_path / "coworld" / COWORLD_ID / "coworld_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_play_coworld(resolved_manifest_path: Path, **_kwargs: object) -> SimpleNamespace:
        captured["manifest_path"] = resolved_manifest_path
        captured["manifest"] = json.loads(resolved_manifest_path.read_text())
        artifacts = SimpleNamespace(
            workspace=Path("/tmp/workspace"),
            results_path=Path("/tmp/results.json"),
            replay_path=Path("/tmp/replay.json"),
            compressed_replay_path=Path("/tmp/replay.json.z"),
            logs_dir=Path("/tmp/logs"),
        )
        return SimpleNamespace(session=SimpleNamespace(artifacts=artifacts), results={})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("coworld.cli.play_coworld", fake_play_coworld)

    result = CliRunner().invoke(app, ["play", COWORLD_ID, "--no-open-browser"])

    assert result.exit_code == 0, result.output
    assert captured["manifest_path"] == manifest_path.resolve()
    assert captured["manifest"] == manifest


def test_coworld_play_downloads_missing_coworld_id_cache(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    manifest = {"game": {"name": "downloaded-cache"}}
    captured: dict[str, object] = {}
    downloads: list[tuple[str, Path, str, bool]] = []

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
        (output_dir / coworld_ref / "coworld_images.json").write_text("{}", encoding="utf-8")

    def fake_play_coworld(resolved_manifest_path: Path, **_kwargs: object) -> SimpleNamespace:
        captured["manifest_path"] = resolved_manifest_path
        captured["manifest"] = json.loads(resolved_manifest_path.read_text())
        artifacts = SimpleNamespace(
            workspace=Path("/tmp/workspace"),
            results_path=Path("/tmp/results.json"),
            replay_path=Path("/tmp/replay.json"),
            compressed_replay_path=Path("/tmp/replay.json.z"),
            logs_dir=Path("/tmp/logs"),
        )
        return SimpleNamespace(session=SimpleNamespace(artifacts=artifacts), results={})

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("coworld.cli.download_coworld_cmd", fake_download_coworld_cmd)
    monkeypatch.setattr("coworld.cli.play_coworld", fake_play_coworld)

    result = CliRunner().invoke(
        app,
        ["play", COWORLD_ID, "--server", "http://example.test", "--no-open-browser"],
    )

    assert result.exit_code == 0, result.output
    assert downloads == [(COWORLD_ID, Path("./coworld"), "http://example.test", False)]
    assert captured["manifest_path"] == (tmp_path / "coworld" / COWORLD_ID / "coworld_manifest.json").resolve()
    assert captured["manifest"] == manifest


def test_coworld_play_accepts_player_image_override(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_play_coworld(manifest_path: Path, **kwargs: object) -> SimpleNamespace:
        captured["manifest_path"] = manifest_path
        captured["kwargs"] = kwargs
        artifacts = SimpleNamespace(
            workspace=Path("/tmp/workspace"),
            results_path=Path("/tmp/results.json"),
            replay_path=Path("/tmp/replay.json"),
            compressed_replay_path=Path("/tmp/replay.json.z"),
            logs_dir=Path("/tmp/logs"),
        )
        return SimpleNamespace(session=SimpleNamespace(artifacts=artifacts), results={})

    monkeypatch.setattr("coworld.cli.play_coworld", fake_play_coworld)

    result = CliRunner().invoke(
        app,
        [
            "play",
            str(_example_manifest(tmp_path)),
            "my-player:latest",
            "--variant",
            "default",
            "--run",
            "python",
            "--run",
            "/app/player.py",
            "--no-open-browser",
        ],
    )

    assert result.exit_code == 0, result.output
    kwargs = cast(dict[str, object], captured["kwargs"])
    assert kwargs["variant_id"] == "default"
    assert kwargs["player_images"] == ["my-player:latest"]
    assert kwargs["player_run"] == ["python", "/app/player.py"]
    assert kwargs["episode_request_path"] is None


def test_coworld_play_accepts_episode_request_file(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    manifest_path = _example_manifest(tmp_path)
    request_path = _write_episode_request(tmp_path, manifest_path)

    def fake_play_coworld(manifest_path: Path, **kwargs: object) -> SimpleNamespace:
        captured["manifest_path"] = manifest_path
        captured["kwargs"] = kwargs
        artifacts = SimpleNamespace(
            workspace=Path("/tmp/workspace"),
            results_path=Path("/tmp/results.json"),
            replay_path=Path("/tmp/replay.json"),
            compressed_replay_path=Path("/tmp/replay.json.z"),
            logs_dir=Path("/tmp/logs"),
        )
        return SimpleNamespace(session=SimpleNamespace(artifacts=artifacts), results={})

    monkeypatch.setattr("coworld.cli.play_coworld", fake_play_coworld)

    result = CliRunner().invoke(app, ["play", str(manifest_path), str(request_path), "--no-open-browser"])

    assert result.exit_code == 0, result.output
    kwargs = cast(dict[str, object], captured["kwargs"])
    assert kwargs["episode_request_path"] == request_path
    assert kwargs["player_images"] is None


def test_coworld_play_accepts_variant(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_play_coworld(manifest_path: Path, **kwargs: object) -> SimpleNamespace:
        captured["kwargs"] = kwargs
        artifacts = SimpleNamespace(
            workspace=Path("/tmp/workspace"),
            results_path=Path("/tmp/results.json"),
            replay_path=Path("/tmp/replay.json"),
            compressed_replay_path=Path("/tmp/replay.json.z"),
            logs_dir=Path("/tmp/logs"),
        )
        return SimpleNamespace(session=SimpleNamespace(artifacts=artifacts), results={})

    monkeypatch.setattr("coworld.cli.play_coworld", fake_play_coworld)

    result = CliRunner().invoke(
        app, ["play", str(_example_manifest(tmp_path)), "--variant", "daily", "--no-open-browser"]
    )

    assert result.exit_code == 0, result.output
    kwargs = cast(dict[str, object], captured["kwargs"])
    assert kwargs["variant_id"] == "daily"


def test_coworld_play_opens_global_client_by_default(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    opened_urls: list[str] = []

    def fake_play_coworld(manifest_path: Path, **kwargs: object) -> SimpleNamespace:
        artifacts = SimpleNamespace(
            workspace=Path("/tmp/workspace"),
            results_path=Path("/tmp/results.json"),
            replay_path=Path("/tmp/replay.json"),
            compressed_replay_path=Path("/tmp/replay.json.z"),
            logs_dir=Path("/tmp/logs"),
        )
        session = SimpleNamespace(
            artifacts=artifacts,
            variant_id="default",
            links=SimpleNamespace(
                players=["http://127.0.0.1/player"],
                global_="http://127.0.0.1/global",
                admin="http://127.0.0.1/admin",
            ),
        )
        cast(Callable[[object], None], kwargs["on_ready"])(session)
        return SimpleNamespace(session=session, results={})

    monkeypatch.setattr("coworld.cli.play_coworld", fake_play_coworld)
    monkeypatch.setattr("coworld.cli.webbrowser.open", opened_urls.append)

    result = CliRunner().invoke(app, ["play", str(_example_manifest(tmp_path))])

    assert result.exit_code == 0, result.output
    assert opened_urls == ["http://127.0.0.1/global"]
    assert "Variant: default" in result.output
    assert "Player containers: 1 launched" in result.output


def test_coworld_play_accepts_output_dir(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    output_dir = tmp_path / "play-results"

    def fake_play_coworld(_manifest_path: Path, **kwargs: object) -> SimpleNamespace:
        captured["kwargs"] = kwargs
        artifacts = SimpleNamespace(
            workspace=output_dir.resolve(),
            results_path=output_dir.resolve() / "results.json",
            replay_path=output_dir.resolve() / "replay.json",
            compressed_replay_path=output_dir.resolve() / "replay.json.z",
            logs_dir=output_dir.resolve() / "logs",
        )
        return SimpleNamespace(session=SimpleNamespace(artifacts=artifacts), results={})

    monkeypatch.setattr("coworld.cli.play_coworld", fake_play_coworld)

    result = CliRunner().invoke(
        app,
        ["play", str(_example_manifest(tmp_path)), "--output-dir", str(output_dir), "--no-open-browser"],
    )

    assert result.exit_code == 0, result.output
    kwargs = cast(dict[str, object], captured["kwargs"])
    assert kwargs["workspace"] == output_dir.resolve()


def test_run_episode_uses_manifest_certification_players(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    spec, kwargs = _invoke_run_episode(
        monkeypatch,
        tmp_path,
        str(_example_manifest(tmp_path)),
        "--timeout-seconds",
        "12",
        "--verify-replay",
    )

    assert [player.image for player in spec.players] == ["coworld-paintarena:latest", "coworld-paintarena:latest"]
    expected_run = ["python", "-m", "coworld.examples.paintarena.player.player"]
    assert [player.run for player in spec.players] == [expected_run, expected_run]
    assert spec.game_config["max_ticks"] == 100
    assert kwargs == {"timeout_seconds": 12.0, "verify_replay": True, "container_prefix": "coworld-run"}


def test_run_episode_defaults_results_next_to_manifest(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    manifest_path = _example_manifest(tmp_path)

    artifacts = _invoke_run_episode_artifacts(monkeypatch, str(manifest_path))

    assert artifacts.workspace == (manifest_path.parent / "results").resolve()
    assert artifacts.results_path == (manifest_path.parent / "results" / "results.json").resolve()


def test_run_episode_defaults_backend_coworld_results_to_coworld_id(
    httpserver: HTTPServer,
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = json.loads(_example_manifest(tmp_path).read_text(encoding="utf-8"))
    httpserver.expect_request(COWORLD_PATH).respond_with_json({"manifest": manifest})

    monkeypatch.chdir(tmp_path)
    artifacts = _invoke_run_episode_artifacts(monkeypatch, COWORLD_PATH, "--server", httpserver.url_for(""))

    assert artifacts.workspace == (tmp_path / "coworld" / COWORLD_ID / "results").resolve()


def test_run_episode_defaults_coworld_id_results_to_coworld_id(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    manifest_path = tmp_path / "coworld" / COWORLD_ID / "coworld_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(_example_manifest(tmp_path).read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    artifacts = _invoke_run_episode_artifacts(monkeypatch, COWORLD_ID)

    assert artifacts.workspace == (tmp_path / "coworld" / COWORLD_ID / "results").resolve()


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
        (output_dir / coworld_ref / "coworld_images.json").write_text("{}", encoding="utf-8")

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


def test_run_episode_defaults_downloaded_id_manifest_results_to_coworld_id(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "coworld" / COWORLD_ID / "coworld_manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(_example_manifest(tmp_path).read_text(encoding="utf-8"), encoding="utf-8")

    artifacts = _invoke_run_episode_artifacts(monkeypatch, str(manifest_path))

    assert artifacts.workspace == (tmp_path / "coworld" / COWORLD_ID / "results").resolve()


def test_run_episode_accepts_one_player_image_for_all_slots(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    spec, kwargs = _invoke_run_episode(
        monkeypatch,
        tmp_path,
        str(_example_manifest(tmp_path)),
        "my-player:latest",
        "--run",
        "python",
        "--run",
        "/app/player.py",
    )

    assert [player.image for player in spec.players] == ["my-player:latest", "my-player:latest"]
    assert [player.run for player in spec.players] == [["python", "/app/player.py"]] * 2
    assert kwargs == {"timeout_seconds": 3600.0, "verify_replay": False, "container_prefix": "coworld-run"}


def test_run_episode_accepts_one_player_image_per_slot(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    spec, _kwargs = _invoke_run_episode(
        monkeypatch,
        tmp_path,
        str(_example_manifest(tmp_path)),
        "player-one:latest",
        "player-two:latest",
    )

    assert [player.image for player in spec.players] == ["player-one:latest", "player-two:latest"]
    expected_run = ["python", "-m", "coworld.examples.paintarena.player.player"]
    assert [player.run for player in spec.players] == [expected_run, expected_run]


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

    spec, kwargs = _invoke_run_episode(monkeypatch, tmp_path, str(manifest_path), str(request_path))

    assert spec.game_config["max_ticks"] == 3
    assert [player.image for player in spec.players] == ["slot-zero:latest", "slot-one:latest"]
    assert [player.run for player in spec.players] == [["python", "/slot-zero.py"], ["python", "/slot-one.py"]]
    assert [player.env for player in spec.players] == [{"PLAYER_SLOT": "0"}, {"PLAYER_SLOT": "1"}]
    assert spec.policy_names == ["slot-zero:v1", "slot-one:v1"]
    assert kwargs == {"timeout_seconds": 3600.0, "verify_replay": False, "container_prefix": "coworld-run"}


def _invoke_run_episode_artifacts(monkeypatch: MonkeyPatch, *args: str) -> EpisodeArtifacts:
    captured: dict[str, object] = {}

    def fake_run_coworld_episode(_spec: CoworldEpisodeJobSpec, artifacts: object, **_kwargs: object) -> None:
        captured["artifacts"] = artifacts

    monkeypatch.setattr("coworld.cli.run_coworld_episode", fake_run_coworld_episode)
    result = CliRunner().invoke(app, ["run-episode", *args])

    assert result.exit_code == 0, result.output
    return cast(EpisodeArtifacts, captured["artifacts"])


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


def _cogs_vs_clips_manifest(tmp_path: Path) -> Path:
    return _materialized_template(
        tmp_path,
        Path(__file__).resolve().parents[3] / "worlds" / "cogs_vs_clips" / "coworld_manifest_template.json",
    )


def _materialized_template(tmp_path: Path, template_path: Path) -> Path:
    manifest = json.loads(template_path.read_text(encoding="utf-8"))
    manifest["game"]["version"] = "0.1.0"
    image_placeholders = {
        "cogs_vs_clips": {
            "{{GAME_IMAGE}}": "coworld-cogs-vs-clips-game:latest",
            "{{PLAYER_IMAGE}}": "coworld-cogs-vs-clips-reference-player:latest",
        },
        "paintarena": {"{{PAINTARENA_IMAGE}}": "coworld-paintarena:latest"},
    }
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
                    "players": [{"name": "Slot Zero"}, {"name": "Slot One"}],
                },
                "players": [
                    {
                        "image": "slot-zero:latest",
                        "run": ["python", "/slot-zero.py"],
                        "env": {"PLAYER_SLOT": "0"},
                    },
                    {
                        "image": "slot-one:latest",
                        "run": ["python", "/slot-one.py"],
                        "env": {"PLAYER_SLOT": "1"},
                    },
                ],
                "policy_names": ["slot-zero:v1", "slot-one:v1"],
            }
        ),
        encoding="utf-8",
    )
    return request_path
