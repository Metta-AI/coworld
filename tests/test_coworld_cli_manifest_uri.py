import json
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, cast

from pytest import MonkeyPatch
from pytest_httpserver import HTTPServer
from typer.testing import CliRunner

from coworld.cli import app
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
            logs_dir=Path("/tmp/logs"),
        )
        return SimpleNamespace(session=SimpleNamespace(artifacts=artifacts), results={})

    monkeypatch.setattr("coworld.cli.play_coworld", fake_play_coworld)

    result = CliRunner().invoke(app, ["play", COWORLD_PATH, "--server", httpserver.url_for("")])

    assert result.exit_code == 0, result.output
    assert captured["manifest"] == manifest


def test_coworld_play_accepts_player_image_override(monkeypatch: MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_play_coworld(manifest_path: Path, **kwargs: object) -> SimpleNamespace:
        captured["manifest_path"] = manifest_path
        captured["kwargs"] = kwargs
        artifacts = SimpleNamespace(
            workspace=Path("/tmp/workspace"),
            results_path=Path("/tmp/results.json"),
            replay_path=Path("/tmp/replay.json"),
            logs_dir=Path("/tmp/logs"),
        )
        return SimpleNamespace(session=SimpleNamespace(artifacts=artifacts), results={})

    monkeypatch.setattr("coworld.cli.play_coworld", fake_play_coworld)

    result = CliRunner().invoke(
        app,
        [
            "play",
            str(_example_manifest()),
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


def test_coworld_play_accepts_variant(monkeypatch: MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_play_coworld(manifest_path: Path, **kwargs: object) -> SimpleNamespace:
        captured["kwargs"] = kwargs
        artifacts = SimpleNamespace(
            workspace=Path("/tmp/workspace"),
            results_path=Path("/tmp/results.json"),
            replay_path=Path("/tmp/replay.json"),
            logs_dir=Path("/tmp/logs"),
        )
        return SimpleNamespace(session=SimpleNamespace(artifacts=artifacts), results={})

    monkeypatch.setattr("coworld.cli.play_coworld", fake_play_coworld)

    result = CliRunner().invoke(app, ["play", str(_example_manifest()), "--variant", "daily", "--no-open-browser"])

    assert result.exit_code == 0, result.output
    kwargs = cast(dict[str, object], captured["kwargs"])
    assert kwargs["variant_id"] == "daily"


def test_coworld_play_opens_global_client_by_default(monkeypatch: MonkeyPatch) -> None:
    opened_urls: list[str] = []

    def fake_play_coworld(manifest_path: Path, **kwargs: object) -> SimpleNamespace:
        artifacts = SimpleNamespace(
            workspace=Path("/tmp/workspace"),
            results_path=Path("/tmp/results.json"),
            replay_path=Path("/tmp/replay.json"),
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

    result = CliRunner().invoke(app, ["play", str(_example_manifest())])

    assert result.exit_code == 0, result.output
    assert opened_urls == ["http://127.0.0.1/global"]
    assert "Variant: default" in result.output
    assert "Player containers: 1 launched" in result.output


def test_run_episode_uses_manifest_certification_players(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    spec, kwargs = _invoke_run_episode(
        monkeypatch,
        tmp_path,
        str(_example_manifest()),
        "--timeout-seconds",
        "12",
        "--verify-replay",
    )

    assert [player.image for player in spec.players] == ["coworld-paintarena:latest", "coworld-paintarena:latest"]
    assert [player.run for player in spec.players] == [["python", "/app/player/player.py"]] * 2
    assert spec.game_config["max_ticks"] == 100
    assert kwargs == {"timeout_seconds": 12.0, "verify_replay": True}


def test_run_episode_accepts_one_player_image_for_all_slots(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    spec, kwargs = _invoke_run_episode(
        monkeypatch,
        tmp_path,
        str(_example_manifest()),
        "my-player:latest",
        "--run",
        "python",
        "--run",
        "/app/player.py",
    )

    assert [player.image for player in spec.players] == ["my-player:latest", "my-player:latest"]
    assert [player.run for player in spec.players] == [["python", "/app/player.py"]] * 2
    assert kwargs == {"timeout_seconds": 3600.0, "verify_replay": False}


def test_run_episode_accepts_one_player_image_per_slot(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    spec, _kwargs = _invoke_run_episode(
        monkeypatch,
        tmp_path,
        str(_example_manifest()),
        "player-one:latest",
        "player-two:latest",
    )

    assert [player.image for player in spec.players] == ["player-one:latest", "player-two:latest"]
    assert [player.run for player in spec.players] == [[], []]


def test_run_episode_player_image_override_keeps_manifest_env(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    spec, _kwargs = _invoke_run_episode(
        monkeypatch,
        tmp_path,
        str(_cogs_vs_clips_manifest()),
        "custom-policy-player:latest",
        "--run",
        "python",
        "--run",
        "/app/player.py",
    )

    assert [player.image for player in spec.players] == ["custom-policy-player:latest"] * 8
    assert [player.run for player in spec.players] == [["python", "/app/player.py"]] * 8
    assert {tuple(player.env.items()) for player in spec.players} == {
        (("COGAMES_POLICY_URI", "metta://policy/cogames.policy.starter_agent.StarterPolicy"),)
    }


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


def _example_manifest() -> Path:
    return Path(__file__).resolve().parents[1] / "src" / "coworld" / "examples" / "paintarena" / "coworld_manifest.json"


def _cogs_vs_clips_manifest() -> Path:
    return (
        Path(__file__).resolve().parents[1] / "src" / "coworld" / "examples" / "cogs_vs_clips" / "coworld_manifest.json"
    )
