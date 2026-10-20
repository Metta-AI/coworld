import asyncio
import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from websockets.asyncio.client import connect

from coworld.report import assert_safe_render_html
from coworld.stats import MeasuredValue, MissingValue, NoOpportunities, StatsBlock


async def _run_episode(directory: Path, ticks: int, environment: dict[str, str]) -> tuple[Path, dict]:
    directory.mkdir()
    config = directory / "config.json"
    replay = directory / "replay.json"
    results = directory / "results.json"
    config.write_text(
        json.dumps(
            {
                "width": 16,
                "height": 2,
                "max_ticks": ticks,
                "tick_rate": 40,
                "player_connect_timeout_seconds": 15,
                "tokens": ["right-token", "stay-token"],
                "players": [{"name": "scripted-right"}, {"name": "scripted-stay"}],
            }
        )
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = {
        **environment,
        "COGAME_HOST": "127.0.0.1",
        "COGAME_PORT": str(port),
        "COGAME_CONFIG_URI": str(config),
        "COGAME_RESULTS_URI": str(results),
        "COGAME_SAVE_REPLAY_URI": str(replay),
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "coworld.examples.paintarena.game.server",
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    log = bytearray()
    assert process.stdout is not None
    try:
        async with asyncio.timeout(15):
            while b"Uvicorn running on" not in log:
                line = await process.stdout.readline()
                log.extend(line)
                assert line, log.decode()

            async def play(slot: int, direction: str) -> None:
                uri = f"ws://127.0.0.1:{port}/player?slot={slot}&token={direction}-token"
                async with connect(uri) as websocket:
                    observation = json.loads(await websocket.recv())
                    assert observation["slot"] == slot
                    await websocket.send(json.dumps({"move": direction}))
                    while json.loads(await websocket.recv())["type"] != "final":
                        pass

            await asyncio.gather(play(0, "right"), play(1, "stay"))
            tail, _ = await process.communicate()
            log.extend(tail)
            assert process.returncode == 0, log.decode()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
        (directory / "server.log").write_bytes(log)
    return replay, json.loads(results.read_text())


@pytest.mark.asyncio
async def test_native_paintarena_stats_batch_and_resume(tmp_path: Path) -> None:
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(str(Path(path).resolve()) for path in sys.path)}
    replay, results = await _run_episode(tmp_path / "eight-ticks", 8, environment)
    short_replay, short_results = await _run_episode(tmp_path / "one-tick", 1, environment)
    assert results["scores"] == [8.0, 1.0]
    assert short_results["scores"] == [1.0, 1.0]
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("not a replay")
    receipts = []
    for episode_id, path in (
        ("scripted-eight-ticks<script>", replay),
        ("scripted-one-tick", short_replay),
        ("corrupt-replay", corrupt),
        ("missing-replay", tmp_path / "missing.json"),
    ):
        receipts.append(
            {
                "path": str(path.relative_to(tmp_path)),
                "episode_id": episode_id,
                "game_id": "paintarena-test-fixture",
                "game_build_id": None,
                "replay_sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "f" * 64,
                "policies": [
                    {"id": f"scripted-{direction}", "sha256": hashlib.sha256(direction.encode()).hexdigest()}
                    for direction in ("right", "stay")
                ],
                "context": {"evaluation_protocol": "native-websocket-system-test-v1"},
            }
        )
    manifest = tmp_path / "inputs.json"
    invalid_output = tmp_path / "invalid-receipts"
    manifest.write_text(json.dumps([receipts[0], {**receipts[1], "episode_id": "replay-sha256:" + "0" * 64}]))
    invalid_receipt = subprocess.run(
        [
            sys.executable,
            "-m",
            "coworld",
            "stats",
            "extract-paintarena",
            str(manifest),
            str(invalid_output),
            "--no-open",
        ],
        capture_output=True,
        text=True,
        env=environment,
        timeout=20,
    )
    assert invalid_receipt.returncode != 0
    assert "Replay-derived episode ID must match" in invalid_receipt.stderr
    assert not invalid_output.exists()
    manifest.write_text(json.dumps(receipts))
    for collision in ("manifest", "report", "episode", "batch", "hardlink"):
        collision_output = tmp_path / f"collision-{collision}"
        collision_output.mkdir()
        collision_manifest = collision_output / ("stats.json" if collision == "manifest" else "inputs.json")
        collision_receipt = {**receipts[0], "path": str(replay)}
        if collision == "report":
            (collision_output / "report.html").symlink_to(replay)
        elif collision == "hardlink":
            (collision_output / "report.html").hardlink_to(replay)
        elif collision in ("episode", "batch"):
            name = hashlib.sha256(str(collision_receipt["episode_id"]).encode()).hexdigest() + ".tmp"
            collision_replay = collision_output / ("episodes" if collision == "episode" else "batches") / name
            collision_replay.parent.mkdir()
            collision_replay.write_bytes(replay.read_bytes())
            collision_receipt["path"] = str(collision_replay)
        collision_manifest.write_text(json.dumps([collision_receipt]))
        paths_before = set(collision_output.rglob("*"))
        bytes_before = {
            path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths_before | {replay} if path.is_file()
        }
        rejected = subprocess.run(
            [
                sys.executable,
                "-m",
                "coworld",
                "stats",
                "extract-paintarena",
                str(collision_manifest),
                str(collision_output),
                "--no-open",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            env=environment,
        )
        assert rejected.returncode == 2, rejected.stdout + rejected.stderr
        assert "overlap reserved output paths" in rejected.stderr
        assert set(collision_output.rglob("*")) == paths_before
        assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in bytes_before} == bytes_before
    output = tmp_path / "output"
    command = [
        sys.executable,
        "-m",
        "coworld",
        "stats",
        "extract-paintarena",
        str(manifest),
        str(output),
        "--workers",
        "2",
        "--no-open",
    ]
    extracted = subprocess.run(command, capture_output=True, text=True, timeout=20, env=environment)
    assert extracted.returncode == 1, extracted.stdout + extracted.stderr
    assert "2 extracted, 2 failed" in extracted.stdout
    block = StatsBlock.model_validate_json((output / "stats.json").read_bytes())
    assert [failure.provenance.episode_id for failure in block.failures] == ["corrupt-replay", "missing-replay"]
    assert "json_invalid" in block.failures[0].reason
    assert "FileNotFoundError" in block.failures[1].reason
    for episode, native_results, receipt in zip(block.episodes, (results, short_results), receipts[:2], strict=True):
        assert episode.provenance.replay_sha256 == receipt["replay_sha256"]
        for index, seat in enumerate(episode.seats):
            values = {measurement.metric_id: measurement for measurement in seat.measurements}
            outcome = values["paintarena.territory.final_tiles"]
            assert isinstance(outcome, MeasuredValue)
            assert outcome.value == outcome.count == native_results["painted_tiles"][index]
            missing = values["paintarena.movement.submitted_commands"]
            unsupported = values["paintarena.economy.purchase_fraction"]
            assert isinstance(missing, MissingValue) and missing.status == "missing"
            assert isinstance(unsupported, MissingValue) and unsupported.status == "unsupported"
            movement = values["paintarena.movement.active_fraction"]
            if native_results["ticks"] == 1:
                assert isinstance(movement, NoOpportunities)
                assert movement.count == movement.denominator == 0
            else:
                assert isinstance(movement, MeasuredValue)
                assert movement.denominator == 7
                assert movement.count == (7 if index == 0 else 0)
                assert movement.value == (1 if index == 0 else 0)
    html = (output / "report.html").read_text()
    assert_safe_render_html(html)
    assert "scripted-eight-ticks&lt;script&gt;" in html
    assert "<script>" not in html
    schema_command = subprocess.run(
        [sys.executable, "-m", "coworld", "stats", "schema"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
        env=environment,
    )
    schema = json.loads(schema_command.stdout)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(block.model_dump(mode="json"))
    unversioned = block.model_dump(mode="json", exclude={"schema_version"})
    assert not Draft202012Validator(schema).is_valid(unversioned)
    unversioned_path = tmp_path / "unversioned-stats.json"
    unversioned_path.write_text(json.dumps(unversioned))
    invalid_version = subprocess.run(
        [sys.executable, "-m", "coworld", "stats", "validate", str(unversioned_path)],
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )
    assert invalid_version.returncode != 0
    assert "schema_version" in invalid_version.stderr
    checked_in_schema = Path(__file__).parents[1] / "src/coworld/coworld_stats_schema.json"
    assert schema == json.loads(checked_in_schema.read_text())
    validated = subprocess.run(
        [sys.executable, "-m", "coworld", "stats", "validate", str(output / "stats.json")],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
        env=environment,
    )
    assert "2 episodes, 2 failures" in validated.stdout
    saved = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (output / "episodes").glob("*.json")}
    assert len(saved) == 2
    repeated = subprocess.run(command, capture_output=True, text=True, timeout=20, env=environment)
    assert repeated.returncode == 1, repeated.stdout + repeated.stderr
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in saved} == saved
    assert StatsBlock.model_validate_json((output / "stats.json").read_bytes()) == block
    batch_bytes = (output / "stats.json").read_bytes()
    snapshot = output / "batches" / f"{hashlib.sha256(batch_bytes).hexdigest()}.json"
    assert snapshot.read_bytes() == batch_bytes
    assert len(list((output / "batches").glob("*.json"))) == 1
    manifest.write_text(json.dumps(receipts[:2]))
    recovered = subprocess.run(command, capture_output=True, text=True, timeout=20, env=environment)
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    latest = StatsBlock.model_validate_json((output / "stats.json").read_bytes())
    assert latest.episodes == block.episodes and latest.failures == []
    assert snapshot.read_bytes() == batch_bytes
    assert len(list((output / "batches").glob("*.json"))) == 2
    assert {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in saved} == saved
