from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Self
from urllib.parse import quote
from uuid import UUID

import httpx
import typer
from pydantic import BaseModel

from coworld.bundle import resolve_registry_image_ref
from coworld.certifier import EXECUTABLE_TRANSCRIPT_PATH, certify_coworld, load_coworld_package
from coworld.cli_support import validate_run_argv
from coworld.config import DEFAULT_SUBMIT_SERVER
from coworld.image_refs import is_digest_pinned_image_ref, is_mutable_registry_image_ref
from coworld.manifest_validation import validate_coworld_manifest_game_configs
from coworld.runner.runner import assert_docker_image_reachable
from coworld.schema_validation import validate_json_schema
from coworld.types import MANIFEST_ROLE_SECTIONS, CoworldManifest, coworld_manifest_schema

_LOCAL_TAG_SEPARATOR_RE = re.compile(r"[^a-z0-9._-]+")
_IMAGE_ID_RE = re.compile(r"^img_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_HOSTED_SMOKE_TERMINAL_STATUSES = {"completed", "failed", "canceled", "cancelled"}
_HOSTED_SMOKE_SUCCESS_STATUSES = {"completed"}
# Matches SMOKE_TEST_EPISODE_TAGS["source"] on the backend: scopes hosted-smoke
# polling to upload-smoke episodes so user/XP/tournament requests for the same
# coworld can't masquerade as smoke results.
_HOSTED_SMOKE_EPISODE_SOURCE = "coworld_upload"
_CERTIFICATION_CACHE_VERSION = "coworld-certification-v1"
_PACKAGE_ROOT = Path(__file__).parent
_DOCKER_AUTH_CONFIG_KEYS = {"auths", "credsStore", "credHelpers"}
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


class CoworldCertificationFailure(BaseModel):
    kind: str
    detail: str
    remediation: str
    retryable: bool


class CoworldCertificationStepSummary(BaseModel):
    id: str
    status: str


class CoworldCertificationStatus(BaseModel):
    """Response of GET /v2/coworlds/{id}/certification (spec 0062)."""

    coworld_id: str
    state: str  # never_run | queued | certifying | certified | failed
    certified: bool
    contract_version: str | None = None
    certification_job_id: str | None = None
    failed_step: str | None = None
    failure: CoworldCertificationFailure | None = None
    transcript_summary: list[CoworldCertificationStepSummary] = []
    completed_at: datetime | None = None


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


class CoworldSecretResponse(BaseModel):
    coworld_id: str
    coworld_name: str
    owner_user_id: str
    secret_name: str
    size_bytes: int
    updated_at: datetime | None = None


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


class ReporterVersionResponse(BaseModel):
    id: str
    name: str
    version: int
    content_hash: str


class ReporterRegisterResponse(BaseModel):
    id: str
    name: str
    user_id: str
    created: bool
    # Issued and shown once on create; None when register updated an existing reporter.
    reporter_key: str | None = None


class ReporterUploadResponse(BaseModel):
    upload_url: str | None = None
    existing_version: ReporterVersionResponse | None = None


class ReporterUploadCompleteResponse(BaseModel):
    version: ReporterVersionResponse


class WhoAmIResponse(BaseModel):
    # The authenticated user's id; for player-subject tokens, the owning user's id.
    owner_user_id: str | None = None


@dataclass(frozen=True)
class CoworldUploadResult:
    id: str
    name: str
    version: str
    manifest_hash: str
    size_bytes: int
    canonical: bool
    hosted_smoke_episode_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class HostedSmokeEpisodeStatus:
    id: str
    status: str
    error: str | None = None

    def model_dump(self) -> dict[str, str | None]:
        return {"id": self.id, "status": self.status, "error": self.error}


@dataclass(frozen=True)
class CoworldStatusResult:
    coworld: CoworldUploadResponse
    hosted_smoke_episodes: tuple[HostedSmokeEpisodeStatus, ...]
    certification: CoworldCertificationStatus | None = None

    @property
    def hosted_smoke_episode_ids(self) -> tuple[str, ...]:
        return tuple(episode.id for episode in self.hosted_smoke_episodes)

    @property
    def hosted_smoke_failed(self) -> bool:
        return any(
            episode.status in _HOSTED_SMOKE_TERMINAL_STATUSES - _HOSTED_SMOKE_SUCCESS_STATUSES
            for episode in self.hosted_smoke_episodes
        )

    @property
    def hosted_smoke_pending(self) -> bool:
        return any(episode.status not in _HOSTED_SMOKE_TERMINAL_STATUSES for episode in self.hosted_smoke_episodes)

    @property
    def hosted_smoke_passed(self) -> bool:
        return bool(self.hosted_smoke_episodes) and not self.hosted_smoke_failed and not self.hosted_smoke_pending


class CoworldUploadClient:
    # Process-scoped elevation flag, set by the top-level `coworld --elevated` Typer
    # callback so every upload/manage command in this invocation carries the header.
    # Kept as a class attribute mirroring CoworldApiClient — the two clients are used
    # side by side and must not diverge on elevation state.
    _elevated = False

    def __init__(self, server_url: str, token: str):
        self._http_client = httpx.Client(base_url=f"{server_url.rstrip('/')}/observatory", timeout=30.0)
        self._token = token

    @classmethod
    def set_elevated(cls, elevated: bool) -> None:
        cls._elevated = elevated

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
        headers = {"Authorization": f"Bearer {self._token}"}
        if type(self)._elevated:
            if self._token.startswith("ply_"):
                raise RuntimeError(
                    "--elevated cannot be used with a player-subject token. Player sessions "
                    "are not eligible for Softmax team access. Run `softmax player unset` to "
                    "revert to your user credential, or omit --elevated."
                )
            headers["X-Use-Elevated-Privileges"] = "true"
        return headers

    def upload_manifest(self, manifest: dict[str, object]) -> CoworldUploadResponse:
        response = self._http_client.post(
            "/v2/coworlds/upload",
            headers=self._headers(),
            json={"manifest": manifest},
            timeout=120.0,
        )
        _raise_for_status(response)
        return CoworldUploadResponse.model_validate(response.json())

    def register_reporter(
        self, *, name: str, display_name: str, description: str, outputs: list[dict[str, Any]]
    ) -> ReporterRegisterResponse:
        response = self._http_client.post(
            "/v2/reporters/register",
            headers=self._headers(),
            json={"name": name, "display_name": display_name, "description": description, "outputs": outputs},
            timeout=60.0,
        )
        _raise_for_status(response)
        return ReporterRegisterResponse.model_validate(response.json())

    def request_reporter_upload(
        self, *, name: str, content_hash: str, size_bytes: int, attributes: dict[str, Any]
    ) -> ReporterUploadResponse:
        response = self._http_client.post(
            "/v2/reporters/upload",
            headers=self._headers(),
            json={"name": name, "content_hash": content_hash, "size_bytes": size_bytes, "attributes": attributes},
            timeout=60.0,
        )
        _raise_for_status(response)
        return ReporterUploadResponse.model_validate(response.json())

    def complete_reporter_upload(
        self, *, name: str, content_hash: str, attributes: dict[str, Any]
    ) -> ReporterUploadCompleteResponse:
        response = self._http_client.post(
            "/v2/reporters/upload/complete",
            headers=self._headers(),
            json={"name": name, "content_hash": content_hash, "attributes": attributes},
            timeout=300.0,
        )
        _raise_for_status(response)
        return ReporterUploadCompleteResponse.model_validate(response.json())

    def whoami(self) -> WhoAmIResponse:
        response = self._http_client.get("/whoami", headers=self._headers(), timeout=30.0)
        _raise_for_status(response)
        return WhoAmIResponse.model_validate(response.json())

    def patch_commissioner(
        self,
        *,
        coworld_name: str,
        container_image_id: str,
        runnable_id: str | None = None,
        version: str | None = None,
    ) -> CoworldUploadResponse:
        payload: dict[str, Any] = {
            "coworld_name": coworld_name,
            "container_image_id": container_image_id,
        }
        if runnable_id is not None:
            payload["runnable_id"] = runnable_id
        if version is not None:
            payload["version"] = version
        response = self._http_client.post(
            "/v2/coworlds/patch-commissioner",
            headers=self._headers(),
            json=payload,
            timeout=120.0,
        )
        _raise_for_status(response)
        return CoworldUploadResponse.model_validate(response.json())

    def list_episode_requests(
        self,
        *,
        coworld_id: str | None = None,
        source: str | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params: dict[str, str | int] = {"limit": limit, "offset": offset}
        if coworld_id is not None:
            params["coworld_id"] = coworld_id
        if source is not None:
            params["source"] = source
        response = self._http_client.get(
            "/v2/episode-requests",
            headers=self._headers(),
            params=params,
            timeout=60.0,
        )
        _raise_for_status(response)
        page = response.json()
        if isinstance(page, dict) and isinstance(page.get("entries"), list):
            return page["entries"]
        if isinstance(page, list):
            return page
        raise RuntimeError("Unexpected episode request list response from server.")

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

    def get_coworld(self, coworld_id: str) -> CoworldUploadResponse:
        response = self._http_client.get(
            f"/v2/coworlds/{coworld_id}",
            headers=self._headers(),
            timeout=120.0,
        )
        _raise_for_status(response)
        return CoworldUploadResponse.model_validate(response.json())

    def get_coworld_certification(self, coworld_id: str) -> CoworldCertificationStatus:
        response = self._http_client.get(
            f"/v2/coworlds/{coworld_id}/certification",
            headers=self._headers(),
            timeout=60.0,
        )
        _raise_for_status(response)
        return CoworldCertificationStatus.model_validate(response.json())

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
        preferences: dict[str, Any] | None = None,
    ) -> LeagueSubmissionResponse:
        payload: dict[str, Any] = {
            "league_id": league_id,
            "policy_version_id": str(policy_version_id),
            "auto_champion": auto_champion.value,
        }
        if preferences is not None:
            payload["preferences"] = preferences
        response = self._http_client.post(
            "/v2/league-submissions",
            headers=self._headers(),
            json=payload,
            timeout=120.0,
        )
        _raise_for_status(response)
        return LeagueSubmissionResponse.model_validate(response.json())

    def create_league_seed(
        self,
        *,
        coworld_name: str,
        template: str = "commissioner_driven",
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

    def put_coworld_secret(
        self,
        *,
        coworld_name: str,
        secret_name: str,
        body: bytes,
    ) -> CoworldSecretResponse:
        response = self._http_client.put(
            f"/v2/coworlds/secrets/{quote(coworld_name, safe='')}/{quote(secret_name, safe='')}",
            headers={**self._headers(), "Content-Type": "application/octet-stream"},
            content=body,
            timeout=120.0,
        )
        _raise_for_status(response)
        return CoworldSecretResponse.model_validate(response.json())

    def list_coworld_secrets(self, *, coworld_name: str) -> list[CoworldSecretResponse]:
        response = self._http_client.get(
            f"/v2/coworlds/secrets/{quote(coworld_name, safe='')}",
            headers=self._headers(),
            timeout=60.0,
        )
        _raise_for_status(response)
        return [CoworldSecretResponse.model_validate(item) for item in response.json()]

    def delete_coworld_secret(self, *, coworld_name: str, secret_name: str) -> CoworldSecretResponse:
        response = self._http_client.delete(
            f"/v2/coworlds/secrets/{quote(coworld_name, safe='')}/{quote(secret_name, safe='')}",
            headers=self._headers(),
            timeout=120.0,
        )
        _raise_for_status(response)
        return CoworldSecretResponse.model_validate(response.json())

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
        policy_secret_env_id: str | None = None
        if secret_env:
            secret_response = self._http_client.post(
                "/stats/policy-secret-envs",
                headers=self._headers(),
                json={"policy_secret_env": secret_env},
                timeout=120.0,
            )
            _raise_for_status(secret_response)
            policy_secret_env_id = secret_response.json()["id"]

        payload: dict[str, Any] = {"name": name, "container_image_id": container_image_id}
        if run:
            payload["run"] = run
        if policy_secret_env_id is not None:
            payload["policy_secret_env_id"] = policy_secret_env_id
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


def _humanize_reporter_id(reporter_id: str) -> str:
    """Fallback display title from a reporter id: 'round-recap' -> 'Round Recap'."""
    return re.sub(r"[-_]+", " ", reporter_id).strip().title()


def _submit_wasm_reporters(client: CoworldUploadClient, manifest: dict[str, Any], package_root: Path) -> dict[str, Any]:
    """Submit wasm reporter references and rewrite them to platform references (spec 0061).

    Every reporter a hosted manifest carries is an owner-qualified platform
    reference: for each `{"wasm": ..., "id": ..., "attributes": ...}` entry, first
    register the reporter identity (POST /v2/reporters/register — an idempotent
    upsert that creates a new name or refreshes an existing one's title,
    description, and outputs contract), then upload the component through the
    standard flow (full static validation runs server-side; identical
    bytes+attributes dedupe to the existing version). Registration happens under
    the name `{game-name}-{id}` (reporter names cannot contain "/", the owner
    separator); the entry is replaced with `{"reporter": "owner/name@version"}`,
    where owner is the submitter's user id from `/whoami`.
    """
    references = list(manifest.get("reporter") or [])
    if not any("wasm" in reference for reference in references):
        return manifest
    owner_user_id = client.whoami().owner_user_id
    if owner_user_id is None:
        raise RuntimeError("Could not resolve your user id from /whoami. Run: uv run softmax login")
    game_name = manifest["game"]["name"]
    rewritten: list[dict[str, Any]] = []
    for reference in references:
        if "reporter" in reference:
            rewritten.append(reference)
            continue
        wasm_path = (package_root / reference["wasm"]).resolve()
        wasm_bytes = wasm_path.read_bytes()
        content_hash = hashlib.sha256(wasm_bytes).hexdigest()
        name = f"{game_name}-{reference['id']}"
        attributes = reference["attributes"]
        client.register_reporter(
            name=name,
            display_name=reference.get("display_name") or _humanize_reporter_id(reference["id"]),
            description=reference.get("description") or attributes["purpose"],
            outputs=attributes["outputs"],
        )
        upload = client.request_reporter_upload(
            name=name, content_hash=content_hash, size_bytes=len(wasm_bytes), attributes=attributes
        )
        if upload.existing_version is not None:
            version = upload.existing_version
        else:
            assert upload.upload_url is not None
            put_response = httpx.put(upload.upload_url, content=wasm_bytes, timeout=600.0)
            put_response.raise_for_status()
            version = client.complete_reporter_upload(
                name=name, content_hash=content_hash, attributes=attributes
            ).version
        _logger.info("Reporter %s submitted as %s@%s (%s)", reference["id"], name, version.version, content_hash[:12])
        rewritten.append({"reporter": f"{owner_user_id}/{name}@{version.version}"})
    return {**manifest, "reporter": rewritten}


def upload_coworld(
    manifest_path: Path,
    *,
    server: str = DEFAULT_SUBMIT_SERVER,
    timeout_seconds: float = 60.0,
    wait_for_hosted_smoke: bool = False,
    hosted_smoke_timeout_seconds: float = 1800.0,
    hosted_smoke_poll_seconds: float = 5.0,
) -> CoworldUploadResult:
    package = load_coworld_package(manifest_path)
    manifest = package.manifest.model_dump(by_alias=True, exclude_none=True)
    _reject_mutable_registry_image_refs(manifest)

    certification_key = _certification_cache_key(package.manifest_path, manifest=manifest)
    certification_cache_path = _certified_manifest_cache_path()
    certified_manifests = _load_string_cache(certification_cache_path)
    if certification_key not in certified_manifests:
        certify_coworld(package.manifest_path, timeout_seconds=timeout_seconds)
        cache_certified_manifest(package.manifest_path, cache_key=certification_key)

    with CoworldUploadClient.from_login(server_url=server) as client:
        upload_manifest = _manifest_with_softmax_image_ids(client, manifest)
        upload_manifest = _submit_wasm_reporters(client, upload_manifest, manifest_path.parent)
        response = client.upload_manifest(upload_manifest)
        if wait_for_hosted_smoke:
            status = get_coworld_status(
                client,
                coworld_id=response.id,
                wait_for_hosted_smoke=True,
                timeout_seconds=hosted_smoke_timeout_seconds,
                poll_seconds=hosted_smoke_poll_seconds,
            )
            response = status.coworld
            hosted_smoke_episode_ids = status.hosted_smoke_episode_ids
        else:
            hosted_smoke_episode_ids = ()

    return CoworldUploadResult(
        id=response.id,
        name=response.name,
        version=response.version,
        manifest_hash=response.manifest_hash,
        size_bytes=response.size_bytes,
        canonical=response.canonical,
        hosted_smoke_episode_ids=hosted_smoke_episode_ids,
    )


def upload_coworld_update(
    coworld_ref: str,
    *,
    server: str = DEFAULT_SUBMIT_SERVER,
    version: str | None = None,
    patch_update: str | None = None,
    image_updates: list[str] | None = None,
    wait_for_hosted_smoke: bool = False,
    hosted_smoke_timeout_seconds: float = 1800.0,
    hosted_smoke_poll_seconds: float = 5.0,
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
        if wait_for_hosted_smoke:
            status = get_coworld_status(
                client,
                coworld_id=response.id,
                wait_for_hosted_smoke=True,
                timeout_seconds=hosted_smoke_timeout_seconds,
                poll_seconds=hosted_smoke_poll_seconds,
            )
            response = status.coworld
            hosted_smoke_episode_ids = status.hosted_smoke_episode_ids
        else:
            hosted_smoke_episode_ids = ()

    return CoworldUploadResult(
        id=response.id,
        name=response.name,
        version=response.version,
        manifest_hash=response.manifest_hash,
        size_bytes=response.size_bytes,
        canonical=response.canonical,
        hosted_smoke_episode_ids=hosted_smoke_episode_ids,
    )


def coworld_status(
    coworld_id: str,
    *,
    server: str = DEFAULT_SUBMIT_SERVER,
    wait_for_hosted_smoke: bool = False,
    timeout_seconds: float = 1800.0,
    poll_seconds: float = 5.0,
) -> CoworldStatusResult:
    with CoworldUploadClient.from_login(server_url=server) as client:
        return get_coworld_status(
            client,
            coworld_id=coworld_id,
            wait_for_hosted_smoke=wait_for_hosted_smoke,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )


def get_coworld_status(
    client: CoworldUploadClient,
    *,
    coworld_id: str,
    wait_for_hosted_smoke: bool = False,
    timeout_seconds: float = 1800.0,
    poll_seconds: float = 5.0,
) -> CoworldStatusResult:
    if wait_for_hosted_smoke:
        hosted_smoke_episodes = wait_for_hosted_smoke_certification(
            client,
            coworld_id=coworld_id,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )
    else:
        hosted_smoke_episodes = get_hosted_smoke_episode_statuses(client, coworld_id=coworld_id)
    return CoworldStatusResult(
        coworld=client.get_coworld(coworld_id),
        hosted_smoke_episodes=hosted_smoke_episodes,
        certification=client.get_coworld_certification(coworld_id),
    )


def wait_for_upload_certification(
    client: CoworldUploadClient,
    *,
    coworld_id: str,
    timeout_seconds: float,
    poll_seconds: float = 5.0,
    on_step: Any = None,
) -> CoworldCertificationStatus:
    """Poll the hosted certification status until it reaches a terminal state.

    ``on_step`` receives each (step_id, status) transition once, in transcript order,
    so callers can stream progress. Raises TimeoutError when the window expires; a
    `never_run` state is not terminal (the auto-queue background task may not have
    landed yet) and keeps polling.
    """
    deadline = time.monotonic() + timeout_seconds
    reported: dict[str, str] = {}
    while True:
        status = client.get_coworld_certification(coworld_id)
        if on_step is not None:
            for step in status.transcript_summary:
                if reported.get(step.id) != step.status:
                    reported[step.id] = step.status
                    on_step(step.id, step.status)
        if status.state in ("certified", "failed"):
            return status
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Timed out waiting for hosted certification of Coworld {coworld_id} (state: {status.state})"
            )
        time.sleep(poll_seconds)


def get_hosted_smoke_episode_statuses(
    client: CoworldUploadClient,
    *,
    coworld_id: str,
) -> tuple[HostedSmokeEpisodeStatus, ...]:
    return _hosted_smoke_episode_statuses_from_rows(
        client.list_episode_requests(coworld_id=coworld_id, source=_HOSTED_SMOKE_EPISODE_SOURCE, limit=1000),
        coworld_id=coworld_id,
    )


def wait_for_hosted_smoke_certification(
    client: CoworldUploadClient,
    *,
    coworld_id: str,
    timeout_seconds: float,
    poll_seconds: float,
) -> tuple[HostedSmokeEpisodeStatus, ...]:
    deadline = time.monotonic() + timeout_seconds
    seen: dict[str, HostedSmokeEpisodeStatus] = {}

    while True:
        for episode in get_hosted_smoke_episode_statuses(client, coworld_id=coworld_id):
            seen[episode.id] = episode

        if seen:
            pending = [episode for episode in seen.values() if episode.status not in _HOSTED_SMOKE_TERMINAL_STATUSES]
            failures = [
                episode
                for episode in seen.values()
                if episode.status in _HOSTED_SMOKE_TERMINAL_STATUSES - _HOSTED_SMOKE_SUCCESS_STATUSES
            ]
            if failures:
                raise RuntimeError(_hosted_smoke_failure_message(coworld_id, failures))
            if not pending:
                return tuple(seen[episode_id] for episode_id in sorted(seen))

        if time.monotonic() >= deadline:
            if not seen:
                raise RuntimeError(
                    f"Timed out waiting for hosted smoke certification episodes to be created for Coworld {coworld_id}."
                )
            raise RuntimeError(_hosted_smoke_timeout_message(coworld_id, seen.values()))
        time.sleep(poll_seconds)


def _hosted_smoke_episode_statuses_from_rows(
    rows: list[dict[str, Any]],
    *,
    coworld_id: str,
) -> tuple[HostedSmokeEpisodeStatus, ...]:
    episodes: dict[str, HostedSmokeEpisodeStatus] = {}
    for row in rows:
        if row.get("coworld_id") != coworld_id:
            continue
        episode_id = row.get("id")
        if not isinstance(episode_id, str):
            continue
        error = row.get("error") or row.get("error_type")
        episodes[episode_id] = HostedSmokeEpisodeStatus(
            id=episode_id,
            status=str(row.get("status")),
            error=str(error) if error else None,
        )
    return tuple(episodes[episode_id] for episode_id in sorted(episodes))


def _hosted_smoke_failure_message(coworld_id: str, failures: list[HostedSmokeEpisodeStatus]) -> str:
    details = []
    for episode in failures:
        details.append(f"{episode.id} status={episode.status} error={episode.error or 'unknown error'}")
    return f"Hosted smoke certification failed for Coworld {coworld_id}:\n- " + "\n- ".join(details)


def _hosted_smoke_timeout_message(coworld_id: str, rows: Any) -> str:
    details = [f"{episode.id} status={episode.status}" for episode in rows]
    return f"Timed out waiting for hosted smoke certification for Coworld {coworld_id}:\n- " + "\n- ".join(details)


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
    wait_for_hosted_smoke: bool = True,
    hosted_smoke_timeout_seconds: float = 1800.0,
    hosted_smoke_poll_seconds: float = 5.0,
    wait_certification: bool = False,
    certification_timeout_seconds: float = 1800.0,
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
            wait_for_hosted_smoke=wait_for_hosted_smoke,
            hosted_smoke_timeout_seconds=hosted_smoke_timeout_seconds,
            hosted_smoke_poll_seconds=hosted_smoke_poll_seconds,
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
            wait_for_hosted_smoke=wait_for_hosted_smoke,
            hosted_smoke_timeout_seconds=hosted_smoke_timeout_seconds,
            hosted_smoke_poll_seconds=hosted_smoke_poll_seconds,
        )
    if wait_for_hosted_smoke:
        typer.echo("Hosted smoke certification: passed")
        if result.hosted_smoke_episode_ids:
            typer.echo("Hosted smoke episodes: " + ", ".join(result.hosted_smoke_episode_ids))
    typer.echo(f"Upload complete: {result.name}:{result.version}")
    typer.echo(f"Coworld: {result.id}")
    typer.echo(f"Manifest hash: {result.manifest_hash}")
    typer.echo(f"Size: {result.size_bytes} bytes")
    typer.echo(f"Canonical: {'yes' if result.canonical else 'no'}")

    # Hosted certification is observational (spec 0062): the upload already succeeded,
    # so by default just report that it was queued and where to watch it.
    with CoworldUploadClient.from_login(server_url=server) as client:
        if not wait_certification:
            state = client.get_coworld_certification(result.id).state
            if state == "never_run":
                state = "not queued (no current certifier registered)"
            typer.echo(f"Hosted certification: {state}")
            typer.echo(f"Status: uv run coworld status {result.id}")
            return
        typer.echo("Hosted certification:")
        try:
            certification = wait_for_upload_certification(
                client,
                coworld_id=result.id,
                timeout_seconds=certification_timeout_seconds,
                on_step=lambda step_id, status: typer.echo(f"  {status:<4}  {step_id}"),
            )
        except TimeoutError as exc:
            # The upload already succeeded; a wait timeout is a platform-side outcome (exit 3).
            typer.echo(f"Hosted certification: {exc}")
            typer.echo(f"Status: uv run coworld status {result.id}")
            raise typer.Exit(code=3) from exc
    if certification.state == "certified":
        typer.echo("Hosted certification: passed")
        return
    typer.echo("Hosted certification: failed")
    if certification.failed_step is not None:
        typer.echo(f"Failed step: {certification.failed_step}")
    if certification.failure is not None:
        typer.echo(f"Reason: {certification.failure.detail}")
        typer.echo(f"Fix: {certification.failure.remediation}")
        raise typer.Exit(code=3 if certification.failure.retryable else 2)
    raise typer.Exit(code=2)


def upload_policy_cmd(
    image: str,
    name: str,
    *,
    run: list[str] | None = None,
    secret_env: dict[str, str] | None = None,
    tags: dict[str, str] | None = None,
    server: str = DEFAULT_SUBMIT_SERVER,
) -> None:
    validate_run_argv(run)
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


def patch_commissioner_cmd(
    coworld_name: str,
    image: str,
    *,
    runnable_id: str | None = None,
    version: str | None = None,
    server: str = DEFAULT_SUBMIT_SERVER,
) -> None:
    upload_image = _resolve_commissioner_patch_image(image)
    _ensure_local_image(upload_image)
    with CoworldUploadClient.from_login(server_url=server) as client:
        uploaded_image = _upload_container_image(client, upload_image)
        result = client.patch_commissioner(
            coworld_name=coworld_name,
            container_image_id=uploaded_image.id,
            runnable_id=runnable_id,
            version=version,
        )
    if upload_image != image:
        typer.echo(f"Resolved image: {upload_image}")
    typer.echo(f"Patched commissioner: {result.name}:{result.version}")
    typer.echo(f"Coworld: {result.id}")
    typer.echo(f"Commissioner image: {uploaded_image.id}")
    typer.echo(f"Canonical: {'yes' if result.canonical else 'no'}")


def _resolve_commissioner_patch_image(image: str) -> str:
    if not is_mutable_registry_image_ref(image):
        return image
    return resolve_registry_image_ref(image)


def _ensure_local_image(image: str) -> None:
    inspect_result = subprocess.run(["docker", "image", "inspect", image], capture_output=True, text=True)
    if inspect_result.returncode == 0:
        assert_docker_image_reachable(image, require_linux_amd64=True)
        return
    subprocess.run(["docker", "pull", image], check=True)
    assert_docker_image_reachable(image, require_linux_amd64=True)


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
    assert_docker_image_reachable(image, require_linux_amd64=True)
    client_hash = _local_image_client_hash(image)
    response = client.request_image_upload(name=_image_upload_name(image), client_hash=client_hash)

    if response.pre_signed_info is not None:
        _push_container_image(image, response.pre_signed_info)
        completed = client.complete_image_upload(response.image.id)
    else:
        completed = response.image

    return completed


def _local_image_client_hash(image: str) -> str:
    image_id = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    # Docker image IDs are content-addressed config digests whose rootfs diff IDs
    # cover every layer. They are therefore already the stable local content key
    # this endpoint needs; saving and rereading a multi-gigabyte image to derive a
    # second hash only delays the upload.
    return image_id


def _certified_manifest_cache_path() -> Path:
    return _coworld_cache_path("certified_manifest_hashes.json")


def _coworld_cache_path(filename: str) -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return base / "coworld" / filename


def _certification_cache_key(manifest_path: Path, *, manifest: dict[str, object] | None = None) -> str:
    manifest_data = manifest if manifest is not None else json.loads(manifest_path.read_text(encoding="utf-8"))
    key = {
        "cache_version": _CERTIFICATION_CACHE_VERSION,
        "certifier_code": _certification_code_digest(),
        "manifest": _sha256_digest(manifest_path.read_bytes()),
        "transcript": _sha256_digest(EXECUTABLE_TRANSCRIPT_PATH.read_bytes()),
        "local_images": _certification_local_image_hashes(manifest_data),
    }
    return _sha256_digest(json.dumps(key, sort_keys=True, separators=(",", ":")).encode())


def cache_certified_manifest(
    manifest_path: Path,
    *,
    manifest: dict[str, object] | None = None,
    cache_key: str | None = None,
) -> None:
    cache_path = _certified_manifest_cache_path()
    cache = _load_string_cache(cache_path)
    cache[cache_key or _certification_cache_key(manifest_path, manifest=manifest)] = "certified"
    _write_string_cache(cache_path, cache)


def _certification_code_digest() -> str:
    # Certification behavior lives in code, not just the transcript, and the certifier
    # delegates across the package (report validation, runner helpers, schema files) —
    # hash every source and schema file under the package root so any release that
    # changes certification behavior invalidates cached certifications. Source hashing
    # (vs package version) also invalidates for editable installs and works under
    # bazel, where coworld is not an installed distribution. examples/ is excluded:
    # certification never imports it, and it is a third of the package by bytes, so
    # example churn would spuriously re-certify every manifest.
    hasher = hashlib.sha256()
    for source_path in sorted(_PACKAGE_ROOT.rglob("*")):
        relative = source_path.relative_to(_PACKAGE_ROOT)
        if relative.parts[0] == "examples":
            continue
        if source_path.suffix not in (".py", ".json") or not source_path.is_file():
            continue
        # Length-prefixed frames: without them, moving bytes across a path/content or
        # file/file boundary could alias two different trees to the same digest.
        path_bytes = relative.as_posix().encode()
        content = source_path.read_bytes()
        hasher.update(len(path_bytes).to_bytes(8, "big"))
        hasher.update(path_bytes)
        hasher.update(len(content).to_bytes(8, "big"))
        hasher.update(content)
    return f"sha256:{hasher.hexdigest()}"


def _certification_local_image_hashes(manifest: dict[str, object]) -> dict[str, str]:
    images = sorted({runnable["image"] for runnable in _manifest_image_fields(manifest)})
    return {
        image: _local_image_client_hash(image)
        for image in images
        if not _is_uploaded_image_id(image) and not is_digest_pinned_image_ref(image)
    }


def _load_string_cache(cache_path: Path) -> dict[str, str]:
    if not cache_path.is_file():
        return {}
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    # ValueError covers every decode/parse corruption mode (UnicodeDecodeError and
    # json.JSONDecodeError are both subclasses); a corrupt best-effort cache is a miss.
    except (OSError, ValueError):
        return {}
    if not isinstance(cache, dict):
        return {}
    return {key: value for key, value in cache.items() if isinstance(value, str)}


def _write_string_cache(cache_path: Path, cache: dict[str, str]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(prefix=f".{cache_path.name}.", suffix=".tmp", dir=cache_path.parent)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_file:
            json.dump(cache, tmp_file, indent=2, sort_keys=True)
            tmp_file.write("\n")
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_name, cache_path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


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

    with tarfile.open(fileobj=archive, mode="r:*") as tar, httpx.Client(timeout=_REGISTRY_UPLOAD_TIMEOUT) as client:
        manifest_file = tar.extractfile("manifest.json")
        if manifest_file is None:
            raise RuntimeError("Docker image archive is missing manifest.json")
        docker_manifest = json.load(manifest_file)
        if not isinstance(docker_manifest, list) or len(docker_manifest) != 1:
            raise RuntimeError("Docker image archive must contain exactly one image manifest")
        entry = docker_manifest[0]
        if not isinstance(entry, dict):
            raise RuntimeError("Docker image archive manifest entry must be an object")

        config_name = entry["Config"]
        layer_names = entry["Layers"]
        if not isinstance(config_name, str) or not isinstance(layer_names, list):
            raise RuntimeError("Docker image archive has invalid config or layers")
        config_file = tar.extractfile(config_name)
        if config_file is None:
            raise RuntimeError(f"Docker image archive is missing {config_name}")
        config_bytes = config_file.read()

        layer_descriptors = []
        for layer_name in layer_names:
            if not isinstance(layer_name, str):
                raise RuntimeError("Docker image archive manifest layers must be strings")
            layer = tar.getmember(layer_name)
            layer_file = tar.extractfile(layer)
            if layer_file is None:
                raise RuntimeError(f"Docker image archive is missing {layer_name}")
            descriptor = _push_streaming_blob(
                client,
                base_url,
                headers,
                layer_file,
                size=layer.size,
                media_type=_DOCKER_LAYER_MEDIA_TYPE,
            )
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
    upload_url = _absolute_registry_upload_url(base_url, resp.headers["Location"])

    sep = "&" if "?" in upload_url else "?"
    resp = client.put(
        f"{upload_url}{sep}digest={digest}",
        content=data,
        headers=headers | {"Content-Type": "application/octet-stream"},
    )
    resp.raise_for_status()

    return {"mediaType": media_type, "digest": digest, "size": len(data)}


def _push_streaming_blob(
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    data: Any,
    *,
    size: int,
    media_type: str,
) -> dict[str, Any]:
    resp = client.post(f"{base_url}/blobs/uploads/", headers=headers)
    resp.raise_for_status()
    upload_url = _absolute_registry_upload_url(base_url, resp.headers["Location"])

    hasher = hashlib.sha256()
    uploaded_size = 0

    def chunks() -> Any:
        nonlocal uploaded_size
        while chunk := data.read(1024 * 1024):
            hasher.update(chunk)
            uploaded_size += len(chunk)
            yield chunk

    resp = client.patch(
        upload_url,
        content=chunks(),
        headers=headers
        | {
            "Content-Type": "application/octet-stream",
            "Content-Length": str(size),
        },
    )
    resp.raise_for_status()
    if uploaded_size != size:
        raise RuntimeError(f"Docker archive layer size changed while uploading: expected {size}, read {uploaded_size}")

    upload_url = _absolute_registry_upload_url(base_url, resp.headers.get("Location", upload_url))
    digest = f"sha256:{hasher.hexdigest()}"
    sep = "&" if "?" in upload_url else "?"
    resp = client.put(f"{upload_url}{sep}digest={digest}", content=b"", headers=headers)
    resp.raise_for_status()
    return {"mediaType": media_type, "digest": digest, "size": size}


def _absolute_registry_upload_url(base_url: str, upload_url: str) -> str:
    if upload_url.startswith("http"):
        return upload_url
    return base_url.split("/v2/", 1)[0] + upload_url


def _image_upload_name(image: str) -> str:
    name = image.rsplit("/", 1)[-1].split("@", 1)[0].split(":", 1)[0]
    return name or "coworld-image"
