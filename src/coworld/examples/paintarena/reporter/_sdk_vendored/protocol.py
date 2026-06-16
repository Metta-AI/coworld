from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EpisodeStatus = Literal["success", "failed"]
ArtifactEncoding = Literal["identity", "zlib"]
BundleToken = Literal["results", "replay", "error_info", "game_logs", "player_logs", "player_artifact"]


class ReporterArtifactRef(BaseModel):
    uri: str
    media_type: str
    encoding: ArtifactEncoding = "identity"


class ReporterErrorInfo(BaseModel):
    error_type: str | None
    error: str | None
    failed_policy_index: int | None = None
    failed_agent_index: int | None = None


class ReporterEpisodeManifest(BaseModel):
    ereq_id: str
    status: EpisodeStatus
    include: list[BundleToken]
    files: dict[BundleToken, str | dict[str, str]]


class ReporterEpisodeArtifacts(BaseModel):
    results: ReporterArtifactRef | None = None
    replay: ReporterArtifactRef | None = None
    game_logs: dict[str, ReporterArtifactRef] = Field(default_factory=dict)
    player_logs: dict[str, ReporterArtifactRef] = Field(default_factory=dict)
    player_artifact: dict[str, ReporterArtifactRef] = Field(default_factory=dict)


class ReporterEpisodeInlineJson(BaseModel):
    error_info: ReporterErrorInfo | None = None


class ReporterEpisodeInput(BaseModel):
    episode_request_id: str
    status: EpisodeStatus
    manifest: ReporterEpisodeManifest
    artifacts: ReporterEpisodeArtifacts
    inline_json: ReporterEpisodeInlineJson = Field(default_factory=ReporterEpisodeInlineJson)


class ReportRequest(BaseModel):
    type: Literal["report_request"] = "report_request"
    request_id: str
    episodes: list[ReporterEpisodeInput]
    report_uri: str
