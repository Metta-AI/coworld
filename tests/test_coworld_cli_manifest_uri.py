import json
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, cast
from urllib.parse import urlparse
from urllib.request import url2pathname

from pytest import MonkeyPatch
from pytest_httpserver import HTTPServer
from typer.testing import CliRunner

from coworld.certifier import load_executable_transcript
from coworld.cli import app
from coworld.runner.runner import EpisodeArtifacts
from coworld.types import CoworldEpisodeJobSpec, StepResult

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


def test_coworld_replay_opens_replay_client_by_default(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    opened_urls: list[str] = []
    replay_link = "http://127.0.0.1:4321/client/replay"
    manifest_path = tmp_path / "coworld_manifest.json"
    replay_path = tmp_path / "replay.json"
    manifest_path.write_text('{"game": {"name": "unit"}}\n', encoding="utf-8")
    replay_path.write_text('{"events":[]}\n', encoding="utf-8")

    def fake_replay_coworld(
        _manifest_path: Path,
        _replay_path: Path,
        **kwargs: object,
    ) -> SimpleNamespace:
        session = SimpleNamespace(
            artifacts=SimpleNamespace(workspace=Path("/tmp/workspace"), logs_dir=Path("/tmp/logs")),
            replay_path=replay_path,
            link=replay_link,
        )
        cast(Callable[[object], None], kwargs["on_ready"])(session)
        return session

    monkeypatch.setattr("coworld.cli.replay_coworld", fake_replay_coworld)
    monkeypatch.setattr("coworld.cli.webbrowser.open", opened_urls.append)

    result = CliRunner().invoke(app, ["replay", str(manifest_path), str(replay_path)])

    assert result.exit_code == 0, result.output
    assert opened_urls == [replay_link]
    assert f"Replay client: {replay_link}" in result.output


def test_coworld_replay_respects_no_open_browser(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    opened_urls: list[str] = []
    manifest_path = tmp_path / "coworld_manifest.json"
    replay_path = tmp_path / "replay.json"
    manifest_path.write_text('{"game": {"name": "unit"}}\n', encoding="utf-8")
    replay_path.write_text('{"events":[]}\n', encoding="utf-8")

    def fake_replay_coworld(
        _manifest_path: Path,
        _replay_path: Path,
        **kwargs: object,
    ) -> SimpleNamespace:
        session = SimpleNamespace(
            artifacts=SimpleNamespace(workspace=Path("/tmp/workspace"), logs_dir=Path("/tmp/logs")),
            replay_path=replay_path,
            link="http://127.0.0.1:4321/client/replay",
        )
        cast(Callable[[object], None], kwargs["on_ready"])(session)
        return session

    monkeypatch.setattr("coworld.cli.replay_coworld", fake_replay_coworld)
    monkeypatch.setattr("coworld.cli.webbrowser.open", opened_urls.append)

    result = CliRunner().invoke(app, ["replay", str(manifest_path), str(replay_path), "--no-open-browser"])

    assert result.exit_code == 0, result.output
    assert opened_urls == []


def test_coworld_certify_prints_replay_liveness_and_inspection_command(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    opened_urls: list[str] = []
    manifest_path = tmp_path / "coworld_manifest.json"
    manifest_path.write_text('{"game": {"name": "unit"}}\n', encoding="utf-8")
    workspace = tmp_path / "workspace"
    artifacts = SimpleNamespace(
        workspace=workspace,
        results_path=workspace / "results.json",
        replay_path=workspace / "replay.json",
        logs_dir=workspace / "logs",
    )
    transcript = load_executable_transcript()
    step_results = [StepResult(id=step.id, kind=step.kind, status="pass") for step in transcript.steps]

    def fake_certify_coworld(_manifest_path: Path, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            transcript=transcript,
            step_results=step_results,
            artifacts=artifacts,
            reporter_references=[],
        )

    monkeypatch.setattr("coworld.cli.certify_coworld", fake_certify_coworld)
    monkeypatch.setattr("coworld.cli.webbrowser.open", opened_urls.append)

    result = CliRunner().invoke(app, ["certify", str(manifest_path)])
    report_path = workspace / "certification_report.html"

    assert result.exit_code == 0, result.output
    assert "Replay liveness: verified /client/replay and /replay" in result.output
    assert f"Inspect replay: uv run coworld replay {manifest_path} {workspace / 'replay.json'}" in result.output
    assert f"Inspect logs: ls {workspace / 'logs'}" in result.output
    assert f"Transcript report: {report_path.as_uri()}" in result.output
    assert opened_urls == [report_path.as_uri()]
    html = report_path.read_text(encoding="utf-8")
    assert "Coworld certification" in html
    assert "Passed" in html
    assert "matriculate" in html
    assert "<details" in html


def test_coworld_certify_failure_writes_report_and_suppresses_traceback(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    opened_urls: list[str] = []
    manifest_path = tmp_path / "coworld_manifest.json"
    manifest_path.write_text('{"game": {"name": "unit"}}\n', encoding="utf-8")
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
    assert "Certification failed" in result.output
    assert "Failed step: images-reachable" in result.output
    assert "Failure reason: image_unreachable" in result.output
    assert "missing image ghcr.io/example/missing:latest" in result.output
    assert "check registry credentials" in result.output
    assert "Traceback" not in result.output
    assert len(opened_urls) == 1
    report_path = Path(url2pathname(urlparse(opened_urls[0]).path))
    html = report_path.read_text(encoding="utf-8")
    assert "Failed" in html
    assert "image_unreachable" in html
    assert "missing image ghcr.io/example/missing:latest" in html
    assert "check registry credentials" in html
    assert html.count('class="detail-line"') >= 2
    assert "not run" in html


def test_coworld_certify_error_without_failed_step_marks_report_failed(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    opened_urls: list[str] = []
    manifest_path = tmp_path / "coworld_manifest.json"
    manifest_path.write_text('{"game": {"name": "unit"}}\n', encoding="utf-8")
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
    assert "Details: runner crashed before verdict" in result.output
    assert len(opened_urls) == 1
    report_path = Path(url2pathname(urlparse(opened_urls[0]).path))
    html = report_path.read_text(encoding="utf-8")
    assert "<title>Coworld certification failed</title>" in html
    assert "<h1>Failed</h1>" in html
    assert "Certification stopped" in html
    assert "runner crashed before verdict" in html


def test_coworld_certify_schema_failure_prints_actionable_detail(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    manifest_path = tmp_path / "coworld_manifest.json"
    manifest_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["certify", str(manifest_path), "--no-open-report"])

    assert result.exit_code == 1, result.output
    assert "Failed step: matriculate" in result.output
    assert "Failure reason: manifest_invalid" in result.output
    assert "Details: $: 'game' is a required property" in result.output
    assert "Failed validating" not in result.output
    assert "Traceback" not in result.output


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


def test_coworld_certify_downloads_missing_coworld_id_cache(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
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

    def fake_certify_coworld(resolved_manifest_path: Path, **_kwargs: object) -> SimpleNamespace:
        captured["manifest_path"] = resolved_manifest_path
        captured["manifest"] = json.loads(resolved_manifest_path.read_text())
        workspace = tmp_path / "certify-workspace"
        artifacts = SimpleNamespace(
            workspace=workspace,
            results_path=workspace / "results.json",
            replay_path=workspace / "replay.json",
            logs_dir=workspace / "logs",
        )
        transcript = load_executable_transcript()
        return SimpleNamespace(
            transcript=transcript,
            step_results=[StepResult(id=step.id, kind=step.kind, status="pass") for step in transcript.steps],
            artifacts=artifacts,
            reporter_references=[],
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("coworld.cli.download_coworld_cmd", fake_download_coworld_cmd)
    monkeypatch.setattr("coworld.cli.certify_coworld", fake_certify_coworld)

    result = CliRunner().invoke(
        app,
        ["certify", COWORLD_ID, "--server", "http://example.test", "--no-open-report"],
    )

    assert result.exit_code == 0, result.output
    assert downloads == [(COWORLD_ID, Path("./coworld"), "http://example.test", False)]
    assert captured["manifest_path"] == (tmp_path / "coworld" / COWORLD_ID / "coworld_manifest.json").resolve()
    assert captured["manifest"] == manifest
    assert "Transcript: coworld-executable (10 steps passed)" in result.output
    assert "Degree:" not in result.output
    assert "Certificate:" not in result.output
    assert "Degree file:" not in result.output


def test_coworld_play_accepts_player_image_override(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
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
            str(_example_manifest(tmp_path)),
            "my-player:latest",
            "--variant",
            "default",
            "--run",
            "python",
            "--run",
            "/app/player.py",
            "--player-exit-timeout-seconds",
            "45",
            "--no-open-browser",
        ],
    )

    assert result.exit_code == 0, result.output
    kwargs = cast(dict[str, object], captured["kwargs"])
    assert kwargs["variant_id"] == "default"
    assert kwargs["player_images"] == ["my-player:latest"]
    assert kwargs["player_run"] == ["python", "/app/player.py"]
    assert kwargs["player_exit_timeout_seconds"] == 45.0
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
    manifest_path = _example_manifest(tmp_path)

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

    result = CliRunner().invoke(app, ["play", str(manifest_path)])

    assert result.exit_code == 0, result.output
    assert opened_urls == ["http://127.0.0.1/global"]
    assert "Variant: default" in result.output
    assert "Player containers: 1 launched" in result.output
    assert f"Inspect replay: uv run coworld replay {manifest_path} /tmp/replay.json" in result.output
    assert "Inspect logs: ls /tmp/logs" in result.output


def test_coworld_play_accepts_output_dir(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    output_dir = tmp_path / "play-results"

    def fake_play_coworld(_manifest_path: Path, **kwargs: object) -> SimpleNamespace:
        captured["kwargs"] = kwargs
        artifacts = SimpleNamespace(
            workspace=output_dir.resolve(),
            results_path=output_dir.resolve() / "results.json",
            replay_path=output_dir.resolve() / "replay",
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


def test_run_episode_prints_fast_feedback_commands(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    output_dir = tmp_path / "episode"

    def fake_run_coworld_episode(_spec: CoworldEpisodeJobSpec, artifacts: object, **_kwargs: object) -> None:
        cast(EpisodeArtifacts, artifacts).results_path.write_text('{"scores":[3,1.5]}', encoding="utf-8")

    monkeypatch.setattr("coworld.cli.run_coworld_episode", fake_run_coworld_episode)
    manifest_path = _example_manifest(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "run-episode",
            str(manifest_path),
            "--output-dir",
            str(output_dir),
            "--server",
            "https://staging.example/api",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Scores: 0=3, 1=1.5" in result.output
    assert (
        f"Inspect replay: uv run coworld replay {manifest_path} {output_dir.resolve() / 'replay'} "
        "--server https://staging.example/api" in result.output
    )
    assert f"Inspect logs: ls {output_dir.resolve() / 'logs'}" in result.output


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


def test_run_episode_accepts_variant_with_player_override(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec, _kwargs = _invoke_run_episode(
        monkeypatch,
        tmp_path,
        str(_cogs_vs_clips_manifest(tmp_path)),
        "custom-policy-player:latest",
        "--variant",
        "machina-1-daily",
    )

    assert spec.game_config["mission"] == "machina_1"
    assert spec.game_config["max_steps"] == 10000
    assert [player.image for player in spec.players] == ["custom-policy-player:latest"] * 8


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
    assert spec.game_config["players"] == [{"name": "slot-zero:v1"}, {"name": "slot-one:v1"}]
    assert kwargs == {"timeout_seconds": 3600.0, "verify_replay": False, "container_prefix": "coworld-run"}


def test_run_episode_rejects_episode_request_file_with_variant(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    manifest_path = _example_manifest(tmp_path)
    request_path = _write_episode_request(tmp_path, manifest_path)

    result = CliRunner().invoke(app, ["run-episode", str(manifest_path), str(request_path), "--variant", "default"])

    assert result.exit_code != 0
    assert "episode request files cannot be combined" in result.output
    assert "--variant" in result.output
    assert "--run" in result.output


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
    expected_kwargs = {"timeout_seconds": 3600.0, "verify_replay": False, "container_prefix": "coworld-run"}
    assert [kwargs for _spec, _artifacts, kwargs in captured] == [expected_kwargs, expected_kwargs]
    assert [player.image for player in captured[0][0].players] == ["my-player:latest"] * 8
    assert [player.run for player in captured[0][0].players] == [["python", "/app/player.py"]] * 8
    assert "Episode 2/2" in result.output
    assert f"Artifacts root: {artifacts_root}" in result.output


def test_scrimmage_runs_one_episode_for_target_player_container(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: list[tuple[CoworldEpisodeJobSpec, EpisodeArtifacts, dict[str, object]]] = []

    def fake_run_coworld_episode(spec: CoworldEpisodeJobSpec, artifacts: object, **kwargs: object) -> None:
        captured.append((spec, cast(EpisodeArtifacts, artifacts), kwargs))

    monkeypatch.setattr("coworld.cli.run_coworld_episode", fake_run_coworld_episode)
    manifest_path = _cogs_vs_clips_manifest(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "scrimmage",
            str(manifest_path),
            "target-policy:latest",
            "--run",
            "python",
            "--run",
            "/app/player.py",
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(captured) == 1
    spec, artifacts, kwargs = captured[0]
    assert spec.game_config["seed"] == 0
    assert artifacts.workspace == (manifest_path.parent / "results").resolve()
    assert kwargs == {"timeout_seconds": 3600.0, "verify_replay": False, "container_prefix": "coworld-run"}
    assert [player.image for player in spec.players] == ["target-policy:latest"] * 8
    assert [player.run for player in spec.players] == [["python", "/app/player.py"]] * 8


def test_scrimmage_accepts_variant_for_target_player_container(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: list[tuple[CoworldEpisodeJobSpec, EpisodeArtifacts, dict[str, object]]] = []

    def fake_run_coworld_episode(spec: CoworldEpisodeJobSpec, artifacts: object, **kwargs: object) -> None:
        captured.append((spec, cast(EpisodeArtifacts, artifacts), kwargs))

    monkeypatch.setattr("coworld.cli.run_coworld_episode", fake_run_coworld_episode)
    manifest_path = _cogs_vs_clips_manifest(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "scrimmage",
            str(manifest_path),
            "target-policy:latest",
            "--variant",
            "machina-1-daily",
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(captured) == 1
    spec, _artifacts, _kwargs = captured[0]
    assert spec.game_config["mission"] == "machina_1"
    assert [player.image for player in spec.players] == ["target-policy:latest"] * 8


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
