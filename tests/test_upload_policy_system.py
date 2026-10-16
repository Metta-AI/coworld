"""Real local upload regression: image archives must not require whole-image staging.

Run with METTA_COWORLD_UPLOAD_SYSTEM_SERVER pointing at a local frontend proxy,
METTA_COWORLD_UPLOAD_SYSTEM_BASE_IMAGE naming a cached Alpine image, and a local
USER debug credential in SOFTMAX_CONFIG_DIR. This creates an isolated local policy.
"""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import pytest

from coworld.api_client import CoworldApiClient


def test_upload_policy_with_file_limit_smaller_than_image(tmp_path: Path) -> None:
    server = os.environ.get("METTA_COWORLD_UPLOAD_SYSTEM_SERVER")
    base_image = os.environ.get("METTA_COWORLD_UPLOAD_SYSTEM_BASE_IMAGE")
    if not server or not base_image:
        pytest.skip("Requires a real local stack and cached Alpine base image")
    assert urlparse(server).hostname in {"localhost", "127.0.0.1"}
    name = f"upload-stream-system-{uuid4().hex[:12]}"
    image = f"{name}:local"
    for filename in ("first", "second"):
        (tmp_path / filename).write_bytes(os.urandom(4 * 1024 * 1024))
    (tmp_path / "Dockerfile").write_text(
        f"FROM {base_image} AS base\n"
        "FROM scratch\n"
        "COPY --from=base /bin/busybox /bin/busybox\n"
        "COPY --from=base /lib /lib\n"
        "COPY first /first\n"
        "COPY second /second\n"
        'ENTRYPOINT ["/bin/busybox", "echo", "upload-system-proof"]\n'
    )
    subprocess.run(
        ["docker", "build", "--platform=linux/amd64", "--pull=false", "-t", image, str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )
    try:
        # Kernel-enforced per-file limit applies only to the CLI, not the Docker daemon.
        # Each layer fits; the image archive exceeds the limit even without tar headers.
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import resource; resource.setrlimit(resource.RLIMIT_FSIZE, (6*1024*1024, 6*1024*1024)); "
                "from coworld.cli import app; app()",
                "upload-policy",
                image,
                "--name",
                name,
                "--server",
                server,
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        (tmp_path / "upload.stdout").write_text(result.stdout)
        (tmp_path / "upload.stderr").write_text(result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"Upload complete: {name}:v1" in result.stdout
        with CoworldApiClient.from_login(server_url=server) as client:
            policy = client.lookup_policy_version(name=name, version=1)
        assert policy is not None
        assert policy.name == name
    finally:
        subprocess.run(["docker", "image", "rm", image], check=True, capture_output=True)
