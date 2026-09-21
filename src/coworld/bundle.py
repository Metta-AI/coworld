from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import urlparse, urlunparse

from coworld.image_refs import image_ref_without_tag, is_digest_pinned_image_ref, is_mutable_registry_image_ref
from coworld.manifest import validate_upload_manifest
from coworld.player_files import resolve_player_file
from coworld.schema_validation import load_json_object
from coworld.types import CoworldManifest, CoworldRunnableSpec

# Compose-built runnable sections. `reporter` is deliberately absent: reporter entries are
# references (spec 0061) — platform reporter versions or wasm components — not container images.
ROLE_SECTIONS = ("player", "commissioner", "grader", "diagnoser", "optimizer")
FULL_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
REPLAY_VIEWER_BUILD_HOOK = Path("tools/build_replay_viewer.sh")
_WINDOWS = os.name == "nt"


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

    manifest_json = load_json_object(template_path)
    game = manifest_json["game"]
    if isinstance(game, dict) and "version" in game:
        raise RuntimeError(f"Coworld manifest templates must not set game.version: {template_path}")

    compose_config = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "config", "--format", "json"],
        cwd=compose_file.parent,
        check=True,
        capture_output=True,
        text=True,
    )
    compose_services = json.loads(compose_config.stdout)["services"]
    image_placeholders = {
        f"{{{{{service_name.upper().replace('-', '_')}_IMAGE}}}}": service["image"]
        for service_name, service in compose_services.items()
    }
    game["version"] = version
    runnables: list[dict[str, Any]] = [game["runnable"]]
    for section in ROLE_SECTIONS:
        if section in manifest_json:
            runnables.extend(manifest_json[section])
    for runnable in runnables:
        image = runnable.get("image")
        if image is None:
            continue
        if image in image_placeholders:
            runnable["image"] = image_placeholders[image]
        elif image.startswith("{{") and image.endswith("}}"):
            raise RuntimeError(f"Coworld image placeholder does not match a Compose service: {image}")
    manifest = validate_upload_manifest(manifest_json).runtime_manifest
    manifest = _with_pinned_source_urls(manifest, _github_source_contexts((compose_file.parent,)))
    # Pull image-only services before building; buildable services are produced locally below.
    subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "pull", "--ignore-buildable", "--ignore-pull-failures"],
        cwd=compose_file.parent,
        check=True,
    )
    # --pull so buildable services (e.g. a commissioner built FROM
    # commissioners-default:latest) always refresh their base image instead of
    # reusing a stale locally-cached one. A mutable FROM can otherwise bake an
    # out-of-date base, and image resolution below only rewrites manifest
    # image refs after the local image is built, not Dockerfile base layers.
    subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "build", "--pull"],
        cwd=compose_file.parent,
        check=True,
    )
    resolved_image_refs = {
        image: resolve_registry_image_ref(image)
        for image in _manifest_images(manifest)
        if is_mutable_registry_image_ref(image)
    }
    manifest = _with_image_tags(manifest, resolved_image_refs)
    image_platforms = {
        service["image"]: service["platform"]
        for service in compose_services.values()
        if isinstance(service.get("image"), str) and isinstance(service.get("platform"), str)
    }
    platforms = {
        service["platform"] for service in compose_services.values() if isinstance(service.get("platform"), str)
    }
    default_platform = next(iter(platforms)) if len(platforms) == 1 else None
    for source_image, resolved_image in sorted(resolved_image_refs.items()):
        command = ["docker", "pull"]
        platform = image_platforms.get(source_image, default_platform)
        if platform:
            command.extend(["--platform", platform])
        command.append(resolved_image)
        subprocess.run(command, check=True)

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
        tag_separator = tag_image.rfind(":")
        slash_separator = tag_image.rfind("/")
        image_name = tag_image[:tag_separator] if tag_separator > slash_separator else tag_image
        build_tag = f"{image_name}:coworld-{image_id.removeprefix('sha256:')[:12]}"
        subprocess.run(["docker", "tag", image, build_tag], check=True)
        image_tags[image] = build_tag
    manifest = _with_image_tags(manifest, image_tags)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _build_replay_viewer_bundle(manifest, template_path.parent, output_path.parent)
    _copy_player_files(manifest, template_path.parent, output_path.parent)
    output_path.write_text(
        json.dumps(manifest.model_dump(exclude_none=True), indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def _copy_player_files(manifest: CoworldManifest, source_root: Path, output_root: Path) -> None:
    """Materialize file-backed players next to the built manifest.

    ``player[].file`` stays package-relative in the built manifest, and upload,
    certification and ``run-episode`` all resolve it against the manifest's directory,
    so the built package must carry the bytes, not point back at the source tree.
    """
    output_root = output_root.resolve()
    for player in manifest.player:
        if player.file is None or player.file.startswith("sha256:"):
            continue
        source = resolve_player_file(Path(player.file), package_root=source_root)
        destination = (output_root / player.file).resolve()
        destination.relative_to(output_root)
        if destination == source:
            continue
        # Replace, never merge: a rebuild into the same dist/ must not keep files the
        # source player has since deleted or renamed.
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        elif destination.exists() or destination.is_symlink():
            destination.unlink()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)


def _build_replay_viewer_bundle(manifest: CoworldManifest, source_root: Path, output_root: Path) -> None:
    replay_viewer = manifest.game.replay_viewer
    if replay_viewer is None or replay_viewer.bundle.startswith("sha256:"):
        return

    source_root = source_root.resolve()
    output_root = output_root.resolve()
    bundle_dir = (output_root / replay_viewer.bundle).resolve()
    bundle_dir.relative_to(output_root)
    build_hook = source_root / REPLAY_VIEWER_BUILD_HOOK
    if not build_hook.is_file() or not os.access(build_hook, os.X_OK):
        raise RuntimeError(
            f"Coworld builds with a source replay viewer bundle require an executable build hook: {build_hook}"
        )
    command = [str(build_hook), str(bundle_dir)]
    if _WINDOWS:
        # Windows CreateProcess cannot execute a shell script (WinError 193), and the
        # executable-bit guard above always passes there, so run the hook through bash.
        # The bundle directory argument stays a native Windows path; hooks must accept it.
        bash = shutil.which("bash")
        if bash is not None and PureWindowsPath(bash).parent.name.lower() in {"system32", "sysnative"}:
            # WSL's launcher bash.exe: it runs the script inside the distro, where the native
            # C:\ script and bundle-dir arguments do not resolve (drives mount under /mnt).
            bash = None
        if bash is None:
            raise RuntimeError(
                "Coworld replay viewer build hooks are shell scripts, which Windows cannot execute "
                "directly; install bash (e.g. Git Bash — WSL's bash.exe cannot run hooks with native "
                f"Windows paths) or run the build from WSL: {build_hook}"
            )
        command = [bash, *command]
    subprocess.run(command, cwd=source_root, check=True)
    if not bundle_dir.is_dir():
        raise RuntimeError(f"Replay viewer build hook did not produce its bundle directory: {bundle_dir}")
    if not (bundle_dir / "index.html").is_file():
        raise RuntimeError(f"Replay viewer build hook did not produce index.html: {bundle_dir}")


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
    ancestor_completed = subprocess.run(["git", "-C", str(repo_root), "merge-base", "--is-ancestor", ref_sha, head_sha])
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


def _manifest_images(manifest: CoworldManifest) -> tuple[str, ...]:
    images = [manifest.game.runnable.image]
    for section in ROLE_SECTIONS:
        images.extend(runnable.image for runnable in getattr(manifest, section) if runnable.image is not None)
    return tuple(dict.fromkeys(images))


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
            runnable
            if runnable.image is None
            else runnable.model_copy(update={"image": image_tags.get(runnable.image, runnable.image)})
            for runnable in getattr(manifest, section)
        ]
    return manifest.model_copy(update=updates)
