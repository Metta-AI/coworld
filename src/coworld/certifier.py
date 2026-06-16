from __future__ import annotations

import copy
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import quote, unquote, urlparse

import httpx

from coworld.manifest_validation import (
    game_config_with_tokens,
    infer_token_count_for_game_config,
    validate_coworld_manifest_game_configs,
)
from coworld.report import ReportManifest, validate_report_zip
from coworld.reporter_protocol import (
    BundleToken,
    ReporterArtifactRef,
    ReporterEpisodeArtifacts,
    ReporterEpisodeInput,
    ReporterEpisodeManifest,
)
from coworld.runner.runner import (
    CONTAINER_WORKDIR,
    EpisodeArtifacts,
    PlayerLaunchSpec,
    RunnableLaunchSpec,
    assert_docker_image_reachable,
    run_coworld_episode,
    run_reporter,
)
from coworld.schema_validation import (
    JsonObject,
    JsonSchema,
    load_json_object,
    validate_json_schema,
)
from coworld.types import (
    CoworldDoc,
    CoworldEpisodeJobSpec,
    CoworldManifest,
    CoworldRunnableSpec,
    coworld_episode_request_schema,
    coworld_manifest_schema,
)


@dataclass(frozen=True)
class CoworldProtocolDocs:
    player: CoworldDoc
    global_: CoworldDoc


@dataclass(frozen=True)
class GitHubSource:
    owner: str
    repo: str
    ref: str | None
    path: str


@dataclass(frozen=True)
class CoworldPackage:
    manifest_path: Path
    manifest: CoworldManifest
    game: RunnableLaunchSpec
    config_schema: JsonSchema
    results_schema: JsonSchema
    protocols: CoworldProtocolDocs


@dataclass(frozen=True)
class ReportCertification:
    reporter_id: str
    manifest: ReportManifest
    report_path: Path


@dataclass(frozen=True)
class CertificationResult:
    package: CoworldPackage
    artifacts: EpisodeArtifacts
    episode_request: JsonObject
    results: JsonObject
    reports: list[ReportCertification]


def load_coworld_package(manifest_path: Path) -> CoworldPackage:
    manifest_path = manifest_path.resolve()
    manifest = load_json_object(manifest_path)
    validate_json_schema(manifest, coworld_manifest_schema())
    typed_manifest = CoworldManifest.model_validate(manifest)
    validate_coworld_manifest_game_configs(typed_manifest)

    package = CoworldPackage(
        manifest_path=manifest_path,
        manifest=typed_manifest,
        game=RunnableLaunchSpec.from_model(typed_manifest.game.runnable),
        config_schema=typed_manifest.game.config_schema,
        results_schema=typed_manifest.game.results_schema,
        protocols=CoworldProtocolDocs(
            player=typed_manifest.game.protocols.player,
            global_=typed_manifest.game.protocols.global_,
        ),
    )
    validate_certification_references(package)
    return package


def validate_certification_references(package: CoworldPackage) -> None:
    _certification_player_specs(package)


def validate_image_references(package: CoworldPackage) -> None:
    for label, image in _image_references(package):
        assert_docker_image_reachable(image, label=label)


def validate_source_references(package: CoworldPackage) -> None:
    issues = []
    for label, source_url in _source_references(package):
        source = _github_source(source_url)
        if source is None:
            continue
        resolved_source, contents = _github_contents(source)
        if not contents:
            issues.append(f"{label}: Empty source directory ({source_url})")
        if not _source_or_ancestor_has_dockerfile(resolved_source, contents):
            issues.append(f"{label}: No Dockerfile found ({source_url})")

    if issues:
        raise ValueError("Coworld source references are not certifiable:\n- " + "\n- ".join(issues))


def build_game_config(package: CoworldPackage, tokens: list[str]) -> JsonObject:
    game_config = game_config_with_tokens(package.manifest.certification.game_config, tokens)
    validate_json_schema(game_config, package.config_schema)
    return game_config


def build_episode_request(package: CoworldPackage, artifacts: EpisodeArtifacts) -> JsonObject:
    episode_request: JsonObject = {
        key: cast(object, value)
        for key, value in build_manifest_episode_job_spec(package)
        .model_dump(by_alias=True, exclude_defaults=True)
        .items()
    }
    return episode_request


def build_manifest_episode_job_spec(
    package: CoworldPackage,
    *,
    variant_id: str | None = None,
    player_images: list[str] | None = None,
    player_run: list[str] | None = None,
) -> CoworldEpisodeJobSpec:
    if variant_id is None:
        game_config = copy.deepcopy(package.manifest.certification.game_config)
    else:
        variants = {variant.id: variant for variant in package.manifest.variants}
        if variant_id not in variants:
            raise ValueError(f"unknown Coworld variant_id: {variant_id!r}")
        game_config = copy.deepcopy(variants[variant_id].game_config)

    slot_count = infer_token_count_for_game_config(package.config_schema, game_config)
    players = _certification_player_specs(package)
    if len(players) != slot_count:
        players = [players[index % len(players)].model_copy(deep=True) for index in range(slot_count)]
    if not player_images:
        if player_run:
            raise ValueError("player_run requires at least one player image")
    else:
        if len(player_images) == 1:
            slot_images = player_images * slot_count
        elif len(player_images) == slot_count:
            slot_images = player_images
        else:
            expected_counts = "1" if slot_count == 1 else f"1 or {slot_count}"
            raise ValueError(f"expected {expected_counts} player images for {slot_count} player slots")

        player_update = {"run": list(player_run)} if player_run is not None else {}
        players = [
            players[slot].model_copy(deep=True, update={"image": image, **player_update})
            for slot, image in enumerate(slot_images)
        ]

    return CoworldEpisodeJobSpec(
        manifest=package.manifest.model_copy(deep=True),
        game_config=game_config,
        players=players,
    )


def build_player_launch_specs(episode_request: JsonObject) -> list[PlayerLaunchSpec]:
    job_spec = build_coworld_episode_job_spec(episode_request)
    return [PlayerLaunchSpec.from_model(player) for player in job_spec.players]


def build_coworld_episode_job_spec(episode_request: JsonObject) -> CoworldEpisodeJobSpec:
    return CoworldEpisodeJobSpec.model_validate(episode_request)


def load_coworld_episode_job_spec(episode_request_path: Path) -> CoworldEpisodeJobSpec:
    episode_request = load_json_object(episode_request_path)
    validate_json_schema(episode_request, coworld_episode_request_schema())
    return build_coworld_episode_job_spec(episode_request)


def load_manifest_episode_job_spec(package: CoworldPackage, episode_request_path: Path) -> CoworldEpisodeJobSpec:
    spec = load_coworld_episode_job_spec(episode_request_path)
    if spec.manifest != package.manifest:
        raise ValueError(f"episode request manifest does not match {package.manifest_path}")
    return spec


def load_results(package: CoworldPackage, artifacts: EpisodeArtifacts) -> JsonObject:
    results = load_json_object(artifacts.results_path)
    validate_json_schema(results, package.results_schema)
    return results


def certify_coworld(
    manifest_path: Path,
    *,
    workspace: Path | None = None,
    timeout_seconds: float = 60.0,
) -> CertificationResult:
    package = load_coworld_package(manifest_path)
    validate_source_references(package)
    validate_image_references(package)
    artifacts = EpisodeArtifacts.create(workspace)
    episode_request = build_episode_request(package, artifacts)
    run_coworld_episode(
        build_coworld_episode_job_spec(episode_request),
        artifacts,
        timeout_seconds=timeout_seconds,
        verify_replay=True,
    )

    results = load_results(package, artifacts)
    if not artifacts.replay_path.exists():
        raise FileNotFoundError(f"Replay file was not produced: {artifacts.replay_path}")

    reports = run_certification_reporters(package, artifacts, timeout_seconds=timeout_seconds)

    return CertificationResult(
        package=package,
        artifacts=artifacts,
        episode_request=episode_request,
        results=results,
        reports=reports,
    )


def run_certification_reporters(
    package: CoworldPackage,
    artifacts: EpisodeArtifacts,
    *,
    timeout_seconds: float,
) -> list[ReportCertification]:
    """Run every declared reporter against the certification episode and certify its report.

    Assembles one episode bundle from the certification artifacts, runs each
    ``manifest.reporter`` container against it, and validates the report zip —
    including the safe render profile for any HTML ``render`` entry (see
    ``docs/artifacts/RENDER.md``). Reporters are optional, so a Coworld without
    them certifies with an empty report list.
    """
    reporters = package.manifest.reporter
    if not reporters:
        return []

    request_id = f"cert-{artifacts.workspace.name}"
    episode = build_local_reporter_episode_input(artifacts, episode_request_id=request_id)
    certifications: list[ReportCertification] = []
    for reporter in reporters:
        workspace = artifacts.workspace / "reports" / reporter.id
        report_bytes = run_reporter(
            RunnableLaunchSpec.from_model(reporter.as_runnable_spec()),
            workspace=workspace,
            request_id=request_id,
            episodes=[episode],
            timeout_seconds=timeout_seconds,
        )
        manifest = validate_report_zip(report_bytes)
        certifications.append(
            ReportCertification(reporter_id=reporter.id, manifest=manifest, report_path=workspace / "report.zip")
        )
    return certifications


def build_local_reporter_episode_input(
    artifacts: EpisodeArtifacts,
    *,
    episode_request_id: str,
    uri_root: str = CONTAINER_WORKDIR,
) -> ReporterEpisodeInput:
    files: dict[BundleToken, str | dict[str, str]] = {
        "results": "results.json",
        "replay": "replay",
        "game_logs": {"stdout": "logs/game.stdout.log", "stderr": "logs/game.stderr.log"},
    }
    include: list[BundleToken] = ["results", "replay", "game_logs"]
    episode_artifacts = ReporterEpisodeArtifacts(
        results=ReporterArtifactRef(
            uri=f"file://{uri_root}/{artifacts.results_path.relative_to(artifacts.workspace)}",
            media_type="application/json",
        ),
        replay=ReporterArtifactRef(
            uri=f"file://{uri_root}/{artifacts.replay_path.relative_to(artifacts.workspace)}",
            media_type="application/json",
        ),
        game_logs={
            "stdout": ReporterArtifactRef(
                uri=f"file://{uri_root}/{artifacts.game_stdout_path.relative_to(artifacts.workspace)}",
                media_type="text/plain",
            ),
            "stderr": ReporterArtifactRef(
                uri=f"file://{uri_root}/{artifacts.game_stderr_path.relative_to(artifacts.workspace)}",
                media_type="text/plain",
            ),
        },
    )

    player_log_files: dict[str, str] = {}
    for log_path in sorted(artifacts.logs_dir.glob("policy_agent_*.log")):
        slot = log_path.stem.removeprefix("policy_agent_")
        player_log_files[slot] = f"logs/{log_path.name}"
        episode_artifacts.player_logs[slot] = ReporterArtifactRef(
            uri=f"file://{uri_root}/{log_path.relative_to(artifacts.workspace)}",
            media_type="text/plain",
        )
    if player_log_files:
        files["player_logs"] = player_log_files
        include.append("player_logs")

    player_artifact_files: dict[str, str] = {}
    for artifact_path in sorted(artifacts.workspace.glob("policy_artifact_*.zip")):
        slot = artifact_path.stem.removeprefix("policy_artifact_")
        player_artifact_files[slot] = f"artifacts/{artifact_path.name}"
        episode_artifacts.player_artifact[slot] = ReporterArtifactRef(
            uri=f"file://{uri_root}/{artifact_path.relative_to(artifacts.workspace)}",
            media_type="application/zip",
        )
    if player_artifact_files:
        files["player_artifact"] = player_artifact_files
        include.append("player_artifact")

    return ReporterEpisodeInput(
        episode_request_id=episode_request_id,
        status="success",
        manifest=ReporterEpisodeManifest(
            ereq_id=episode_request_id,
            status="success",
            include=include,
            files=files,
        ),
        artifacts=episode_artifacts,
    )


def _image_references(package: CoworldPackage) -> list[tuple[str, str]]:
    references = [("game.runnable.image", package.game.image)]
    references.extend(
        (f"Certification players[{slot}].image", player.image)
        for slot, player in enumerate(_certification_player_specs(package))
    )
    for section in ("player", "reporter", "commissioner", "grader", "diagnoser", "optimizer"):
        references.extend(
            (f"Coworld {section}[{index}].image", runnable.image)
            for index, runnable in enumerate(getattr(package.manifest, section))
        )
    return list(dict.fromkeys(references))


def _source_references(package: CoworldPackage) -> list[tuple[str, str]]:
    references = []
    game_source_url = package.manifest.game.runnable.source_url
    if game_source_url is not None:
        references.append(("game.runnable.source_url", game_source_url))
    for section in ("player", "reporter", "commissioner", "grader", "diagnoser", "optimizer"):
        references.extend(
            (f"Coworld {section}[{index}].source_url", source_url)
            for index, runnable in enumerate(getattr(package.manifest, section))
            if (source_url := runnable.source_url) is not None
        )
    return list(dict.fromkeys(references))


def _github_source(source_url: str) -> GitHubSource | None:
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc not in {"github.com", "www.github.com"}:
        return None

    parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        return None

    owner = parts[0]
    repo = parts[1].removesuffix(".git")
    if len(parts) == 2:
        return GitHubSource(owner=owner, repo=repo, ref=None, path="")
    if len(parts) >= 4 and parts[2] in {"tree", "blob"}:
        return GitHubSource(owner=owner, repo=repo, ref=parts[3], path="/".join(parts[4:]))
    return None


def _github_contents(source: GitHubSource) -> tuple[GitHubSource, list[dict[str, object]]]:
    api_url = _github_contents_url(source)
    for candidate in _github_source_candidates(source):
        api_url = _github_contents_url(candidate)
        response = _github_contents_response(candidate, api_url)
        if response.status_code == 404:
            continue
        if response.status_code != 200:
            raise RuntimeError(f"GitHub source URL is not readable: {api_url} returned HTTP {response.status_code}")

        contents = response.json()
        if isinstance(contents, list):
            return candidate, cast(list[dict[str, object]], contents)
        if isinstance(contents, dict):
            return candidate, [cast(dict[str, object], contents)]
        raise TypeError(f"Expected GitHub contents object or list from {api_url}")

    raise RuntimeError(f"GitHub source URL is not readable: {api_url} returned HTTP 404")


def _source_or_ancestor_has_dockerfile(source: GitHubSource, contents: list[dict[str, object]]) -> bool:
    if any(_is_dockerfile(item) for item in contents):
        return True

    for ancestor in _github_ancestor_sources(source):
        _, ancestor_contents = _github_contents(ancestor)
        if any(_is_dockerfile(item) for item in ancestor_contents):
            return True
    return False


def _github_contents_url(source: GitHubSource) -> str:
    api_path = f"/{quote(source.path, safe='/')}" if source.path else ""
    return f"https://api.github.com/repos/{source.owner}/{source.repo}/contents{api_path}"


def _github_contents_response(source: GitHubSource, api_url: str) -> httpx.Response:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token := _github_token():
        headers["Authorization"] = f"Bearer {token}"

    return httpx.get(
        api_url,
        headers=headers,
        params={"ref": source.ref} if source.ref is not None else {},
        timeout=30.0,
    )


def _github_source_candidates(source: GitHubSource) -> list[GitHubSource]:
    candidates = [source]
    if source.ref is None or not source.path:
        return candidates

    path_parts = source.path.split("/")
    candidates.extend(
        GitHubSource(
            owner=source.owner,
            repo=source.repo,
            ref=f"{source.ref}/{'/'.join(path_parts[:index])}",
            path="/".join(path_parts[index:]),
        )
        for index in range(1, len(path_parts) + 1)
    )
    return candidates


def _github_ancestor_sources(source: GitHubSource) -> list[GitHubSource]:
    if not source.path:
        return []

    path_parts = source.path.split("/")
    return [
        GitHubSource(
            owner=source.owner,
            repo=source.repo,
            ref=source.ref,
            path="/".join(path_parts[:index]),
        )
        for index in range(len(path_parts) - 1, -1, -1)
    ]


def _is_dockerfile(item: dict[str, object]) -> bool:
    name = item["name"]
    if item["type"] != "file" or not isinstance(name, str):
        return False
    return name == "Dockerfile" or (name.startswith("Dockerfile.") and name != "Dockerfile.dockerignore")


def _github_token() -> str | None:
    for variable in ("GITHUB_TOKEN", "GH_TOKEN"):
        if token := os.environ.get(variable):
            return token
    if shutil.which("gh") is None:
        return None

    completed = subprocess.run(["gh", "auth", "token"], check=False, capture_output=True, text=True)
    token = completed.stdout.strip()
    if completed.returncode == 0 and token:
        return token
    return None


def _certification_player_specs(package: CoworldPackage) -> list[CoworldRunnableSpec]:
    declared_players = _manifest_items_by_id(package, "player")
    players = package.manifest.certification.players
    specs: list[CoworldRunnableSpec] = []
    for slot, certification_player in enumerate(players):
        player_id = certification_player.player_id
        if player_id not in declared_players:
            raise ValueError(f"unknown certification player_id for slot {slot}: {player_id!r}")
        declared_player = declared_players[player_id]
        specs.append(declared_player.as_runnable_spec())
    return specs


def _manifest_items_by_id(package: CoworldPackage, section: str):
    items = getattr(package.manifest, section)
    items_by_id = {}
    for item in items:
        if item.id in items_by_id:
            raise ValueError(f"duplicate {section} id: {item.id!r}")
        items_by_id[item.id] = item
    return items_by_id
