"""Real BuildKit -> OCI archive -> Coworld upload, without a Docker daemon.

Set METTA_BUILDKIT_HOST and METTA_COWORLD_UPLOAD_SYSTEM_SERVER and supply normal CLI
credentials. The test registers one isolated policy; it never enters a league.
"""

import io
import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from uuid import uuid4

import pytest

from coworld.api_client import CoworldApiClient


def test_buildkit_policy(tmp_path: Path) -> None:
    host = os.environ.get("METTA_BUILDKIT_HOST")
    server = os.environ.get("METTA_COWORLD_UPLOAD_SYSTEM_SERVER")
    if not host or not server:
        pytest.skip("Requires a real BuildKit endpoint, API, and normal upload credentials")
    context = tmp_path / "context"
    context.mkdir()
    (context / "Dockerfile").write_text("FROM scratch\nCOPY . /source/\n")
    (context / ".dockerignore").write_text("ignored\n")
    (context / "ignored").write_text("excluded")
    (context / "binary").write_bytes(bytes(range(256)) * 20000)
    for index in range(300):
        (context / f"file-{index}").write_text(str(index))
    (context / "executable").write_text("#!/bin/sh\necho proof\n")
    (context / "executable").chmod(0o755)
    (context / "link").symlink_to("executable")
    image = tmp_path / "new-output-directory" / "policy.tar"
    command = [
        sys.executable,
        "-c",
        "from coworld.cli import app; app()",
        "build-policy",
        str(context),
        "--output",
        str(image),
    ]
    environment = dict(os.environ, BUILDKIT_HOST=host)
    subprocess.run(command, env=environment, check=True, timeout=120)
    with tarfile.open(image) as archive:
        index_file = archive.extractfile("index.json")
        assert index_file is not None
        index = json.load(index_file)
        manifest_file = archive.extractfile("blobs/" + index["manifests"][0]["digest"].replace(":", "/", 1))
        assert manifest_file is not None
        manifest = json.load(manifest_file)
        layer_file = archive.extractfile("blobs/" + manifest["layers"][0]["digest"].replace(":", "/", 1))
        assert layer_file is not None
        layer_bytes = layer_file.read()
    with tarfile.open(fileobj=io.BytesIO(layer_bytes)) as layer:
        assert "source/ignored" not in layer.getnames()
        assert layer.getmember("source/binary").size == 5_120_000
        assert layer.getmember("source/executable").mode & 0o111
        assert layer.getmember("source/link").issym()
        assert sum(name.startswith("source/file-") for name in layer.getnames()) == 300
    cached = subprocess.run(command, env=environment, check=True, capture_output=True, text=True, timeout=120)
    assert "CACHED" in cached.stderr
    name = f"buildkit-system-{uuid4().hex[:12]}"
    upload = [
        sys.executable,
        "-c",
        "from coworld.cli import app; app()",
        "upload-policy",
        "--image-archive",
        str(image),
        "--name",
        name,
        "--server",
        server,
    ]
    first = subprocess.run(upload, cwd=tmp_path, capture_output=True, text=True, timeout=180)
    assert first.returncode == 0, first.stdout + first.stderr
    repeated = subprocess.run(upload, cwd=tmp_path, capture_output=True, text=True, timeout=180)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    for result in (first, repeated):
        assert f"Upload complete: {name}:v1" in result.stdout
    with CoworldApiClient.from_login(server_url=server) as client:
        policy = client.lookup_policy_version(name=name, version=1)
    assert policy is not None and policy.name == name
    (context / "Dockerfile").write_text("FROM scratch\nCOPY missing /missing\n")
    failed = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=120)
    assert failed.returncode != 0 and "missing" in failed.stderr
    assert not image.exists()
