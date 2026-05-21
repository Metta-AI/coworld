from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from coworld.schema_validation import load_json_object
from coworld.types import CoworldManifest

ROLE_SECTIONS = ("player", "reporter", "commissioner", "grader", "diagnoser", "optimizer")


def build_coworld_manifest(
    compose_file: Path,
    template_path: Path,
    version: str,
    output_path: Path,
) -> Path:
    compose_file = compose_file.resolve()
    template_path = template_path.resolve()
    output_path = output_path.resolve()
    if not compose_file.is_file():
        raise RuntimeError(f"Compose file not found for Coworld build: {compose_file}")

    manifest = _load_template_manifest(template_path, version, _compose_image_placeholders(compose_file))
    subprocess.run(["docker", "compose", "-f", str(compose_file), "build"], cwd=compose_file.parent, check=True)
    manifest = _with_image_tags(manifest, _built_image_tags(manifest))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest.model_dump(by_alias=True, exclude_none=True), indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def _load_template_manifest(template_path: Path, version: str, image_placeholders: dict[str, str]) -> CoworldManifest:
    manifest_json = load_json_object(template_path)
    game = manifest_json["game"]
    if "version" in game:
        raise RuntimeError(f"Coworld manifest templates must not set game.version: {template_path}")
    game["version"] = version
    runnables: list[dict[str, Any]] = [game["runnable"]]
    for section in ROLE_SECTIONS:
        if section in manifest_json:
            runnables.extend(manifest_json[section])
    for runnable in runnables:
        image = runnable["image"]
        if image in image_placeholders:
            runnable["image"] = image_placeholders[image]
        elif image.startswith("{{") and image.endswith("}}"):
            raise RuntimeError(f"Coworld image placeholder does not match a Compose service: {image}")
    return CoworldManifest.model_validate(manifest_json)


def _compose_image_placeholders(compose_file: Path) -> dict[str, str]:
    completed = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "config", "--format", "json"],
        cwd=compose_file.parent,
        check=True,
        capture_output=True,
        text=True,
    )
    services = json.loads(completed.stdout)["services"]
    return {
        f"{{{{{service_name.upper().replace('-', '_')}_IMAGE}}}}": service["image"]
        for service_name, service in services.items()
    }


def _built_image_tags(manifest: CoworldManifest) -> dict[str, str]:
    image_tags: dict[str, str] = {}
    for image in _manifest_images(manifest):
        local_image = image.split("@", 1)[0]
        image_id = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", local_image],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        build_tag = _sha_tag(local_image, image_id)
        subprocess.run(["docker", "tag", local_image, build_tag], check=True)
        image_tags[image] = build_tag

    return image_tags


def _manifest_images(manifest: CoworldManifest) -> tuple[str, ...]:
    images = [manifest.game.runnable.image]
    for section in ROLE_SECTIONS:
        images.extend(runnable.image for runnable in getattr(manifest, section))
    return tuple(dict.fromkeys(images))


def _sha_tag(image: str, image_id: str) -> str:
    tag_separator = image.rfind(":")
    slash_separator = image.rfind("/")
    image_name = image[:tag_separator] if tag_separator > slash_separator else image
    return f"{image_name}:coworld-{image_id.removeprefix('sha256:')[:12]}"


def _with_image_tags(manifest: CoworldManifest, image_tags: dict[str, str]) -> CoworldManifest:
    game = manifest.game.model_copy(
        update={
            "runnable": manifest.game.runnable.model_copy(update={"image": image_tags[manifest.game.runnable.image]})
        }
    )
    updates: dict[str, object] = {"game": game}
    for section in ROLE_SECTIONS:
        updates[section] = [
            runnable.model_copy(update={"image": image_tags[runnable.image]}) for runnable in getattr(manifest, section)
        ]
    return manifest.model_copy(update=updates)
