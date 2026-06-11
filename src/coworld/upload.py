from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import shlex
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Self
from uuid import UUID

import httpx
import typer
from pydantic import BaseModel

from coworld.certifier import certify_coworld, load_coworld_package
from coworld.config import DEFAULT_SUBMIT_SERVER
from coworld.image_refs import is_mutable_registry_image_ref
from coworld.manifest_validation import validate_coworld_manifest_game_configs
from coworld.schema_validation import validate_json_schema
from coworld.types import MANIFEST_ROLE_SECTIONS, CoworldManifest, coworld_manifest_schema

_LOCAL_TAG_SEPARATOR_RE = re.compile(r"[^a-z0-9._-]+")
_IMAGE_ID_RE = re.compile(r"^img_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
DOWNLOAD_AGENTS_MD = """# AGENTS.md

Guidance for coding agents working from this downloaded Coworld package.

## Facts

- Champion means your nominated policy version: the chosen participant you want to represent you in a league. It is not
  a claim that the policy has won the tournament.

## Start

- Read `coworld_manifest.json` before changing policy code.
- Treat `game.protocols.player`, `game.docs.pages`, `variants`, and `certification` as the local contract for this
  package.
- Run `uv run coworld run-episode ./coworld_manifest.json --timeout-seconds 120` with the bundled players before
  testing your own image.

## Policy Work

- Keep policy source in your policy project, not in this downloaded Coworld cache.
- Use the manifest path from this directory when building, running, and comparing policies.
"""


class CoworldUploadResponse(BaseModel):
    id: str
    name: str
    version: str
    manifest: dict[str, Any]
    manifest_hash: str
    size_bytes: int
    canonical: bool


class PolicyVersionResponse(BaseModel):
    id: str
    name: str
    version: int
    pools: list[str] | None = None
    submit_error: str | None = None


class EcrPushInfo(BaseModel):
    kind: str = "ecr"
    region: str
    registry: str
    repository: str
    tag: str
    image_uri: str
    endpoint_url: str | None = None
    authorization_token: str


class ContainerImageResponse(BaseModel):
    id: str
    name: str
    version: int
    client_hash: str | None = None
    status: str
    image_uri: str | None = None
    image_digest: str | None = None
    public_image_uri: str | None = None


class CoworldListEntry(BaseModel):
    id: str
    name: str
    version: str
    manifest: dict[str, Any]
    manifest_hash: str
    size_bytes: int
    created_at: datetime
    canonical: bool


class LeagueSubmissionResponse(BaseModel):
    id: str
    status: str
    league_policy_membership_id: str | None = None
    notes: str | None = None


class AutoChampion(str, Enum):
    always = "always"
    never = "never"
    lineage = "lineage"


class CoworldLeagueSeedResponse(BaseModel):
    id: str
    coworld_name: str
    template: str
    overrides: dict[str, Any] | None = None
    enabled: bool
    created_by: str
    created_at: str
    league_id: str | None = None


class HostedGameCreateResponse(BaseModel):
    session_id: str
    join_url: str
    lobby_url: str
    player_count: int
    global_url: str | None


class HostedGameJoinPlayer(BaseModel):
    slot: int
    label: str
    user_id: str | None = None
    player_id: str | None = None
    player_name: str | None = None
    joined_at: datetime | None = None


class HostedGameJoinResponse(BaseModel):
    player_url: str
    slot: int
    player: HostedGameJoinPlayer


class PolicyVersionRow(BaseModel):
    id: UUID
    name: str
    version: int


class PolicyVersionsResponse(BaseModel):
    entries: list[PolicyVersionRow]
    total_count: int


class ImageUploadResponse(BaseModel):
    image: ContainerImageResponse
    pre_signed_info: EcrPushInfo | None = None


@dataclass(frozen=True)
class CoworldUploadResult:
    id: str
    name: str
    version: str
    manifest_hash: str
    size_bytes: int
    canonical: bool


class CoworldUploadClient:
    def __init__(self, server_url: str, token: str):
        self._http_client = httpx.Client(base_url=f"{server_url.rstrip('/')}/observatory", timeout=30.0)
        self._token = token

    @classmethod
    def from_login(cls, *, server_url: str) -> Self:
        token = _load_current_token(server_url=server_url)
        if token is None:
            raise RuntimeError(f"Not authenticated. Run: uv run softmax login --server {server_url}")
        return cls(server_url=server_url, token=token)

    def close(self) -> None:
        self._http_client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def upload_manifest(self, manifest: dict[str, object]) -> CoworldUploadResponse:
        response = self._http_client.post(
            "/v2/coworlds/upload",
            headers=self._headers(),
            json={"manifest": manifest},
            timeout=120.0,
        )
        _raise_for_status(response)
        return CoworldUploadResponse.model_validate(response.json())

    def list_coworlds(self, *, limit: int = 200, offset: int = 0) -> list[CoworldListEntry]:
        response = self._http_client.get(
            "/v2/coworlds",
            headers=self._headers(),
            params={"limit": limit, "offset": offset},
            timeout=60.0,
        )
        _raise_for_status(response)
        return [CoworldListEntry.model_validate(item) for item in response.json()]

    def find_coworld(self, coworld_id: str) -> CoworldListEntry | None:
        limit = 200
        offset = 0
        while True:
            coworlds = self.list_coworlds(limit=limit, offset=offset)
            for coworld in coworlds:
                if coworld.id == coworld_id:
                    return coworld
            if len(coworlds) < limit:
                return None
            offset += limit

    def find_canonical_coworld(self, name: str) -> CoworldListEntry | None:
        target_name = _coworld_name_key(name)
        limit = 200
        offset = 0
        while True:
            coworlds = self.list_coworlds(limit=limit, offset=offset)
            for coworld in coworlds:
                if _coworld_name_key(coworld.name) == target_name and coworld.canonical:
                    return coworld
            if len(coworlds) < limit:
                return None
            offset += limit

    def lookup_policy_version(self, *, name: str, version: int | None = None) -> PolicyVersionRow | None:
        params: dict[str, Any] = {"mine": "true", "name_exact": name, "limit": 100}
        if version is not None:
            params["version"] = str(version)
        response = self._http_client.get(
            "/stats/policy-versions",
            headers=self._headers(),
            params=params,
            timeout=60.0,
        )
        _raise_for_status(response)
        versions = PolicyVersionsResponse.model_validate(response.json()).entries
        return versions[0] if versions else None

    def submit_to_league(
        self,
        league_id: str,
        policy_version_id: UUID,
        *,
        auto_champion: AutoChampion = AutoChampion.always,
    ) -> LeagueSubmissionResponse:
        response = self._http_client.post(
            "/v2/league-submissions",
            headers=self._headers(),
            json={
                "league_id": league_id,
                "policy_version_id": str(policy_version_id),
                "auto_champion": auto_champion.value,
            },
            timeout=120.0,
        )
        _raise_for_status(response)
        return LeagueSubmissionResponse.model_validate(response.json())

    def create_league_seed(
        self,
        *,
        coworld_name: str,
        template: str,
        overrides: dict[str, Any] | None = None,
        enabled: bool = True,
    ) -> CoworldLeagueSeedResponse:
        response = self._http_client.post(
            "/v2/coworld-league-seeds",
            headers=self._headers(),
            json={
                "coworld_name": coworld_name,
                "template": template,
                "overrides": overrides,
                "enabled": enabled,
            },
            timeout=120.0,
        )
        _raise_for_status(response)
        return CoworldLeagueSeedResponse.model_validate(response.json())

    def list_league_seeds(self) -> list[CoworldLeagueSeedResponse]:
        response = self._http_client.get(
            "/v2/coworld-league-seeds",
            headers=self._headers(),
            timeout=60.0,
        )
        _raise_for_status(response)
        return [CoworldLeagueSeedResponse.model_validate(item) for item in response.json()]

    def create_hosted_game(
        self,
        *,
        coworld_id: str,
        variant_id: str | None = None,
        allow_spectators: bool = False,
    ) -> HostedGameCreateResponse:
        response = self._http_client.post(
            "/v2/coworlds/play/session",
            headers=self._headers(),
            json={
                "coworld_id": coworld_id,
                "variant_id": variant_id,
                "allow_spectators": allow_spectators,
            },
            timeout=120.0,
        )
        _raise_for_status(response)
        return HostedGameCreateResponse.model_validate(response.json())

    def join_hosted_game(self, session_id: str) -> HostedGameJoinResponse:
        response = self._http_client.post(
            f"/v2/coworlds/play/session/{session_id}/join",
            headers=self._headers(),
            timeout=120.0,
        )
        _raise_for_status(response)
        return HostedGameJoinResponse.model_validate(response.json())

    def list_images(self, *, limit: int = 200, offset: int = 0) -> list[ContainerImageResponse]:
        response = self._http_client.get(
            "/v2/container_images",
            headers=self._headers(),
            params={"limit": limit, "offset": offset},
            timeout=60.0,
        )
        _raise_for_status(response)
        return [ContainerImageResponse.model_validate(item) for item in response.json()]

    def get_image(self, image_id: str) -> ContainerImageResponse:
        response = self._http_client.get(
            f"/v2/container_images/{image_id}",
            headers=self._headers(),
            timeout=60.0,
        )
        _raise_for_status(response)
        return ContainerImageResponse.model_validate(response.json())

    def request_image_upload(self, *, name: str, client_hash: str) -> ImageUploadResponse:
        response = self._http_client.post(
            "/v2/container_images/upload",
            headers=self._headers(),
            json={"name": name, "client_hash": client_hash},
            timeout=60.0,
        )
        _raise_for_status(response)
        return ImageUploadResponse.model_validate(response.json())

    def complete_image_upload(self, image_id: str) -> ContainerImageResponse:
        response = self._http_client.post(
            "/v2/container_images/upload/complete",
            headers=self._headers(),
            json={"id": image_id},
            timeout=120.0,
        )
        _raise_for_status(response)
        return ContainerImageResponse.model_validate(response.json())

    def complete_docker_image_policy(
        self,
        *,
        name: str,
        container_image_id: str,
        run: list[str] | None,
        secret_env: dict[str, str] | None,
        tags: dict[str, str] | None = None,
    ) -> PolicyVersionResponse:
        payload: dict[str, Any] = {"name": name, "container_image_id": container_image_id}
        if run:
            payload["run"] = run
        if secret_env:
            payload["policy_secret_env"] = secret_env
        if tags:
            payload["tags"] = tags
        response = self._http_client.post(
            "/stats/policies/docker-img/complete",
            headers=self._headers(),
            json=payload,
            timeout=120.0,
        )
        _raise_for_status(response)
        return PolicyVersionResponse.model_validate(response.json())


def upload_coworld(
    manifest_path: Path,
    *,
    server: str = DEFAULT_SUBMIT_SERVER,
    timeout_seconds: float = 60.0,
) -> CoworldUploadResult:
    package = load_coworld_package(manifest_path)
    manifest = package.manifest.model_dump(by_alias=True, exclude_none=True)
    _reject_mutable_registry_image_refs(manifest)
    certify_coworld(package.manifest_path, timeout_seconds=timeout_seconds)

    with CoworldUploadClient.from_login(server_url=server) as client:
        upload_manifest = _manifest_with_softmax_image_ids(client, manifest)
        response = client.upload_manifest(upload_manifest)

    return CoworldUploadResult(
        id=response.id,
        name=response.name,
        version=response.version,
        manifest_hash=response.manifest_hash,
        size_bytes=response.size_bytes,
        canonical=response.canonical,
    )


def upload_coworld_update(
    coworld_ref: str,
    *,
    server: str = DEFAULT_SUBMIT_SERVER,
    version: str | None = None,
    patch_update: str | None = None,
    image_updates: list[str] | None = None,
) -> CoworldUploadResult:
    if version is None and patch_update is None and not image_updates:
        raise ValueError("--from-coworld requires --version, --patch, or --image")

    with CoworldUploadClient.from_login(server_url=server) as client:
        coworld = _resolve_stored_coworld(client, coworld_ref)
        manifest = copy.deepcopy(coworld.manifest)
        _apply_manifest_updates(manifest, version=version, patch_update=patch_update, image_updates=image_updates)
        _validate_manifest_document(manifest)
        _reject_mutable_registry_image_refs(manifest)
        upload_manifest = _manifest_with_softmax_image_ids(client, manifest)
        response = client.upload_manifest(upload_manifest)

    return CoworldUploadResult(
        id=response.id,
        name=response.name,
        version=response.version,
        manifest_hash=response.manifest_hash,
        size_bytes=response.size_bytes,
        canonical=response.canonical,
    )


def _resolve_stored_coworld(client: CoworldUploadClient, coworld_ref: str) -> CoworldListEntry:
    if coworld_ref.startswith("cow_"):
        coworld = client.find_coworld(coworld_ref)
        if coworld is None:
            raise RuntimeError(f"Coworld not found: {coworld_ref}")
        return coworld
    coworld = client.find_canonical_coworld(coworld_ref)
    if coworld is None:
        raise RuntimeError(f"Canonical Coworld not found: {coworld_ref}")
    return coworld


def _validate_manifest_document(manifest: dict[str, object]) -> None:
    validate_json_schema(manifest, coworld_manifest_schema())
    typed_manifest = CoworldManifest.model_validate(manifest)
    validate_coworld_manifest_game_configs(typed_manifest)


def _apply_manifest_updates(
    manifest: dict[str, object],
    *,
    version: str | None,
    patch_update: str | None,
    image_updates: list[str] | None,
) -> None:
    if patch_update is not None:
        _merge_json_object(manifest, _load_manifest_patch(patch_update))
    if version is not None:
        game = manifest.get("game")
        if not isinstance(game, dict):
            raise ValueError("Manifest game field must be an object")
        game["version"] = version
    for update in image_updates or []:
        target, image = _parse_image_update(update)
        _set_manifest_image(manifest, target, image)


def _load_manifest_patch(patch_update: str) -> dict[str, object]:
    patch_text = patch_update
    if not patch_update.lstrip().startswith("{"):
        patch_text = Path(patch_update).read_text(encoding="utf-8")
    try:
        patch = json.loads(patch_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--patch must be a JSON object or path to a JSON object: {exc}") from exc
    if not isinstance(patch, dict):
        raise ValueError("--patch must be a JSON object")
    return patch


def _merge_json_object(target: dict[str, object], patch: dict[str, object]) -> None:
    for key, value in patch.items():
        if value is None:
            target.pop(key, None)
        elif isinstance(value, dict) and isinstance(target_value := target.get(key), dict):
            _merge_json_object(target_value, value)
        else:
            target[key] = copy.deepcopy(value)


def _parse_image_update(update: str) -> tuple[str, str]:
    target, separator, image = update.partition("=")
    if not separator or not target or not image:
        raise ValueError(f"Expected TARGET=IMAGE for --image, got: {update}")
    return target, image


def _set_manifest_image(manifest: dict[str, object], target: str, image: str) -> None:
    if target == "game":
        game = manifest.get("game")
        if not isinstance(game, dict):
            raise ValueError("Manifest game field must be an object")
        runnable = game.get("runnable")
        if not isinstance(runnable, dict):
            raise ValueError("Manifest game.runnable field must be an object")
        runnable["image"] = image
        return

    role, selector = _parse_image_target(target)
    entries = manifest.get(role)
    if not isinstance(entries, list):
        raise ValueError(f"Manifest role section is not a list: {role}")
    if selector is None:
        if len(entries) != 1:
            raise ValueError(f"--image {role}=... is ambiguous because {role} has {len(entries)} entries")
        entry = entries[0]
    elif selector.isdigit():
        index = int(selector)
        try:
            entry = entries[index]
        except IndexError as exc:
            raise ValueError(f"No {role} entry at index {index}") from exc
    else:
        matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("id") == selector]
        if len(matches) != 1:
            raise ValueError(f"No unique {role} entry with id {selector!r}")
        entry = matches[0]
    if not isinstance(entry, dict) or "image" not in entry:
        raise ValueError(f"Manifest target is not a runnable image field: {target}")
    entry["image"] = image


def _parse_image_target(target: str) -> tuple[str, str | None]:
    if target.endswith("]"):
        role, separator, index_text = target[:-1].partition("[")
        if separator and role in MANIFEST_ROLE_SECTIONS and index_text.isdigit():
            return role, index_text
    role, separator, selector = target.partition(".")
    if role not in MANIFEST_ROLE_SECTIONS:
        raise ValueError(f"Unknown image target role: {role}")
    return role, selector if separator else None


def _reject_mutable_registry_image_refs(manifest: dict[str, object]) -> None:
    mutable_refs = sorted(
        {
            image
            for image in (runnable["image"] for runnable in _manifest_image_fields(manifest))
            if is_mutable_registry_image_ref(image)
        }
    )
    if not mutable_refs:
        return
    refs = ", ".join(mutable_refs)
    raise RuntimeError(
        "Coworld manifest contains mutable registry image refs: "
        f"{refs}. Use `uv run coworld resolve-and-upload` to generate a digest-pinned manifest and upload that."
    )


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code == 401:
        raise RuntimeError("Authentication failed (401). Your token may be expired. Run: uv run softmax login")
    if response.status_code == 403:
        raise RuntimeError(
            f"Access denied (403) for {response.request.url.path}. "
            "You may lack permissions, or your token may be expired. Run: uv run softmax login"
        )
    if response.is_error:
        # httpx's raise_for_status() drops the response body, but the server puts the
        # actual error there (e.g. FastAPI's {"detail": ...}). Surface it so failures
        # are diagnosable instead of a bare status code.
        body = response.text.strip()
        message = (
            f"Request to {response.request.method} {response.request.url.path} failed with HTTP {response.status_code}"
        )
        raise RuntimeError(f"{message}: {body}" if body else message)


def _load_current_token(*, server_url: str) -> str | None:
    from softmax.auth import load_current_token  # noqa: PLC0415

    return load_current_token(server=server_url)


def upload_coworld_cmd(
    manifest_path: Path | None = None,
    *,
    base_coworld: str | None = None,
    server: str = DEFAULT_SUBMIT_SERVER,
    timeout_seconds: float = 60.0,
    version: str | None = None,
    patch_update: str | None = None,
    image_updates: list[str] | None = None,
) -> None:
    if base_coworld is not None:
        if manifest_path is not None:
            raise typer.BadParameter("MANIFEST_PATH cannot be combined with --from-coworld")
        result = upload_coworld_update(
            base_coworld,
            server=server,
            version=version,
            patch_update=patch_update,
            image_updates=image_updates,
        )
    else:
        if manifest_path is None:
            raise typer.BadParameter("MANIFEST_PATH is required unless --from-coworld is set")
        if version is not None or patch_update is not None or image_updates:
            raise typer.BadParameter("--version, --patch, and --image require --from-coworld")
        result = upload_coworld(
            manifest_path,
            server=server,
            timeout_seconds=timeout_seconds,
        )
    typer.echo(f"Upload complete: {result.name}:{result.version}")
    typer.echo(f"Coworld: {result.id}")
    typer.echo(f"Manifest hash: {result.manifest_hash}")
    typer.echo(f"Size: {result.size_bytes} bytes")
    typer.echo(f"Canonical: {'yes' if result.canonical else 'no'}")


def upload_policy_cmd(
    image: str,
    name: str,
    *,
    run: list[str] | None = None,
    secret_env: dict[str, str] | None = None,
    tags: dict[str, str] | None = None,
    server: str = DEFAULT_SUBMIT_SERVER,
) -> None:
    with CoworldUploadClient.from_login(server_url=server) as client:
        uploaded_image = _upload_container_image(client, image)
        result = client.complete_docker_image_policy(
            name=name,
            container_image_id=uploaded_image.id,
            run=run,
            secret_env=secret_env,
            tags=tags,
        )
    typer.echo(f"Upload complete: {result.name}:v{result.version}")


def download_coworld(
    coworld_ref: str,
    *,
    server: str = DEFAULT_SUBMIT_SERVER,
) -> CoworldUploadResponse:
    coworld_id = resolve_coworld_download_id(coworld_ref, server=server)

    with httpx.Client(base_url=f"{server.rstrip('/')}/observatory", timeout=30.0) as http_client:
        response = http_client.get(f"/v2/coworlds/{coworld_id}", timeout=120.0)
    response.raise_for_status()
    return CoworldUploadResponse.model_validate(response.json())


def resolve_coworld_download_id(
    coworld_ref: str,
    *,
    server: str = DEFAULT_SUBMIT_SERVER,
) -> str:
    if coworld_ref.startswith("cow_"):
        return coworld_ref

    with CoworldUploadClient.from_login(server_url=server) as client:
        coworld = client.find_canonical_coworld(coworld_ref)
    if coworld is None:
        raise RuntimeError(f"Canonical Coworld not found: {coworld_ref}")
    return coworld.id


def downloaded_coworld_manifest_path(output_dir: Path, coworld_id: str) -> Path:
    return output_dir / coworld_id / "coworld_manifest.json"


def downloaded_coworld_images_path(output_dir: Path, coworld_id: str) -> Path:
    return output_dir / coworld_id / "coworld_images.json"


def downloaded_coworld_exists(output_dir: Path, coworld_id: str) -> bool:
    return (
        downloaded_coworld_manifest_path(output_dir, coworld_id).is_file()
        and downloaded_coworld_images_path(output_dir, coworld_id).is_file()
    )


def download_coworld_cmd(
    coworld_ref: str,
    output_dir: Path,
    *,
    server: str = DEFAULT_SUBMIT_SERVER,
    refresh: bool = False,
) -> None:
    coworld_id = resolve_coworld_download_id(coworld_ref, server=server)
    manifest_path = downloaded_coworld_manifest_path(output_dir, coworld_id)
    image_map_path = downloaded_coworld_images_path(output_dir, coworld_id)
    if downloaded_coworld_exists(output_dir, coworld_id) and not refresh:
        typer.echo(f"Coworld already downloaded: {coworld_id}")
        agents_path = manifest_path.with_name("AGENTS.md")
        agents_path.write_text(DOWNLOAD_AGENTS_MD, encoding="utf-8")
        _print_download_paths(coworld_id, manifest_path, image_map_path, agents_path)
        return

    coworld = download_coworld(coworld_id, server=server)

    image_tags = _local_image_tags(coworld)
    for public_image_uri, local_tag in image_tags.items():
        pull_and_tag_image(public_image_uri, local_tag)

    (output_dir / coworld.id).mkdir(parents=True, exist_ok=True)
    manifest = _manifest_with_local_images(coworld.manifest, image_tags)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    image_map_path.write_text(
        json.dumps(
            {
                "coworld_id": coworld.id,
                "name": coworld.name,
                "version": coworld.version,
                "images": [
                    {
                        "public_image_uri": public_image_uri,
                        "local_image": local_tag,
                    }
                    for public_image_uri, local_tag in image_tags.items()
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    agents_path = manifest_path.with_name("AGENTS.md")
    agents_path.write_text(DOWNLOAD_AGENTS_MD, encoding="utf-8")

    typer.echo(f"Downloaded Coworld: {coworld.name}:{coworld.version}")
    _print_download_paths(coworld.id, manifest_path, image_map_path, agents_path)


def _print_download_paths(coworld_id: str, manifest_path: Path, image_map_path: Path, agents_path: Path) -> None:
    typer.echo(f"Coworld: {coworld_id}")
    typer.echo(f"Manifest: {manifest_path}")
    typer.echo(f"Images: {image_map_path}")
    typer.echo(f"Agent guide: {agents_path}")
    typer.echo(f"Play: {shlex.join(['uv', 'run', 'coworld', 'play', coworld_id])}")


def pull_and_tag_image(public_image_uri: str, local_tag: str) -> None:
    if public_image_uri.startswith("public.ecr.aws/"):
        with tempfile.TemporaryDirectory(prefix="coworld-docker-config-") as docker_config:
            subprocess.run(
                ["docker", "pull", public_image_uri],
                check=True,
                env={**os.environ, "DOCKER_CONFIG": docker_config},
            )
    else:
        subprocess.run(["docker", "pull", public_image_uri], check=True)
    subprocess.run(["docker", "tag", public_image_uri, local_tag], check=True)


def _manifest_with_softmax_image_ids(client: CoworldUploadClient, manifest: dict[str, object]) -> dict[str, object]:
    upload_manifest = copy.deepcopy(manifest)
    replacements = {
        image: _upload_container_image(client, image).id
        for image in sorted({runnable["image"] for runnable in _manifest_image_fields(upload_manifest)})
        if not _is_uploaded_image_id(image)
    }
    for runnable in _manifest_image_fields(upload_manifest):
        image = runnable["image"]
        if image in replacements:
            runnable["image"] = replacements[image]
    return upload_manifest


def _is_uploaded_image_id(image: str) -> bool:
    return _IMAGE_ID_RE.match(image) is not None


def _manifest_image_fields(value: object) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            fields.extend(_manifest_image_fields(item))
    if isinstance(value, dict):
        image = value.get("image")
        if image is not None:
            if not isinstance(image, str):
                raise TypeError("Coworld runnable image must be a string")
            fields.append(value)
        for item in value.values():
            fields.extend(_manifest_image_fields(item))
    return fields


def _local_image_tags(coworld: CoworldUploadResponse) -> dict[str, str]:
    images = sorted({runnable["image"] for runnable in _manifest_image_fields(coworld.manifest)})
    return {
        image: _local_image_tag(coworld.id, coworld.name, coworld.version, index) for index, image in enumerate(images)
    }


def _coworld_name_key(name: str) -> str:
    return name.replace("-", "_")


def _local_image_tag(coworld_id: str, coworld_name: str, coworld_version: str, index: int) -> str:
    coworld = _slug_for_local_image(coworld_id, "coworld")
    name = _slug_for_local_image(coworld_name, "coworld")
    version = _slug_for_local_image(coworld_version, "version")
    return f"coworld/{coworld}/{name}-{version}-{index}:downloaded"


def _slug_for_local_image(value: str, fallback: str) -> str:
    slug = _LOCAL_TAG_SEPARATOR_RE.sub("-", value.lower()).strip("._-")
    return slug or fallback


def _manifest_with_local_images(
    manifest: dict[str, Any],
    image_tags: dict[str, str],
) -> dict[str, Any]:
    local_manifest = copy.deepcopy(manifest)
    for runnable in _manifest_image_fields(local_manifest):
        image = runnable["image"]
        runnable["image"] = image_tags[image]
    return local_manifest


def _upload_container_image(client: CoworldUploadClient, image: str) -> ContainerImageResponse:
    client_hash = _local_image_client_hash(image)
    response = client.request_image_upload(name=_image_upload_name(image), client_hash=client_hash)

    if response.pre_signed_info is not None:
        _push_container_image(image, response.pre_signed_info)
        completed = client.complete_image_upload(response.image.id)
    else:
        completed = response.image

    return completed


def _local_image_client_hash(image: str) -> str:
    with tempfile.TemporaryFile() as archive:
        subprocess.run(["docker", "image", "save", image], check=True, stdout=archive)
        archive.seek(0)
        return _docker_archive_client_hash(archive, image=image)


def _docker_archive_client_hash(archive: Any, *, image: str | None = None) -> str:
    with tarfile.open(fileobj=archive, mode="r:*") as tar:
        manifest_json = _read_tar_member(tar, "manifest.json")
        manifest = json.loads(manifest_json)
        if not isinstance(manifest, list) or len(manifest) != 1:
            raise RuntimeError("Docker image archive must contain exactly one image manifest")
        image_manifest = manifest[0]
        if not isinstance(image_manifest, dict):
            raise RuntimeError("Docker image archive manifest entry must be an object")

        config_name = image_manifest["Config"]
        layers = image_manifest["Layers"]
        if not isinstance(config_name, str) or not isinstance(layers, list):
            raise RuntimeError("Docker image archive manifest has invalid config or layers")

        config_bytes = _read_tar_member(tar, config_name)
        config = json.loads(config_bytes)
        if not isinstance(config, dict):
            raise RuntimeError("Docker image archive config must be an object")
        os_name = config.get("os")
        architecture = config.get("architecture")
        if os_name != "linux" or architecture != "amd64":
            subject = f"Docker image {image}" if image is not None else "Docker image archive"
            raise RuntimeError(
                f"{subject} is {os_name or 'unknown'}/{architecture or 'unknown'}; "
                "hosted Coworld episodes require linux/amd64 images. "
                "Rebuild the image with: docker build --platform linux/amd64 ..."
            )

        layer_hashes = []
        for layer in layers:
            if not isinstance(layer, str):
                raise RuntimeError("Docker image archive manifest layers must be strings")
            layer_hashes.append(_sha256_digest(_read_tar_member(tar, layer)))

        content = {
            "config": _sha256_digest(config_bytes),
            "layers": layer_hashes,
        }
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    return _sha256_digest(encoded)


def _read_tar_member(tar: tarfile.TarFile, name: str) -> bytes:
    member = tar.extractfile(name)
    if member is None:
        raise RuntimeError(f"Docker image archive is missing {name}")
    return member.read()


def _sha256_digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


_logger = logging.getLogger(__name__)

# --- Direct registry push (workaround for moby/moby#51779) ---
#
# Docker 29 made the containerd image store the default. Its push implementation
# does a HEAD on /v2/<repo>/manifests/<tag> to check existence before pushing.
# ECR returns 403 (not 404) for non-existent manifests, which the containerd
# pusher treats as fatal. All layers upload fine; only the manifest tag fails.
#
# Rather than shelling out to `docker push`, we implement the OCI distribution
# spec directly via httpx: POST+PUT each blob, then PUT the manifest. This
# sidesteps the HEAD check entirely. Once Docker fixes this upstream, this code
# can be replaced with a simple `docker push` call again.

_DOCKER_MANIFEST_MEDIA_TYPE = "application/vnd.docker.distribution.manifest.v2+json"
_DOCKER_CONFIG_MEDIA_TYPE = "application/vnd.docker.container.image.v1+json"
_DOCKER_LAYER_MEDIA_TYPE = "application/vnd.docker.image.rootfs.diff.tar.gzip"
_REGISTRY_UPLOAD_TIMEOUT = httpx.Timeout(connect=600.0, read=600.0, write=3600.0, pool=600.0)


def _push_container_image(source_image: str, push_info: EcrPushInfo) -> None:
    auth_header = push_info.authorization_token
    if push_info.endpoint_url is not None:
        scheme = "http" if push_info.endpoint_url.startswith("http://") else "https"
    else:
        scheme = "https"
    # The registry may carry a path prefix (e.g. floci's "localhost:5100/<account>/<region>"
    # namespacing in local dev); the OCI /v2/ API root sits on the host, with the
    # prefix prepended to the repository path.
    host, _, prefix = push_info.registry.partition("/")
    repository = f"{prefix}/{push_info.repository}" if prefix else push_info.repository
    base_url = f"{scheme}://{host}/v2/{repository}"

    with tempfile.TemporaryFile() as archive:
        subprocess.run(["docker", "image", "save", source_image], check=True, stdout=archive)
        archive.seek(0)
        _push_archive_to_registry(archive, base_url, push_info.tag, auth_header)


def _push_archive_to_registry(archive: Any, base_url: str, tag: str, auth_header: str) -> None:
    """Push a docker-save tar archive to a registry via the OCI distribution API."""
    headers = {"Authorization": f"Basic {auth_header}"}

    with tarfile.open(fileobj=archive, mode="r|*") as tar:
        members: dict[str, bytes] = {}
        for member in tar:
            if member.isfile():
                data = tar.extractfile(member)
                if data is not None:
                    members[member.name] = data.read()

    manifest_json = members.get("manifest.json")
    if manifest_json is None:
        raise RuntimeError("Docker image archive is missing manifest.json")
    docker_manifest = json.loads(manifest_json)
    if not isinstance(docker_manifest, list) or len(docker_manifest) != 1:
        raise RuntimeError("Docker image archive must contain exactly one image manifest")
    entry = docker_manifest[0]

    config_name = entry["Config"]
    layer_names = entry["Layers"]
    config_bytes = members[config_name]

    with httpx.Client(timeout=_REGISTRY_UPLOAD_TIMEOUT) as client:
        layer_descriptors = []
        for layer_name in layer_names:
            layer_bytes = members[layer_name]
            descriptor = _push_blob(client, base_url, headers, layer_bytes, _DOCKER_LAYER_MEDIA_TYPE)
            layer_descriptors.append(descriptor)
            _logger.info("Pushed layer %s (%d bytes)", descriptor["digest"], descriptor["size"])

        config_descriptor = _push_blob(client, base_url, headers, config_bytes, _DOCKER_CONFIG_MEDIA_TYPE)
        _logger.info("Pushed config %s", config_descriptor["digest"])

        manifest = {
            "schemaVersion": 2,
            "mediaType": _DOCKER_MANIFEST_MEDIA_TYPE,
            "config": config_descriptor,
            "layers": layer_descriptors,
        }
        manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode()

        # PUT the manifest directly — no HEAD pre-check (which is what breaks docker push + ECR).
        resp = client.put(
            f"{base_url}/manifests/{tag}",
            content=manifest_bytes,
            headers=headers | {"Content-Type": _DOCKER_MANIFEST_MEDIA_TYPE},
        )
        resp.raise_for_status()
        _logger.info("Pushed manifest tagged %s", tag)


def _push_blob(
    client: httpx.Client, base_url: str, headers: dict[str, str], data: bytes, media_type: str
) -> dict[str, Any]:
    digest = _sha256_digest(data)

    resp = client.post(f"{base_url}/blobs/uploads/", headers=headers)
    resp.raise_for_status()
    upload_url = resp.headers["Location"]
    if not upload_url.startswith("http"):
        registry_origin = base_url.split("/v2/")[0]
        upload_url = registry_origin + upload_url

    sep = "&" if "?" in upload_url else "?"
    resp = client.put(
        f"{upload_url}{sep}digest={digest}",
        content=data,
        headers=headers | {"Content-Type": "application/octet-stream"},
    )
    resp.raise_for_status()

    return {"mediaType": media_type, "digest": digest, "size": len(data)}


def _image_upload_name(image: str) -> str:
    name = image.rsplit("/", 1)[-1].split("@", 1)[0].split(":", 1)[0]
    return name or "coworld-image"
