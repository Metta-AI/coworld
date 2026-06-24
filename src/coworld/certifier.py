from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import secrets
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal, cast
from urllib.parse import quote, unquote, urlparse
from uuid import UUID

import httpx
import websockets

from coworld.commissioner.protocol import (
    CommissionerMessage,
    DivisionInfo,
    LeagueInfo,
    MembershipInfo,
    ScheduleRoundsRequest,
    ScheduleRoundsResponse,
)
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
from coworld.runner.io import RunnerEpisodeError
from coworld.runner.runner import (
    CONTAINER_WORKDIR,
    GAME_HOST,
    GAME_HOST_ENV_VAR,
    GAME_PORT,
    GAME_PORT_ENV_VAR,
    EpisodeArtifacts,
    EpisodeRunSpec,
    PlayerLaunchSpec,
    RunnableLaunchSpec,
    _env_args,
    _free_local_port,
    _image_command,
    _wait_for_health,
    assert_docker_image_reachable,
    generate_tokens,
    run_episode_containers,
    run_reporter,
    verify_replay_loadable,
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
    CoworldTranscript,
    StepResult,
    TranscriptStep,
    coworld_episode_request_schema,
    coworld_manifest_schema,
)

EXECUTABLE_TRANSCRIPT_PATH = Path(__file__).parent / "transcripts" / "coworld-executable.transcript.md"
_TRANSCRIPT_COLUMNS = ("id", "kind", "checks", "pass", "how")
_FULL_COMMIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_CERTIFICATION_LEAGUE_ID = UUID("00000000-0000-4000-8000-000000000001")
_CERTIFICATION_DIVISION_ID = UUID("00000000-0000-4000-8000-000000000002")
_CERTIFICATION_POLICY_IDS = (
    UUID("00000000-0000-4000-8000-000000000003"),
    UUID("00000000-0000-4000-8000-000000000004"),
)
CertifierEpisodeRunner = Callable[[CoworldEpisodeJobSpec, EpisodeArtifacts, float], None]


class SourceNotPinnedError(ValueError):
    pass


class ReporterCertificationError(RuntimeError):
    pass


class CommissionerProbeError(RuntimeError):
    pass


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
    transcript: CoworldTranscript
    step_results: list[StepResult]
    matriculated_at: datetime
    graduated_at: datetime


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


def validate_image_references(package: CoworldPackage, *, require_linux_amd64: bool = False) -> None:
    for label, image in _image_references(package):
        assert_docker_image_reachable(image, label=label, require_linux_amd64=require_linux_amd64)


def validate_players_ran(package: CoworldPackage, artifacts: EpisodeArtifacts) -> None:
    issues = []
    if not artifacts.game_stdout_path.exists():
        issues.append(f"game.runnable left no launch log at {artifacts.game_stdout_path}")

    slots_by_player_id: dict[str, list[int]] = {}
    for slot, certification_player in enumerate(package.manifest.certification.players):
        slots_by_player_id.setdefault(certification_player.player_id, []).append(slot)

    for index, player in enumerate(package.manifest.player):
        slots = slots_by_player_id.get(player.id, [])
        if not slots:
            issues.append(f"Coworld player[{index}] ({player.id!r}) has no certification slot, so it never ran")
        elif not any(artifacts.policy_log_path(slot).exists() for slot in slots):
            issues.append(f"Coworld player[{index}] ({player.id!r}) left no launch log for slots {slots}")

    if issues:
        raise ValueError("Required player runnables did not run on the smoke episode:\n- " + "\n- ".join(issues))


def validate_source_references(package: CoworldPackage) -> list[str]:
    issues = []
    pinned_issues = []
    resolved_sources = []
    github_sources: list[tuple[str, str, GitHubSource]] = []
    for label, source_url in _source_references(package):
        source = _github_source(source_url)
        if source is None:
            continue
        if source.ref is None or _FULL_COMMIT_SHA_RE.fullmatch(source.ref) is None:
            ref = source.ref or "<default branch>"
            pinned_issues.append(
                f"{label}: source_url must pin a commit SHA, not a branch/tag ({ref}); "
                "repoint to an immutable commit SHA"
            )
            continue
        github_sources.append((label, source_url, source))

    if pinned_issues:
        raise SourceNotPinnedError("\n".join(pinned_issues))

    for label, source_url, source in github_sources:
        resolved_source, contents = _github_contents(source)
        if not contents:
            issues.append(f"{label}: Empty source directory ({source_url})")
        if not _source_or_ancestor_has_dockerfile(resolved_source, contents):
            issues.append(f"{label}: No Dockerfile found ({source_url})")
        resolved_sources.append(f"{label}: {source.ref}")

    if issues:
        raise ValueError("Coworld source references are not certifiable:\n- " + "\n- ".join(issues))
    return resolved_sources


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

    players_config = game_config.get("players")
    if isinstance(players_config, list):
        slot_count = len(players_config)
    elif variant_id is None:
        slot_count = len(package.manifest.certification.players)
    else:
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


def load_executable_transcript() -> CoworldTranscript:
    return load_transcript(EXECUTABLE_TRANSCRIPT_PATH, name="coworld-executable")


def load_transcript(path: Path, *, name: str) -> CoworldTranscript:
    text = path.read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.strip().startswith("|")]
    header, _separator, *data_rows = rows
    columns = tuple(_split_transcript_row(header))
    if columns != _TRANSCRIPT_COLUMNS:
        raise ValueError(f"{path} transcript table columns must be {_TRANSCRIPT_COLUMNS}, found {columns}")
    steps = [
        TranscriptStep.model_validate(dict(zip(_TRANSCRIPT_COLUMNS, _split_transcript_row(row), strict=True)))
        for row in data_rows
    ]
    return CoworldTranscript(name=name, text=text, steps=steps)


def certify_coworld(
    manifest_path: Path,
    *,
    workspace: Path | None = None,
    timeout_seconds: float = 60.0,
    on_step: Callable[[StepResult, TranscriptStep], None] | None = None,
    episode_runner: CertifierEpisodeRunner | None = None,
) -> CertificationResult:
    transcript = load_executable_transcript()
    step_results: list[StepResult] = []
    run_episode = episode_runner or _run_local_certifier_episode

    def announce(step: TranscriptStep) -> None:
        if on_step is None:
            return
        on_step(StepResult(id=step.id, kind=step.kind, status="running"), step)

    def record(
        step: TranscriptStep,
        *,
        status: Literal["pass", "fail"],
        failure_reason: str | None = None,
        feedback: str | None = None,
    ) -> StepResult:
        result = StepResult(id=step.id, kind=step.kind, status=status, failure_reason=failure_reason, feedback=feedback)
        step_results.append(result)
        if on_step is not None:
            on_step(result, step)
        return result

    def run_step(
        step_id: str,
        action: Callable[[], object],
        pass_feedback: Callable[[object], str | None] | str | None = None,
    ) -> object:
        step = _transcript_step(transcript, step_id)
        announce(step)
        try:
            value = action()
        except Exception as exc:
            record(
                step,
                status="fail",
                failure_reason=_step_failure_reason(step_id, exc),
                feedback=str(exc),
            )
            raise
        feedback = pass_feedback(value) if callable(pass_feedback) else pass_feedback
        record(step, status="pass", feedback=feedback)
        return value

    package = cast(
        CoworldPackage,
        run_step("matriculate", lambda: load_coworld_package(manifest_path), "Manifest schema validated."),
    )
    matriculated_at = datetime.now(timezone.utc)

    def source_refs_feedback(resolved: object) -> str:
        sources = cast(list[str], resolved)
        if not sources:
            return "No GitHub source_url references declared."
        return "Pinned source refs validated:\n- " + "\n- ".join(sources)

    run_step("source-resolves", lambda: validate_source_references(package), source_refs_feedback)
    run_step("images-reachable", lambda: validate_image_references(package), "All declared images are reachable.")
    run_step(
        "fixture-conforms",
        lambda: validate_coworld_manifest_game_configs(package.manifest),
        "Certification fixture validates against game.config_schema after token injection.",
    )

    artifacts = EpisodeArtifacts.create(workspace)

    def run_smoke_episode() -> tuple[JsonObject, CoworldEpisodeJobSpec]:
        episode_request = build_episode_request(package, artifacts)
        episode_spec = build_coworld_episode_job_spec(episode_request)
        run_episode(episode_spec, artifacts, timeout_seconds)
        return episode_request, episode_spec

    smoke_result = cast(
        tuple[JsonObject, CoworldEpisodeJobSpec],
        run_step(
            "smoke-episode",
            run_smoke_episode,
            f"Episode completed in {artifacts.workspace}.",
        ),
    )
    episode_request = smoke_result[0]

    results = cast(
        JsonObject,
        run_step(
            "results-conform",
            lambda: load_results(package, artifacts),
            f"{artifacts.results_path} validates against game.results_schema.",
        ),
    )

    run_step(
        "replay-present",
        lambda: _assert_replay_present(artifacts),
        f"Replay artifact exists at {artifacts.replay_path}.",
    )
    run_step(
        "replay-loadable",
        lambda: verify_replay_loadable(package.game, artifacts, timeout_seconds=timeout_seconds),
        "Replay loads through /client/replay and /replay.",
    )
    run_step("players-run", lambda: validate_players_ran(package, artifacts), "Game and declared players started.")

    supporting_result = cast(
        tuple[list[ReportCertification], str],
        run_step(
            "supporting-roles",
            lambda: run_certification_supporting_roles(package, artifacts, timeout_seconds=timeout_seconds),
            lambda value: cast(tuple[list[ReportCertification], str], value)[1],
        ),
    )
    reports = supporting_result[0]

    _assert_transcript_complete(transcript, step_results)
    graduated_at = datetime.now(timezone.utc)

    return CertificationResult(
        package=package,
        artifacts=artifacts,
        episode_request=episode_request,
        results=results,
        reports=reports,
        transcript=transcript,
        step_results=step_results,
        matriculated_at=matriculated_at,
        graduated_at=graduated_at,
    )


def _run_local_certifier_episode(
    job: CoworldEpisodeJobSpec,
    artifacts: EpisodeArtifacts,
    timeout_seconds: float,
) -> None:
    tokens = generate_tokens(len(job.players))
    game_config = game_config_with_tokens(job.game_config, tokens)
    artifacts.config_path.write_text(json.dumps(game_config, indent=2), encoding="utf-8")
    run_spec = EpisodeRunSpec(
        game=RunnableLaunchSpec.from_model(job.game_runnable),
        players=[PlayerLaunchSpec.from_model(player) for player in job.players],
        tokens=tokens,
        artifacts=artifacts,
        timeout_seconds=timeout_seconds,
    )
    run_episode_containers(run_spec, verify_replay=False)


def _assert_replay_present(artifacts: EpisodeArtifacts) -> None:
    if not artifacts.replay_path.exists():
        raise FileNotFoundError(f"Replay file was not produced: {artifacts.replay_path}")


def _step_failure_reason(step_id: str, exc: Exception) -> str:
    if isinstance(exc, SourceNotPinnedError):
        return "source_not_pinned"
    if isinstance(exc, ReporterCertificationError):
        return "reporter_failed"
    if isinstance(exc, CommissionerProbeError):
        return "commissioner_protocol_failed"
    if isinstance(exc, RunnerEpisodeError):
        return exc.error_type
    if step_id == "results-conform":
        if isinstance(exc, FileNotFoundError):
            return "results_missing"
        return "results_malformed"
    if step_id == "replay-present":
        return "replay_missing"
    return {
        "matriculate": "manifest_invalid",
        "source-resolves": "source_unresolved",
        "images-reachable": "image_unreachable",
        "fixture-conforms": "fixture_invalid",
        "players-run": "players_missing",
        "supporting-roles": "supporting_roles_failed",
    }.get(step_id, "step_failed")


def run_certification_supporting_roles(
    package: CoworldPackage,
    artifacts: EpisodeArtifacts,
    *,
    timeout_seconds: float,
) -> tuple[list[ReportCertification], str]:
    feedback = []
    try:
        reports = run_certification_reporters(package, artifacts, timeout_seconds=timeout_seconds)
    except Exception as exc:
        raise ReporterCertificationError(str(exc)) from exc
    feedback.append(f"reporters run: {len(reports)}")

    for commissioner in package.manifest.commissioner:
        try:
            run_certification_commissioner(
                commissioner.id,
                commissioner.as_runnable_spec(),
                artifacts,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            raise CommissionerProbeError(f"{commissioner.id}: {exc}") from exc
    feedback.append(f"commissioners probed: {len(package.manifest.commissioner)}")

    if package.manifest.grader:
        feedback.append(f"graders declared, harness not available yet: {len(package.manifest.grader)}")
    if package.manifest.diagnoser:
        feedback.append(f"diagnosers declared, harness not available yet: {len(package.manifest.diagnoser)}")
    if package.manifest.optimizer:
        feedback.append(f"optimizers skipped for Executable: {len(package.manifest.optimizer)}")
    if feedback == ["reporters run: 0", "commissioners probed: 0"]:
        feedback.append("no supporting roles declared")
    return reports, "; ".join(feedback)


def run_certification_commissioner(
    commissioner_id: str,
    commissioner: CoworldRunnableSpec,
    artifacts: EpisodeArtifacts,
    *,
    timeout_seconds: float,
) -> ScheduleRoundsResponse:
    workspace = artifacts.workspace / "commissioners" / commissioner_id
    workspace.mkdir(parents=True, exist_ok=True)
    stdout_path = workspace / "commissioner.stdout.log"
    stderr_path = workspace / "commissioner.stderr.log"
    port = _free_local_port()
    container = f"coworld-cert-commissioner-{secrets.token_hex(8)}"
    launch_spec = RunnableLaunchSpec.from_model(commissioner)
    try:
        with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
            process = subprocess.Popen(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    container,
                    "-p",
                    f"127.0.0.1:{port}:{GAME_PORT}",
                    *_env_args(commissioner.env),
                    "-e",
                    f"{GAME_HOST_ENV_VAR}={GAME_HOST}",
                    "-e",
                    f"{GAME_PORT_ENV_VAR}={GAME_PORT}",
                    *_image_command(launch_spec),
                ],
                stdout=stdout,
                stderr=stderr,
                text=True,
            )
            _wait_for_health(port, process, stderr_path, timeout_seconds=timeout_seconds)
            return asyncio.run(
                request_commissioner_once(
                    ws_url=f"ws://127.0.0.1:{port}/round",
                    request=_certification_schedule_rounds_request(),
                    response_type=ScheduleRoundsResponse,
                    timeout_seconds=timeout_seconds,
                )
            )
    finally:
        subprocess.run(["docker", "rm", "-f", container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def request_commissioner_once(
    *,
    ws_url: str,
    request: ScheduleRoundsRequest,
    response_type: type[ScheduleRoundsResponse],
    timeout_seconds: float,
    ping_timeout_seconds: float = 30.0,
) -> ScheduleRoundsResponse:
    async with asyncio.timeout(timeout_seconds):
        async with websockets.connect(
            ws_url,
            ping_interval=ping_timeout_seconds,
            ping_timeout=ping_timeout_seconds,
        ) as websocket:
            await websocket.send(json.dumps(request.to_json()))
            payload = json.loads(await websocket.recv())
            message = CommissionerMessage.from_json(payload)
            if not isinstance(message, response_type):
                raise RuntimeError(f"Unexpected commissioner message type: {payload['type']!r}")
            return message


def _certification_schedule_rounds_request() -> ScheduleRoundsRequest:
    division = DivisionInfo(id=_CERTIFICATION_DIVISION_ID, name="Certification", level=1)
    return ScheduleRoundsRequest(
        league=LeagueInfo(id=_CERTIFICATION_LEAGUE_ID, commissioner_key="container"),
        divisions=[division],
        active_memberships=[
            MembershipInfo(
                id=policy_id,
                league_id=_CERTIFICATION_LEAGUE_ID,
                division_id=division.id,
                policy_version_id=policy_id,
                player_id=f"cert-player-{index}",
                is_champion=True,
            )
            for index, policy_id in enumerate(_CERTIFICATION_POLICY_IDS)
        ],
        recent_rounds=[],
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


def _split_transcript_row(row: str) -> list[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def _transcript_step(transcript: CoworldTranscript, step_id: str) -> TranscriptStep:
    for step in transcript.steps:
        if step.id == step_id:
            return step
    raise ValueError(f"certifier step {step_id!r} is not declared in transcript {transcript.name!r}")


def _assert_transcript_complete(transcript: CoworldTranscript, step_results: list[StepResult]) -> None:
    executed = [result.id for result in step_results]
    declared = [step.id for step in transcript.steps]
    if executed != declared:
        raise ValueError(f"certifier executed {executed} but transcript {transcript.name!r} declares {declared}")


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
