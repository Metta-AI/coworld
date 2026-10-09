"""Local Docker image cache for downloaded Coworlds.

`coworld download` only writes the manifest, `coworld_images.json`, and player files. The
images behind the rewritten `coworld/<id>/...:downloaded` tags are pulled here, the first
time something loads the package to run it locally.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

DOWNLOADED_IMAGES_FILENAME = "coworld_images.json"
_DOCKER_AUTH_CONFIG_KEYS = {"auths", "credsStore", "credHelpers"}


def pull_and_tag_image(public_image_uri: str, local_tag: str) -> None:
    if public_image_uri.startswith("public.ecr.aws/"):
        # Anonymous public pulls fail when the caller's Docker config carries stale
        # public-ECR auth (ecr-public login tokens expire ~12h; ecr-login credHelpers
        # break with expired AWS creds). Pull through a temp DOCKER_CONFIG that keeps
        # the active Docker context (colima/OrbStack/Desktop) but drops auth material.
        with tempfile.TemporaryDirectory(prefix="coworld-docker-config-") as docker_config:
            _prepare_public_ecr_docker_config(Path(docker_config))
            subprocess.run(
                ["docker", "pull", public_image_uri],
                check=True,
                env={**os.environ, "DOCKER_CONFIG": docker_config},
            )
    else:
        subprocess.run(["docker", "pull", public_image_uri], check=True)
    subprocess.run(["docker", "tag", public_image_uri, local_tag], check=True)


def _prepare_public_ecr_docker_config(docker_config: Path) -> None:
    source_config = Path(os.environ.get("DOCKER_CONFIG") or str(Path.home() / ".docker")).expanduser()
    config_path = source_config / "config.json"
    if config_path.is_file():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        for key in _DOCKER_AUTH_CONFIG_KEYS:
            config.pop(key, None)
        (docker_config / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    contexts_path = source_config / "contexts"
    if contexts_path.exists():
        shutil.copytree(contexts_path, docker_config / "contexts")


def ensure_downloaded_images(manifest_path: Path) -> None:
    """Pull and tag any image of a downloaded Coworld whose local tag is missing.

    Idempotent: tags that already exist (including from earlier downloads) are not pulled
    again. Manifests that are not next to a `coworld_images.json` are left untouched.
    """
    images_path = manifest_path.parent / DOWNLOADED_IMAGES_FILENAME
    if not images_path.is_file():
        return
    for entry in json.loads(images_path.read_text(encoding="utf-8"))["images"]:
        local_tag = entry["local_image"]
        inspect = subprocess.run(["docker", "image", "inspect", local_tag], capture_output=True, check=False)
        if inspect.returncode != 0:
            pull_and_tag_image(entry["public_image_uri"], local_tag)
