"""Build and run a contributor's endpoint-backed player through a real local hosted stack.

Requires METTA_PARLEY_SYSTEM_SERVER, METTA_PARLEY_SYSTEM_COWORLD,
METTA_PARLEY_SYSTEM_GAME_IMAGE, METTA_PARLEY_SYSTEM_ENDPOINT, and
METTA_PARLEY_SYSTEM_MODEL. METTA_PARLEY_SYSTEM_API_KEY_ENV optionally names the
provider credential variable. Authenticate with a local USER credential in
SOFTMAX_CONFIG_DIR. The endpoint must serve complete legal Parley actions.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import pytest

from coworld.api_client import CoworldApiClient
from coworld.examples.parley.evidence import read_capture_archive


def test_parley_custom_endpoint_preserves_seeded_inference(tmp_path: Path) -> None:
    if "METTA_PARLEY_SYSTEM_SERVER" not in os.environ:
        pytest.skip("Requires a real local hosted stack and a contributor inference endpoint")
    server = os.environ["METTA_PARLEY_SYSTEM_SERVER"]
    assert urlparse(server).hostname in {"localhost", "127.0.0.1"}
    name = f"parley-endpoint-system-{uuid4().hex[:12]}"
    image = f"{name}:local"
    project = tmp_path / "player"

    with (tmp_path / "commands.log").open("w") as log:

        def cli(*args: str) -> None:
            subprocess.run(
                [sys.executable, "-m", "coworld", *args],
                check=True,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=1500,
            )

        cli("init", "player", str(project), "--example", "parley")
        subprocess.run(
            [
                "docker",
                "build",
                "--platform=linux/amd64",
                "--build-arg",
                'PARLEY_INFERENCE={"seed":42}',
                "-t",
                image,
                str(project),
            ],
            check=True,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=300,
        )
        credential_args = (
            ["--llm-api-key-env", os.environ["METTA_PARLEY_SYSTEM_API_KEY_ENV"]]
            if "METTA_PARLEY_SYSTEM_API_KEY_ENV" in os.environ
            else []
        )
        cli(
            "upload-policy",
            image,
            "--name",
            name,
            "--server",
            server,
            "--use-llm",
            "--llm-endpoint",
            os.environ["METTA_PARLEY_SYSTEM_ENDPOINT"],
            "--llm-model",
            os.environ["METTA_PARLEY_SYSTEM_MODEL"],
            *credential_args,
        )
        cli(
            "upload-policy",
            os.environ["METTA_PARLEY_SYSTEM_GAME_IMAGE"],
            "--name",
            name + "-scripted",
            "--server",
            server,
            "--run",
            "/bin/parley-player",
            "--secret-env",
            "PLAYER_SCRIPTED=1",
        )
        with CoworldApiClient.from_login(server_url=server) as client:
            policy = client.lookup_policy_version(name=name, version=1)
            assert policy is not None
            request = {
                "idempotency_key": name,
                "private": True,
                "coworld_id": os.environ["METTA_PARLEY_SYSTEM_COWORLD"],
                "variant_id": "table5",
                "game_config_overrides": {"seed": 20261019},
                "roster": [
                    {"player": {"policy_ref": name + ":v1"}, "slot": 0},
                    *[{"player": {"policy_ref": name + "-scripted:v1"}, "slot": slot} for slot in range(1, 5)],
                ],
                "num_episodes": 1,
            }
            batch = client.create_experience_request(request)
            assert client.create_experience_request(request).id == batch.id
            (tmp_path / "request.json").write_text(json.dumps(request))
            (tmp_path / "batch.json").write_text(batch.model_dump_json())
            cli(
                "xp-request",
                "watch",
                batch.id,
                "--server",
                server,
                "--until",
                "evidence",
                "--include",
                "player_artifact",
                "--timeout",
                "1200",
            )
            assert len(batch.episodes) == 1
            episode = client.get_episode_request(batch.episodes[0].id)
            (tmp_path / "episode.json").write_text(episode.model_dump_json())
            assert episode.status == "completed", episode.error
            assert episode.replay_url and episode.scores
            replay = client.get_episode_request_artifact_bytes(episode.id, "replay")
            assert replay
            (tmp_path / "replay").write_bytes(replay)
            archive = client.get_episode_request_policy_artifact(episode.id, policy.id, 0)
            (tmp_path / "player-artifact.zip").write_bytes(archive)
            captures = read_capture_archive(archive)
            assert captures
            assert all(c.seat == 0 and c.platform_call_id is not None and c.request.seed == 42 for c in captures)
            assert all(c.completion() for c in captures)
