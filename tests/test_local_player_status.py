import json
import subprocess
from pathlib import Path

from coworld.runner.io import PlayerRuntimeStatuses
from coworld.runner.local_player_status import collect_local_player_status


def test_capture_keeps_faults_running_and_missing_seats_distinct(monkeypatch, tmp_path: Path) -> None:
    states = [("exited", False, 0, False), ("exited", False, 137, True), ("running", True, 0, False)]

    def inspect(command, **kwargs):
        slot = int(command[-1].split("-")[-1])
        if slot == 3:
            return subprocess.CompletedProcess(command, 1, "", "container gone")
        state, running, code, oom = states[slot]
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                [
                    {
                        "Id": f"container-{slot}",
                        "Image": "sha256:actual-image",
                        "Config": {"Env": ["SECRET=must-not-be-exported"]},
                        "State": {
                            "Status": state,
                            "Running": running,
                            "ExitCode": code,
                            "OOMKilled": oom,
                            "Error": "",
                            "FinishedAt": "2026-10-03T20:00:00Z",
                        },
                    }
                ]
            ),
        )

    monkeypatch.setattr("coworld.runner.local_player_status.subprocess.run", inspect)
    collect_local_player_status([f"player-{i}" for i in range(4)], 5, tmp_path)
    statuses = PlayerRuntimeStatuses.model_validate_json((tmp_path / "player_status.json").read_text()).players
    assert [(s.state, s.exit_code) for s in statuses] == [
        ("exited", 0),
        ("exited", 137),
        ("running", None),
        ("unavailable", None),
        ("not_started", None),
    ]
    assert statuses[1].reason == "OOMKilled"
    assert statuses[2].reason == "runner_cleanup_pending"
    receipt = (tmp_path / "player_containers.json").read_text()
    assert "must-not-be-exported" not in receipt
    assert json.loads(receipt)["players"][1]["inspection"]["container_id"] == "container-1"
    assert (tmp_path / "player_status.json").stat().st_mode & 0o777 == 0o600
