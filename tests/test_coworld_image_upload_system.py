"""Upload and certify a real local Coworld without rewriting game-owned image data."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import pytest

from coworld.upload import CoworldUploadClient

pytestmark = pytest.mark.skipif(
    "METTA_COWORLD_IMAGE_UPLOAD_SYSTEM_CONFIG" not in os.environ,
    reason="requires a local hosted stack and a prepared task-enabled game image",
)


def test_upload_preserves_schema_images_and_resolves_task_images(tmp_path: Path) -> None:
    settings = json.loads(Path(os.environ["METTA_COWORLD_IMAGE_UPLOAD_SYSTEM_CONFIG"]).read_text())
    server = settings["server"]
    assert urlparse(server).hostname in {"localhost", "127.0.0.1"}
    manifest = json.loads(Path(settings["manifest"]).read_text())
    manifest["game"]["name"] = f"image-reference-proof-{uuid4().hex[:12]}"
    schema = manifest["game"]["config_schema"]
    schema["properties"]["image"] = {"type": "string", "description": "Game-owned provenance, not a container."}
    schema["examples"] = [{"image": "opaque-provenance"}]
    source = tmp_path / "coworld_manifest.json"
    source.write_text(json.dumps(manifest))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "coworld",
            "upload-coworld",
            str(source),
            "--server",
            server,
            "--visibility",
            "private",
            "--no-wait-hosted-smoke",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    (tmp_path / "upload.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    coworld_id = next(
        line.removeprefix("Coworld: ") for line in result.stdout.splitlines() if line.startswith("Coworld: ")
    )
    with CoworldUploadClient.from_login(server_url=server) as api:
        uploaded = api.get_coworld(coworld_id)
        (tmp_path / "uploaded.json").write_text(uploaded.model_dump_json(indent=2))
        assert uploaded.manifest["game"]["config_schema"] == schema
        assert uploaded.manifest["game"]["runnable"]["image"].startswith("img_")
        assert all(row["image"].startswith("img_") for row in uploaded.manifest["game"]["task_environments"].values())
        deadline = time.monotonic() + 600
        while True:
            status = api.get_coworld_certification(coworld_id)
            (tmp_path / "certification.json").write_text(status.model_dump_json(indent=2))
            if status.certified:
                break
            assert status.state not in {"failed", "rejected"}, status
            assert time.monotonic() < deadline, status
            time.sleep(2)
