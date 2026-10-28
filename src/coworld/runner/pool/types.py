import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from coworld.runner.player_artifacts import ArtifactUploadTargets
from coworld.types import CoworldEpisodeJobSpec


class ImageLaunchMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    image: str = Field(pattern=r"^.+@sha256:[0-9a-f]{64}$")
    architecture: Literal["amd64", "arm64"]
    entrypoint: tuple[str, ...]
    command: tuple[str, ...]
    working_directory: str
    env: dict[str, str]


class PoolResources(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cpu: str
    memory: str
    ephemeral_storage: str
    cpu_limit: str
    memory_limit: str


class ExecutionProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    runtime_version: Literal[1] = 1
    execution_mode: Literal["reuse"] = "reuse"
    player_runtime: Literal["game-hosted"] = "game-hosted"
    image: ImageLaunchMetadata
    command: tuple[str, ...] = Field(min_length=1)
    episode_timeout_seconds: int = Field(gt=0)
    resources: PoolResources
    # Profiles are explicitly qualified. Sidecars with episode state require their own reset protocol.
    sidecar_policy: Literal["none"] = "none"
    network_policy: Literal["local-development", "restricted-egress-no-inference"] = "local-development"

    def content_hash(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class PreparedPoolEpisode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: ExecutionProfile
    spec: CoworldEpisodeJobSpec
    timeout_seconds: int = Field(gt=0)
    owner_user_id: str
    runtime_episode_id: str


class PoolCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results_url: str
    replay_url: str
    logs_url: str


class PoolArtifactTargets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uploads: ArtifactUploadTargets
    completion: PoolCompletion
    coordinator_env: dict[str, str]
    game_env: dict[str, str]
    spec: CoworldEpisodeJobSpec
