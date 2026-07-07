from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from coworld.image_refs import image_ref_without_tag, is_digest_pinned_image_ref, is_mutable_registry_image_ref
from coworld.schema_validation import load_json_object
from coworld.types import CoworldManifest, CoworldRunnableSpec

# Compose-built runnable sections. `reporter` is deliberately absent: reporter entries are
# references (spec 0061) — platform reporter versions or wasm components — not container images.
ROLE_SECTIONS = ("player", "commissioner", "grader", "diagnoser", "optimizer")
FULL_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def build_coworld_manifest(
    compose_file: Path,
    template_path: Path,
    version: str,
    output_path: Path,
    *,
    resolve_mutable_image_refs: bool = False,
    source_contexts: tuple[Path, ...] = (),
) -> Path:
    compose_file = compose_file.resolve()
    template_path = template_path.resolve()
    output_path = output_path.resolve()
    if not compose_file.is_file():
        raise RuntimeError(f"Compose file not found for Coworld build: {compose_file}")

    manifest_json = load_json_object(template_path)
    game = manifest_json["game"]
    if isinstance(game, dict) and "version" in game and template_path.name != "coworld_manifest.json":
        raise RuntimeError(f"Coworld manifest templates must not set game.version: {template_path}")

    compose_services = _compose_services(compose_file)
    manifest = _load_template_manifest(manifest_json, version, _compose_image_placeholders(compose_services))
    if source_contexts:
        manifest = _with_pinned_source_urls(manifest, _github_source_contexts(source_contexts))
    # Pull image-only services before building; buildable services are produced locally below.
    subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "pull", "--ignore-buildable", "--ignore-pull-failures"],
        cwd=compose_file.parent,
        check=True,
    )
    # --pull so buildable services (e.g. a commissioner built FROM
    # commissioners-default:latest) always refresh their base image instead of
    # reusing a stale locally-cached one. A mutable FROM can otherwise bake an
    # out-of-date base, and --resolve-mutable-images below only rewrites manifest
    # image refs after the local image is built, not Dockerfile base layers.
    subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "build", "--pull"],
        cwd=compose_file.parent,
        check=True,
    )
    if resolve_mutable_image_refs:
        resolved_image_refs = _resolved_mutable_image_refs(manifest)
        manifest = _with_image_tags(manifest, resolved_image_refs)
        _pull_image_refs(
            resolved_image_refs,
            _compose_image_platforms(compose_services),
            _compose_default_platform(compose_services),
        )
    manifest = _with_image_tags(manifest, _built_image_tags(manifest))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest.model_dump(by_alias=True, exclude_none=True), indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def _load_template_manifest(
    manifest_json: dict[str, Any], version: str, image_placeholders: dict[str, str]
) -> CoworldManifest:
    game = manifest_json["game"]
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


def _compose_services(compose_file: Path) -> dict[str, dict[str, Any]]:
    completed = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "config", "--format", "json"],
        cwd=compose_file.parent,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)["services"]


def _compose_image_placeholders(services: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    return {
        f"{{{{{service_name.upper().replace('-', '_')}_IMAGE}}}}": service["image"]
        for service_name, service in services.items()
    }


def _compose_image_platforms(services: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    image_platforms: dict[str, str] = {}
    for service in services.values():
        image = service.get("image")
        platform = service.get("platform")
        if isinstance(image, str) and isinstance(platform, str):
            image_platforms[image] = platform
    return image_platforms


def _compose_default_platform(services: Mapping[str, Mapping[str, Any]]) -> str | None:
    platforms = {service["platform"] for service in services.values() if isinstance(service.get("platform"), str)}
    if len(platforms) == 1:
        return next(iter(platforms))
    return None


def _github_source_contexts(source_contexts: tuple[Path, ...]) -> dict[str, Path]:
    contexts: dict[str, Path] = {}
    for source_context in source_contexts:
        repo_root = Path(_git_stdout(source_context, "rev-parse", "--show-toplevel"))
        repo = _github_repo_from_remote(_git_stdout(repo_root, "remote", "get-url", "origin"))
        if repo is not None:
            contexts[repo] = repo_root
    return contexts


def _github_repo_from_remote(remote_url: str) -> str | None:
    if remote_url.startswith("git@github.com:"):
        repo = remote_url.removeprefix("git@github.com:")
    else:
        parsed = urlparse(remote_url)
        if parsed.netloc != "github.com":
            return None
        repo = parsed.path.removeprefix("/")
    return repo.removesuffix(".git")


def _with_pinned_source_urls(manifest: CoworldManifest, source_contexts: Mapping[str, Path]) -> CoworldManifest:
    game = manifest.game.model_copy(
        update={"runnable": _with_pinned_runnable_source_url(manifest.game.runnable, source_contexts)}
    )
    updates: dict[str, object] = {"game": game}
    for section in ROLE_SECTIONS:
        updates[section] = [
            _with_pinned_runnable_source_url(runnable, source_contexts) for runnable in getattr(manifest, section)
        ]
    return manifest.model_copy(update=updates)


def _with_pinned_runnable_source_url(
    runnable: CoworldRunnableSpec, source_contexts: Mapping[str, Path]
) -> CoworldRunnableSpec:
    if runnable.source_url is None:
        return runnable
    source_url = _pinned_source_url(runnable.source_url, source_contexts)
    if source_url == runnable.source_url:
        return runnable
    return runnable.model_copy(update={"source_url": source_url})


def _pinned_source_url(source_url: str, source_contexts: Mapping[str, Path]) -> str:
    parsed = urlparse(source_url)
    if parsed.netloc != "github.com":
        return source_url
    parts = parsed.path.removeprefix("/").split("/")
    if len(parts) < 4 or parts[2] not in {"tree", "blob"}:
        return source_url
    ref = parts[3]
    if FULL_SHA_PATTERN.fullmatch(ref):
        return source_url
    repo_root = source_contexts.get(f"{parts[0]}/{parts[1]}")
    if repo_root is None:
        return source_url
    parts[3] = _source_context_ref_sha(repo_root, ref)
    return urlunparse(parsed._replace(path="/" + "/".join(parts)))


def _source_context_ref_sha(repo_root: Path, ref: str) -> str:
    head_sha = _git_stdout(repo_root, "rev-parse", "HEAD")
    ref_completed = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", "--quiet", f"origin/{ref}^{{commit}}"],
        capture_output=True,
        text=True,
    )
    if ref_completed.returncode != 0:
        return head_sha
    ref_sha = ref_completed.stdout.strip()
    ancestor_completed = subprocess.run(
        ["git", "-C", str(repo_root), "merge-base", "--is-ancestor", ref_sha, head_sha]
    )
    if ancestor_completed.returncode == 0:
        return head_sha
    return ref_sha


def _git_stdout(repo_path: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _built_image_tags(manifest: CoworldManifest) -> dict[str, str]:
    image_tags: dict[str, str] = {}
    for image in _manifest_images(manifest):
        if is_digest_pinned_image_ref(image):
            image_tags[image] = image
            continue
        tag_image = image.split("@", 1)[0]
        image_id = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", image],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        build_tag = _sha_tag(tag_image, image_id)
        subprocess.run(["docker", "tag", image, build_tag], check=True)
        image_tags[image] = build_tag

    return image_tags


def _resolved_mutable_image_refs(manifest: CoworldManifest) -> dict[str, str]:
    return {
        image: resolve_registry_image_ref(image)
        for image in _manifest_images(manifest)
        if is_mutable_registry_image_ref(image)
    }


def resolve_registry_image_ref(image: str) -> str:
    completed = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", image, "--format", "{{json .Manifest}}"],
        check=True,
        capture_output=True,
        text=True,
    )
    manifest = json.loads(completed.stdout)
    digest = manifest.get("digest")
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise RuntimeError(f"Could not resolve immutable digest for image ref: {image}")
    return f"{image_ref_without_tag(image)}@{digest}"


def _pull_image_refs(
    image_refs: Mapping[str, str], image_platforms: Mapping[str, str], default_platform: str | None
) -> None:
    for source_image, resolved_image in sorted(image_refs.items()):
        command = ["docker", "pull"]
        platform = image_platforms.get(source_image, default_platform)
        if platform:
            command.extend(["--platform", platform])
        command.append(resolved_image)
        subprocess.run(command, check=True)


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
            "runnable": manifest.game.runnable.model_copy(
                update={"image": image_tags.get(manifest.game.runnable.image, manifest.game.runnable.image)}
            )
        }
    )
    updates: dict[str, object] = {"game": game}
    for section in ROLE_SECTIONS:
        updates[section] = [
            runnable.model_copy(update={"image": image_tags.get(runnable.image, runnable.image)})
            for runnable in getattr(manifest, section)
        ]
    return manifest.model_copy(update=updates)
