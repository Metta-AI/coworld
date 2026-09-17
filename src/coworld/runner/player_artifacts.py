import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import IO
from uuid import UUID

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter, model_validator

ARTIFACT_TARGETS_PATH = "/var/run/coworld-uploads/targets.json"
DIAGNOSTIC_TARGETS_PATH = "/var/run/coworld-diagnostics/targets.json"


class PersistentDiagnosticSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_id: UUID = Field(description="Persistent controller identity.")
    session_id: UUID = Field(description="Immutable launch identity for this controller session.")
    player_id: str = Field(description="Player identity running this controller session.")
    policy_version_id: UUID = Field(description="Policy version used for this controller session.")
    coworld_id: str = Field(description="Coworld identity used for this controller session.")
    generation: int = Field(description="Persistent runtime generation at launch.")
    created_at: datetime = Field(description="UTC timestamp when this controller session was created.")

    @property
    def prefix(self) -> str:
        return f"jobs/{self.runtime_id}/sessions/{self.session_id}"


class PlayerArtifactUploadGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str
    fields: dict[str, str]


class ArtifactUploadTargets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expires_at: AwareDatetime
    targets: dict[str, str]


class PersistentDiagnosticTargets(ArtifactUploadTargets):
    session: PersistentDiagnosticSession
    artifact_upload: PlayerArtifactUploadGrant | None = None


PLAYER_ARTIFACT_CAPTURE_HEADER = "X-Coworld-Artifact-Capture"
PLAYER_ARTIFACT_MAX_BYTES = 200 * 1024 * 1024
PLAYER_ARTIFACT_SESSION_MAX_BYTES = 512 * 1024 * 1024
PLAYER_ARTIFACT_SESSION_MAX_COUNT = 128
PLAYER_ARTIFACT_EPISODE_MAX_COUNT = 16


class PlayerArtifactCapture(BaseModel):
    """Producer-reported capture identity and coverage, independent of upload time."""

    model_config = ConfigDict(extra="forbid")
    capture_id: UUID
    started_at: AwareDatetime
    ended_at: AwareDatetime

    @model_validator(mode="after")
    def ordered_capture(self) -> "PlayerArtifactCapture":
        if self.ended_at <= self.started_at:
            raise ValueError("capture ended_at must be after started_at")
        self.started_at = self.started_at.astimezone(UTC)
        self.ended_at = self.ended_at.astimezone(UTC)
        return self


class PlayerArtifactReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runtime_id: UUID
    session_id: UUID
    artifact_id: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def prefix(self) -> str:
        return f"jobs/{self.runtime_id}/sessions/{self.session_id}/artifacts/{self.artifact_id}"


class PlayerArtifactManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session: PersistentDiagnosticSession
    capture: PlayerArtifactCapture
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0, le=PLAYER_ARTIFACT_MAX_BYTES)

    def canonical_bytes(self) -> bytes:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()

    @property
    def reference(self) -> PlayerArtifactReference:
        return PlayerArtifactReference(
            runtime_id=self.session.runtime_id,
            session_id=self.session.session_id,
            artifact_id=hashlib.sha256(self.canonical_bytes()).hexdigest(),
        )


def upload_captured_player_artifact(
    *,
    grant: PlayerArtifactUploadGrant,
    session: PersistentDiagnosticSession,
    capture: PlayerArtifactCapture,
    artifact: IO[bytes],
    size: int,
    ledger_path: Path,
) -> PlayerArtifactManifest | None:
    """Reserve a bounded session budget, then publish content-addressed bytes.

    Reserve before I/O so failures and worker restarts cannot reset the budget.
    Identical retries reuse the reservation and write identical objects. The
    caller serializes uploads for this player; the ledger lives on its job volume.
    """
    artifact.seek(0)
    digest = hashlib.sha256()
    while chunk := artifact.read(1024 * 1024):
        digest.update(chunk)
    manifest = PlayerArtifactManifest(session=session, capture=capture, size_bytes=size, sha256=digest.hexdigest())
    reference = manifest.reference
    reservations = TypeAdapter(dict[str, int]).validate_json(ledger_path.read_bytes()) if ledger_path.exists() else {}
    if reference.artifact_id not in reservations:
        if (
            len(reservations) >= PLAYER_ARTIFACT_SESSION_MAX_COUNT
            or sum(reservations.values()) + size > PLAYER_ARTIFACT_SESSION_MAX_BYTES
        ):
            return None
        reservations[reference.artifact_id] = size
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        pending = ledger_path.with_suffix(".tmp")
        pending.write_text(json.dumps(reservations))
        pending.replace(ledger_path)
    artifact.seek(0)
    with httpx.Client(proxy=os.environ.get("COWORLD_EGRESS_RELAY_URL"), timeout=60) as client:
        response = client.post(
            grant.url,
            data={**grant.fields, "key": f"{reference.prefix}/artifact.zip"},
            files={"file": ("artifact.zip", artifact, "application/zip")},
        )
        response.raise_for_status()
        response = client.post(
            grant.url,
            data={**grant.fields, "key": f"{reference.prefix}/manifest.json"},
            files={"file": ("manifest.json", manifest.canonical_bytes(), "application/json")},
        )
        response.raise_for_status()
    return manifest
