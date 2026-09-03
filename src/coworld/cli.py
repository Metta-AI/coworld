from __future__ import annotations

import json
import shlex
import time
import uuid
import webbrowser
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Iterator
from urllib.parse import urlparse

import typer
from packaging.version import Version
from rich import box
from rich.table import Table
from typer.core import TyperCommand

from coworld.api_client import AutoChampion, CoworldApiClient
from coworld.bundle import build_coworld_manifest
from coworld.campaign_cli import register_campaign_commands
from coworld.certification_report import write_certification_report
from coworld.certifier import (
    build_manifest_episode_job_spec,
    certify_coworld,
    load_coworld_package,
    load_executable_transcript,
    load_manifest_episode_job_spec,
)
from coworld.cli_support import (
    active_docker_context,
    console,
    emit_json,
    observatory_web_url,
    print_replay_session,
    resolve_league_id,
    validate_run_argv,
)
from coworld.config import DEFAULT_OPTIMIZER_PORT, DEFAULT_SUBMIT_SERVER
from coworld.deploy_audit import (
    DEFAULT_GITHUB_OWNER,
    DEFAULT_REPO_PREFIX,
    audit_coworld_deployments,
    format_deploy_audit_markdown,
    github_token_from_env,
)
from coworld.manifest.schema_check import check_manifest_schema
from coworld.manifest_uri import materialized_manifest_path, materialized_replay_path
from coworld.optimizer.runtime import OptimizerSetupError, run_optimizer_session
from coworld.play import PlaySession, ReplaySession, _resolve_bedrock_aws_env, play_coworld, replay_coworld
from coworld.runner.runner import DEFAULT_PLAYER_EXIT_TIMEOUT_SECONDS, EpisodeArtifacts, run_coworld_episode
from coworld.submit import submit_policy_to_league_cmd
from coworld.tournament_cli import register_tournament_commands
from coworld.types import StepResult, TranscriptStep
from coworld.upload import (
    ContainerImageResponse,
    CoworldCertificationStatus,
    CoworldLeagueSeedRebindChange,
    CoworldListEntry,
    CoworldStatusResult,
    CoworldUploadClient,
    CoworldUploadResponse,
    cache_certified_manifest,
    coworld_status,
    download_coworld_cmd,
    downloaded_coworld_manifest_path,
    patch_commissioner_cmd,
    upload_coworld_cmd,
    upload_policy_cmd,
)
from softmax import auth as softmax_auth
from softmax.players import list_players, player_app

_DEFAULT_POLICY_NAME_MAX_LENGTH = 64

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
register_tournament_commands(app)
register_campaign_commands(app)
hosted_game_app = typer.Typer(no_args_is_help=True, help="Create and join hosted Coworld games.")
app.add_typer(hosted_game_app, name="hosted-game")
manifest_schema_app = typer.Typer(no_args_is_help=True, help="Check versioned Coworld manifest schemas.")
app.add_typer(manifest_schema_app, name="manifest-schema")


@manifest_schema_app.command("check")
def manifest_schema_check(
    against: Annotated[str, typer.Option(help="Git ref containing the base schema.")] = "origin/main",
) -> None:
    failures = check_manifest_schema(against)
    if failures:
        for failure in failures:
            typer.echo(f"error: {failure}", err=True)
        raise typer.Exit(1)
    typer.echo(f"Coworld manifest schema declarations are valid against {against}.")


class _DockerCommand(TyperCommand):
    def invoke(self, ctx: typer.Context) -> object:
        typer.echo(f"Docker context: {active_docker_context()} (local images use this store)")
        return super().invoke(ctx)


def _parse_secret_env(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise typer.BadParameter(f"Expected KEY=VALUE format, got: {value}")
    key, _, val = value.partition("=")
    return key, val


def _parse_override(value: str) -> tuple[str, object]:
    """Parse a `KEY=VALUE` override; VALUE is JSON-decoded so `flag=true` becomes a bool."""
    key, sep, raw = value.partition("=")
    if not sep or not key:
        raise typer.BadParameter(f"Expected KEY=VALUE format, got: {value}")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = raw
    return key, parsed


league_app = typer.Typer(
    no_args_is_help=True,
    help="Create and inspect Coworld league seeds (Softmax team, or the Coworld owner for their own Coworld).",
)
app.add_typer(league_app, name="league")

counterfactual_app = typer.Typer(
    no_args_is_help=True,
    help="Trigger and inspect counterfactual evals (candidate vs baseline on a league).",
)
app.add_typer(counterfactual_app, name="counterfactual")

secret_app = typer.Typer(no_args_is_help=True, help="Manage hosted Coworld secrets.")
app.add_typer(secret_app, name="secret")


def _parse_policy_ref(ref: str) -> tuple[str, int] | str:
    """Return (name, version) for name:vN / name@N, else the raw UUID/string."""
    if ":v" in ref:
        name, _, version_text = ref.rpartition(":v")
        if name and version_text.isdigit():
            return name, int(version_text)
    if "@" in ref and not ref.startswith("@"):
        name, _, version_text = ref.rpartition("@")
        if name and version_text.isdigit():
            return name, int(version_text)
    return ref


def _resolve_policy_version_id(client: CoworldApiClient, ref: str) -> str:
    parsed = _parse_policy_ref(ref)
    if isinstance(parsed, str):
        return parsed
    name, version = parsed
    row = client.lookup_policy_version(name=name, version=version)
    if row is None:
        raise typer.BadParameter(f"policy version not found (mine): {name}:v{version}")
    return str(row.id)


@counterfactual_app.command("create")
def counterfactual_create(
    candidate: Annotated[
        str,
        typer.Argument(help="Candidate policy: name:vN (e.g. ctf-autoresearch:v47) or policy_version UUID."),
    ],
    baseline: Annotated[
        str,
        typer.Argument(help="Baseline policy: name:vN or policy_version UUID."),
    ],
    league: Annotated[
        str,
        typer.Option("--league", "-l", help="League name (e.g. Ctf) or league_… id."),
    ],
    n: Annotated[
        int | None,
        typer.Option("--n", help="Number of matched fields (defaults to league default_n)."),
    ] = None,
    idempotency_key: Annotated[
        str | None,
        typer.Option("--idempotency-key", help="Idempotency key (default: generated)."),
    ] = None,
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    """Start a measurement counterfactual eval of candidate vs baseline on a league."""
    with CoworldApiClient.from_login(server_url=server) as client:
        candidate_id = _resolve_policy_version_id(client, candidate)
        baseline_id = _resolve_policy_version_id(client, baseline)
        league_id = resolve_league_id(client, league)
        key = (
            idempotency_key or f"cli:{candidate_id}:{baseline_id}:{league_id}:{int(time.time())}:{uuid.uuid4().hex[:8]}"
        )
        result = client.create_counterfactual_eval(
            candidate_policy_version_id=candidate_id,
            baseline_policy_version_id=baseline_id,
            league_id=league_id,
            n=n,
            idempotency_key=key,
        )
    if json_output:
        emit_json(result)
        return
    cf_id = result["id"]
    detail_url = observatory_web_url(server, f"/observatory/v2?detail=counterfactual-eval:{cf_id}")
    console.print(f"[green]Created[/green] {cf_id}  status={result.get('status')}")
    console.print(f"[dim]candidate[/dim] {candidate_id}")
    console.print(f"[dim]baseline[/dim]  {baseline_id}")
    console.print(f"[dim]league[/dim]    {league_id}")
    console.print(f"[dim]UI[/dim]        {detail_url}", soft_wrap=True)


@counterfactual_app.command("get")
def counterfactual_get(
    counterfactual_eval_id: Annotated[str, typer.Argument(help="cfeval_… id")],
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    with CoworldApiClient.from_login(server_url=server) as client:
        result = client.get_counterfactual_eval(counterfactual_eval_id)
    if json_output:
        emit_json(result)
        return
    console.print(
        f"{result['id']}  status={result.get('status')}  verdict={result.get('verdict')}  "
        f"n_paired={result.get('n_paired')}/{result.get('n_requested')}"
    )
    if result.get("skip_reason"):
        console.print(f"[yellow]skip[/yellow] {result['skip_reason']}")
    if result.get("error"):
        console.print(f"[red]error[/red] {result['error']}")
    detail_url = observatory_web_url(server, f"/observatory/v2?detail=counterfactual-eval:{result['id']}")
    console.print(f"[dim]UI[/dim] {detail_url}", soft_wrap=True)


@league_app.command("create")
def league_create(
    coworld_name: Annotated[str, typer.Argument(help="Canonical coworld name to promote into a league.")],
    league_key: Annotated[str, typer.Argument(help="Stable key for this league within the Coworld.")],
    league_name: Annotated[str, typer.Argument(help="Human-readable league name.")],
    default_variant_id: Annotated[
        str | None,
        typer.Option(
            "--default-variant",
            help="Commissioner default variant. Omit to use the manifest's first variant.",
        ),
    ] = None,
    template: Annotated[
        str,
        typer.Option(
            "--template",
            "-t",
            help=(
                "Temporary seed template. Defaults to commissioner_driven; legacy values are "
                "default | social_deduction | cogs_vs_clips | four_score."
            ),
        ),
    ] = "commissioner_driven",
    overrides: Annotated[
        list[str] | None,
        typer.Option("--set", help="Override KEY=VALUE (VALUE parsed as JSON when possible). Repeatable."),
    ] = None,
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    override_map = dict(_parse_override(item) for item in overrides) if overrides else None
    with CoworldUploadClient.from_login(server_url=server) as client:
        seed = client.create_league_seed(
            coworld_name=coworld_name,
            league_key=league_key,
            league_name=league_name,
            default_variant_id=default_variant_id,
            template=template,
            overrides=override_map,
        )
    if json_output:
        emit_json(seed.model_dump(mode="json"))
        return
    console.print(
        f"[green]Created league seed[/green] [bold]{seed.league_name}[/bold] "
        f"({seed.coworld_name}/{seed.league_key}, default variant: {seed.default_variant_id or 'manifest first'})"
    )
    if seed.league_id is not None:
        league_url = observatory_web_url(server, f"/observatory/v2?detail=league:{seed.league_id}")
        console.print(f"[dim]League:[/dim] {seed.league_id}")
        console.print(f"[dim]League page:[/dim] {league_url}", soft_wrap=True)
    else:
        console.print(
            "[yellow]No league materialized yet; reconcile creates it once the coworld is canonical.[/yellow]"
        )
    if (seed.overrides or {}).get("commissioner_key") == "platform":
        console.print(
            "[yellow]Platform ladder league — it schedules nothing yet.[/yellow] Declare divisions "
            "(PUT /v2/leagues/{league_id}/divisions), then POST /v2/leagues/{league_id}/settings "
            "with ladder.enabled = true."
        )


@league_app.command("list")
def league_list(
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    with CoworldUploadClient.from_login(server_url=server) as client:
        seeds = client.list_league_seeds()
    if json_output:
        emit_json([seed.model_dump(mode="json") for seed in seeds])
        return
    table = Table(box=box.SIMPLE)
    table.add_column("Coworld")
    table.add_column("Key")
    table.add_column("Name")
    table.add_column("Variant")
    table.add_column("Template")
    table.add_column("Enabled")
    table.add_column("League")
    for seed in seeds:
        table.add_row(
            seed.coworld_name,
            seed.league_key,
            seed.league_name,
            seed.default_variant_id or "manifest first",
            seed.template,
            "yes" if seed.enabled else "no",
            seed.league_id or "-",
        )
    console.print(table)
    if seeds:
        console.print("[bold]Seed IDs[/bold]")
        for seed in seeds:
            console.print(f"{seed.id}  {seed.coworld_name}/{seed.league_key}")


@league_app.command("rebind")
def league_rebind(
    plan_path: Annotated[
        Path,
        typer.Argument(help="JSON file containing a changes list or an object with a changes field."),
    ],
    commit: Annotated[
        bool,
        typer.Option("--commit", help="Apply the validated batch. Omit for a read-only dry run."),
    ] = False,
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    raw_changes = payload.get("changes") if isinstance(payload, dict) else payload
    if not isinstance(raw_changes, list):
        raise typer.BadParameter("Plan must be a JSON list or an object with a changes list")
    changes = [CoworldLeagueSeedRebindChange.model_validate(change) for change in raw_changes]
    with CoworldUploadClient.from_login(server_url=server) as client:
        result = client.rebind_league_seeds(changes=changes, dry_run=not commit)
    if json_output:
        emit_json(result.model_dump(mode="json"))
    else:
        table = Table(box=box.SIMPLE)
        table.add_column("League")
        table.add_column("Current")
        table.add_column("Proposed")
        table.add_column("Status")
        for item in result.results:
            table.add_row(
                item.league_name,
                f"{item.current.coworld_name}/{item.current.league_key}:"
                f"{item.current.default_variant_id or 'manifest first'}"
                f" -> {item.current.effective_variant_id or 'unresolved'}",
                f"{item.proposed.coworld_name}/{item.proposed.league_key}:"
                f"{item.proposed.default_variant_id or 'manifest first'}"
                f" -> {item.proposed.effective_variant_id or 'unresolved'}",
                "; ".join(item.blocking_reasons) if item.blocking_reasons else "ready",
            )
        console.print(table)
        outcome = "[green]Applied[/green]" if result.applied else "Dry run complete" if not commit else "Not applied"
        console.print(outcome)
    if commit and not result.applied:
        raise typer.Exit(1)


@league_app.command("game-of-week")
def league_game_of_week(
    seed_id: Annotated[str, typer.Argument(help="League seed ID (lseed_…).")],
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    """Make this coworld's league the single Observatory game of the week."""
    with CoworldUploadClient.from_login(server_url=server) as client:
        seed = client.set_league_game_of_week(seed_id=seed_id)
    if json_output:
        emit_json(seed.model_dump(mode="json"))
        return
    console.print(f"[green]Game of the week[/green] is now [bold]{seed.league_name}[/bold]")


@league_app.command("update")
def league_update(
    seed_id: Annotated[str, typer.Argument(help="League seed ID (lseed_…).")],
    overrides: Annotated[
        list[str] | None,
        typer.Option(
            "--set",
            help="Replacement override KEY=VALUE (VALUE parsed as JSON when possible). Repeatable.",
        ),
    ] = None,
    default_variant_id: Annotated[
        str | None,
        typer.Option("--default-variant", help="Set the commissioner's default manifest variant."),
    ] = None,
    use_manifest_default: Annotated[
        bool,
        typer.Option("--use-manifest-default", help="Clear the configured default and use manifest order."),
    ] = False,
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    if default_variant_id is not None and use_manifest_default:
        raise typer.BadParameter("--default-variant and --use-manifest-default are mutually exclusive")
    if not overrides and default_variant_id is None and not use_manifest_default:
        raise typer.BadParameter("Provide --set, --default-variant, or --use-manifest-default")
    override_map = dict(_parse_override(item) for item in overrides) if overrides else None
    with CoworldUploadClient.from_login(server_url=server) as client:
        seed = client.update_league_seed(
            seed_id=seed_id,
            overrides=override_map,
            default_variant_id=default_variant_id,
            clear_default_variant=use_manifest_default,
        )
    if json_output:
        emit_json(seed.model_dump(mode="json"))
        return
    console.print(f"[green]Updated league seed[/green] for [bold]{seed.league_name}[/bold]")
    if seed.league_id is not None:
        console.print(f"[dim]League:[/dim] {seed.league_id}")


@secret_app.command("put")
def secret_put(
    coworld_name: Annotated[str, typer.Argument(help="Coworld game name or cow_... id.")],
    secret_name: Annotated[str, typer.Argument(help="Secret name referenced as secret://coworld/<coworld>/<secret>.")],
    secret_path: Annotated[Path, typer.Argument(help="Local file containing the secret bytes.")],
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    body = secret_path.read_bytes()
    with CoworldUploadClient.from_login(server_url=server) as client:
        secret = client.put_coworld_secret(coworld_name=coworld_name, secret_name=secret_name, body=body)
    if json_output:
        emit_json(secret.model_dump(mode="json"))
        return
    console.print(
        f"[green]Uploaded secret[/green] [bold]{secret.secret_name}[/bold] for "
        f"[bold]{secret.coworld_name}[/bold] owned by [bold]{secret.owner_user_id}[/bold] "
        f"({secret.size_bytes} bytes)"
    )


@secret_app.command("list")
def secret_list(
    coworld_name: Annotated[str, typer.Argument(help="Coworld game name or cow_... id.")],
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    with CoworldUploadClient.from_login(server_url=server) as client:
        secrets = client.list_coworld_secrets(coworld_name=coworld_name)
    if json_output:
        emit_json([secret.model_dump(mode="json") for secret in secrets])
        return
    table = Table(box=box.SIMPLE)
    table.add_column("Secret")
    table.add_column("Owner")
    table.add_column("Size")
    table.add_column("Updated")
    for secret in secrets:
        updated_at = secret.updated_at.isoformat() if secret.updated_at else "-"
        table.add_row(secret.secret_name, secret.owner_user_id, str(secret.size_bytes), updated_at)
    console.print(table)


@secret_app.command("delete")
def secret_delete(
    coworld_name: Annotated[str, typer.Argument(help="Coworld game name or cow_... id.")],
    secret_name: Annotated[str, typer.Argument(help="Secret name to delete.")],
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    with CoworldUploadClient.from_login(server_url=server) as client:
        secret = client.delete_coworld_secret(coworld_name=coworld_name, secret_name=secret_name)
    if json_output:
        emit_json(secret.model_dump(mode="json"))
        return
    console.print(
        f"[green]Deleted secret[/green] [bold]{secret.secret_name}[/bold] for "
        f"[bold]{secret.coworld_name}[/bold] owned by [bold]{secret.owner_user_id}[/bold]"
    )


# Player identity is a Softmax-platform concept; the commands live in
# softmax-cli (`softmax player ...`) and are mounted here for discoverability.
app.add_typer(player_app, name="player")


@app.callback()
def main(
    elevated: Annotated[
        bool,
        typer.Option(
            "--elevated",
            # Hidden from `coworld --help`: this flag only functions for Softmax team
            # members, and shipping it in the public help surface would be noise for the
            # much larger external-user population. Employees learn about it through
            # internal docs. Matches how team-only subapps like `coworld league` are
            # public in name but understood internally.
            hidden=True,
            help=(
                "Attach X-Use-Elevated-Privileges to every backend call. Softmax team members "
                "need this for team-only endpoints (private leagues, cross-user artifacts, "
                "SQL access). No-op for external users. Rejected for player-subject tokens."
            ),
        ),
    ] = False,
) -> None:
    """Validate, certify, and play Coworld packages."""
    from coworld.api_client import CoworldApiClient  # noqa: PLC0415

    CoworldApiClient.set_elevated(elevated)
    CoworldUploadClient.set_elevated(elevated)


@app.command("certify", cls=_DockerCommand)
def certify(
    manifest_uri: Annotated[str, typer.Argument(help="Path, URI, or Coworld ID for coworld_manifest.json.")],
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=1.0)] = 60.0,
    open_report: Annotated[
        bool,
        typer.Option(
            "--open-report/--no-open-report",
            help="Open the generated certification transcript report in the browser.",
        ),
    ] = True,
) -> None:
    transcript = load_executable_transcript()
    step_results: list[StepResult] = []
    artifacts = EpisodeArtifacts.create()

    def on_step(result: StepResult, step: TranscriptStep) -> None:
        marker = "run " if result.status == "running" else result.status
        typer.echo(f"  [{marker}] {result.id}: {step.checks}")
        if result.status in ("pass", "fail"):
            step_results.append(result)

    with _materialized_manifest_path(manifest_uri, server=server) as manifest_path:
        typer.echo(f"Certifying {manifest_uri} against transcript coworld-executable")
        try:
            result = certify_coworld(
                manifest_path,
                workspace=artifacts.workspace,
                timeout_seconds=timeout_seconds,
                on_step=on_step,
            )
            cache_certified_manifest(manifest_path)
        except Exception as exc:
            report = write_certification_report(
                manifest_uri=str(manifest_uri),
                transcript=transcript,
                step_results=step_results,
                artifacts=artifacts,
                error=str(exc) or exc.__class__.__name__,
            )
            typer.echo(f"Certification failed for {manifest_uri}")
            failed_step = next((step for step in reversed(step_results) if step.status == "fail"), None)
            if failed_step is not None:
                typer.echo(f"Failed step: {failed_step.id}")
                typer.echo(f"Failure reason: {failed_step.failure_reason or 'step_failed'}")
                if failed_step.feedback:
                    typer.echo(f"Details: {failed_step.feedback}")
            else:
                typer.echo(f"Details: {exc}")
            typer.echo(f"Transcript report: {report.uri}")
            typer.echo(f"Artifacts: {artifacts.workspace}")
            if open_report:
                webbrowser.open(report.uri)
            raise typer.Exit(1) from exc
    transcript_report = write_certification_report(
        manifest_uri=str(manifest_uri),
        transcript=result.transcript,
        step_results=result.step_results,
        artifacts=result.artifacts,
        reporter_references=result.reporter_references,
    )
    typer.echo(f"Certified {manifest_uri}")
    typer.echo(f"Transcript: {result.transcript.name} ({len(result.step_results)} steps passed)")
    typer.echo(f"Transcript report: {transcript_report.uri}")
    typer.echo(f"Artifacts: {result.artifacts.workspace}")
    typer.echo(f"Results: {result.artifacts.results_path}")
    _echo_replay_paths(result.artifacts)
    uses_static_replay_viewer_bundle = _uses_static_replay_viewer_bundle(result)
    if uses_static_replay_viewer_bundle:
        typer.echo("Replay liveness: skipped (static replay bundle declared; /client/replay and /replay not required)")
    else:
        typer.echo("Replay liveness: verified /client/replay and /replay")
    typer.echo(f"Logs: {result.artifacts.logs_dir}")
    for reference_line in result.reporter_references:
        typer.echo(f"Reporter reference: {reference_line}")
    _echo_feedback_commands(
        manifest_uri,
        result.artifacts,
        server=server,
        uses_static_replay_viewer_bundle=uses_static_replay_viewer_bundle,
    )
    if open_report:
        webbrowser.open(transcript_report.uri)


@app.command("build", cls=_DockerCommand)
def build(
    version: Annotated[str, typer.Option("--version", help="Version to write into the hydrated manifest.")],
    project_dir: Annotated[
        Path,
        typer.Option(
            "--project",
            help="Coworld project directory containing compose.yaml and coworld_manifest_template.json.",
        ),
    ] = Path("."),
    compose_file: Annotated[
        Path,
        typer.Option("--compose", help="Compose filename, relative to the project directory."),
    ] = Path("compose.yaml"),
    template_path: Annotated[
        Path,
        typer.Option("--template", help="Manifest template filename, relative to the project directory."),
    ] = Path("coworld_manifest_template.json"),
    output_path: Annotated[
        Path,
        typer.Option("--output", help="Output filename, relative to the project directory."),
    ] = Path("dist/coworld_manifest.json"),
) -> None:
    project_dir = project_dir.resolve()
    manifest_path = build_coworld_manifest(
        project_dir / compose_file,
        project_dir / template_path,
        version,
        project_dir / output_path,
    )
    typer.echo(f"Built Coworld manifest: {manifest_path}")


@app.command("play", cls=_DockerCommand)
def play(
    manifest_uri: Annotated[str, typer.Argument(help="Path, URI, or Coworld ID for coworld_manifest.json.")],
    episode_request_or_player_images: Annotated[
        list[str] | None,
        typer.Argument(
            help=(
                "Optional episode_request.json, or local player image override(s). One image is reused for every "
                "player slot; otherwise provide one image per slot."
            )
        ),
    ] = None,
    run: Annotated[
        list[str] | None,
        typer.Option("--run", help="Command argv for supplied player image(s)."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", "-o", help="Directory for play artifacts."),
    ] = None,
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    variant_id: Annotated[
        str | None,
        typer.Option(
            "--variant",
            help="Coworld variant ID to play. Defaults to the certification fixture.",
        ),
    ] = None,
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=1.0, help="Episode timeout.")] = 3600.0,
    player_exit_timeout_seconds: Annotated[
        float,
        typer.Option(
            "--player-exit-timeout-seconds",
            min=1.0,
            help="Seconds to wait for player containers to exit after the game ends.",
        ),
    ] = DEFAULT_PLAYER_EXIT_TIMEOUT_SECONDS,
    use_bedrock: Annotated[
        bool,
        typer.Option(
            "--use-bedrock",
            help="Enable AWS Bedrock access for player containers using host AWS credentials.",
        ),
    ] = False,
    aws_profile: Annotated[
        str | None,
        typer.Option("--aws-profile", help="AWS profile to use when resolving --use-bedrock credentials."),
    ] = None,
    aws_region: Annotated[
        str | None,
        typer.Option("--aws-region", help="AWS region to use for --use-bedrock player containers."),
    ] = None,
    secret_env: Annotated[
        list[str] | None,
        typer.Option(
            "--secret-env",
            help="Secret environment variable for player containers (KEY=VALUE, can be repeated).",
        ),
    ] = None,
    open_browser: Annotated[
        bool,
        typer.Option("--open-browser/--no-open-browser", help="Open the global viewer in a browser."),
    ] = True,
) -> None:
    if not use_bedrock and (aws_profile is not None or aws_region is not None):
        raise typer.BadParameter("--aws-profile and --aws-region require --use-bedrock")
    validate_run_argv(run)
    parsed_secret_env: dict[str, str] = {}
    if secret_env:
        for kv in secret_env:
            key, val = _parse_secret_env(kv)
            parsed_secret_env[key] = val
    episode_request_path, player_images = _split_episode_request_and_player_images(episode_request_or_player_images)
    if episode_request_path is not None and (variant_id is not None or run):
        raise typer.BadParameter("episode request files cannot be combined with --variant or --run")

    def on_ready(session: PlaySession) -> None:
        _print_play_session(session)
        if open_browser:
            webbrowser.open(session.links.global_)

    with _materialized_manifest_path(manifest_uri, server=server) as manifest_path:
        result = play_coworld(
            manifest_path,
            variant_id=variant_id,
            episode_request_path=episode_request_path,
            player_images=player_images,
            player_run=run,
            workspace=output_dir.resolve() if output_dir is not None else None,
            use_bedrock=use_bedrock,
            aws_profile=aws_profile,
            aws_region=aws_region,
            secret_env=parsed_secret_env or None,
            timeout_seconds=timeout_seconds,
            player_exit_timeout_seconds=player_exit_timeout_seconds,
            on_ready=on_ready,
        )
    typer.echo(f"Artifacts: {result.session.artifacts.workspace}")
    typer.echo(f"Results: {result.session.artifacts.results_path}")
    _echo_replay_paths(result.session.artifacts)
    typer.echo(f"Logs: {result.session.artifacts.logs_dir}")
    _echo_feedback_commands(
        manifest_uri,
        result.session.artifacts,
        server=server,
        uses_static_replay_viewer_bundle=_uses_static_replay_viewer_bundle(result),
    )


@app.command("list")
def list_coworlds(
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    limit: Annotated[int, typer.Option("--limit", min=1, max=500, help="Maximum rows to return.")] = 200,
    cursor: Annotated[str | None, typer.Option("--cursor", help="Resume after a previous page's next cursor.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    with CoworldUploadClient.from_login(server_url=server) as client:
        page = client.list_coworlds(limit=limit, cursor=cursor)
    if json_output:
        emit_json(page.model_dump(mode="json"))
        return
    _print_coworld_table(page.entries)
    if page.next_cursor is not None:
        typer.echo(f"More rows available. Pass --cursor {page.next_cursor} to continue.")


@app.command("deploy-audit")
def deploy_audit(
    owner: Annotated[
        str, typer.Option("--owner", help="GitHub organization or owner to inspect.")
    ] = DEFAULT_GITHUB_OWNER,
    repo_prefix: Annotated[
        str,
        typer.Option("--repo-prefix", help="Repository prefix to discover when --repo is not passed."),
    ] = DEFAULT_REPO_PREFIX,
    repositories: Annotated[
        list[str] | None,
        typer.Option("--repo", help="Repository name to inspect. Repeat to avoid org-wide discovery."),
    ] = None,
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    skip_coworld_registry: Annotated[
        bool,
        typer.Option("--skip-coworld-registry", help="Only inspect GitHub workflow state."),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Print machine-readable audit JSON.")] = False,
    fail_on_alert: Annotated[
        bool,
        typer.Option("--fail-on-alert", help="Exit non-zero when the audit finds deploy alerts."),
    ] = False,
) -> None:
    result = audit_coworld_deployments(
        owner=owner,
        repo_prefix=repo_prefix,
        repositories=repositories,
        github_token=github_token_from_env(),
        server=server,
        include_coworld_registry=not skip_coworld_registry,
    )
    if json_output:
        emit_json(result.model_dump(mode="json"))
    else:
        typer.echo(format_deploy_audit_markdown(result), nl=False)
    if fail_on_alert and result.alerts:
        raise typer.Exit(1)


@app.command("next-version")
def next_version(
    coworld_name: Annotated[str, typer.Argument(help="Coworld name.")],
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
) -> None:
    with CoworldUploadClient.from_login(server_url=server) as client:
        latest_version = max(
            (Version(coworld.version) for coworld in client.iter_coworlds_by_name(coworld_name)),
            default=None,
        )
    if latest_version is None:
        console.print(f"[red]Coworld not found: {coworld_name}. Pass an explicit version instead.[/red]")
        raise typer.Exit(1)
    release = latest_version.release
    typer.echo(".".join(str(part) for part in (*release[:-1], release[-1] + 1)))


@app.command("show")
def show_coworld(
    coworld_id: Annotated[str, typer.Argument(help="Coworld ID to inspect.")],
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    with CoworldUploadClient.from_login(server_url=server) as client:
        coworld = client.find_coworld(coworld_id)
    if coworld is None:
        console.print("[red]Coworld not found[/red]")
        raise typer.Exit(1)
    if json_output:
        emit_json(coworld.model_dump(mode="json"))
        return
    _print_coworld_detail(coworld)


@app.command("status")
def status_coworld(
    coworld_id: Annotated[str, typer.Argument(help="Coworld ID to inspect.")],
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    wait_hosted_smoke: Annotated[
        bool,
        typer.Option(
            "--wait-hosted-smoke/--no-wait-hosted-smoke",
            help="Wait for hosted smoke certification to finish before printing status.",
        ),
    ] = False,
    hosted_smoke_timeout_seconds: Annotated[
        float,
        typer.Option("--hosted-smoke-timeout-seconds", min=1.0, help="Maximum time to wait for hosted smoke."),
    ] = 1800.0,
    json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    result = coworld_status(
        coworld_id,
        server=server,
        wait_for_hosted_smoke=wait_hosted_smoke,
        timeout_seconds=hosted_smoke_timeout_seconds,
    )
    if json_output:
        emit_json(
            {
                "coworld": result.coworld.model_dump(mode="json"),
                "hosted_smoke_episodes": [episode.model_dump() for episode in result.hosted_smoke_episodes],
                "certification": result.certification.model_dump(mode="json") if result.certification else None,
            }
        )
        return
    _print_coworld_status(result)


@app.command("retry-certification")
def retry_coworld_certification(
    coworld_id: Annotated[str, typer.Argument(help="Coworld ID to certify again.")],
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    with CoworldUploadClient.from_login(server_url=server) as client:
        certification = client.retry_coworld_certification(coworld_id)
    if json_output:
        emit_json(certification.model_dump(mode="json"))
        return
    typer.echo(f"Queued hosted certification retry for {coworld_id}")
    _print_certification_status(certification)
    typer.echo(f"Status: uv run coworld status {coworld_id}")


@app.command("images")
def images(
    image_id: Annotated[str | None, typer.Argument(help="Image ID to inspect. Lists images when omitted.")] = None,
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    limit: Annotated[int, typer.Option("--limit", min=1, max=500, help="Maximum rows to return.")] = 200,
    cursor: Annotated[str | None, typer.Option("--cursor", help="Resume after a previous page's next cursor.")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    with CoworldUploadClient.from_login(server_url=server) as client:
        if image_id is None:
            page = client.list_images(limit=limit, cursor=cursor)
            if json_output:
                emit_json(page.model_dump(mode="json"))
                return
            _print_image_table(page.entries)
            if page.next_cursor is not None:
                typer.echo(f"More rows available. Pass --cursor {page.next_cursor} to continue.")
            return
        image = client.get_image(image_id)
    if json_output:
        emit_json(image.model_dump(mode="json"))
        return
    _print_image_detail(image)


@app.command("upload-coworld", cls=_DockerCommand)
def upload_coworld(
    manifest_path: Annotated[Path | None, typer.Argument(help="Path to coworld_manifest.json.")] = None,
    base_coworld: Annotated[
        str | None,
        typer.Option(
            "--from-coworld",
            help="Uploaded Coworld ID or canonical name to use as the base manifest for a partial update.",
        ),
    ] = None,
    version: Annotated[
        str | None,
        typer.Option("--version", help="Override game.version before upload."),
    ] = None,
    patch_update: Annotated[
        str | None,
        typer.Option(
            "--patch",
            help="JSON merge-patch object, or path to one, applied before --version and --image.",
        ),
    ] = None,
    image_updates: Annotated[
        list[str] | None,
        typer.Option(
            "--image",
            help=(
                "Set a runnable image as TARGET=IMAGE. TARGET can be game, role.id, role[index], "
                "or bare role when that role has one runnable. Repeatable."
            ),
        ),
    ] = None,
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=1.0)] = 60.0,
    wait_hosted_smoke: Annotated[
        bool,
        typer.Option(
            "--wait-hosted-smoke/--no-wait-hosted-smoke",
            help="Wait for hosted smoke certification after upload and fail if it fails.",
        ),
    ] = True,
    hosted_smoke_timeout_seconds: Annotated[
        float,
        typer.Option("--hosted-smoke-timeout-seconds", min=1.0, help="Maximum time to wait for hosted smoke."),
    ] = 1800.0,
    wait_certification: Annotated[
        bool,
        typer.Option(
            "--wait-certification/--no-wait-certification",
            help="Wait for the auto-queued hosted certification and stream step results. "
            "Exits 2 on a certification failure you control, 3 on platform failure/timeout.",
        ),
    ] = False,
    certification_timeout_seconds: Annotated[
        float,
        typer.Option("--certification-timeout-seconds", min=1.0, help="Maximum time to wait for certification."),
    ] = 1800.0,
) -> None:
    upload_coworld_cmd(
        manifest_path,
        base_coworld=base_coworld,
        server=server,
        timeout_seconds=timeout_seconds,
        version=version,
        patch_update=patch_update,
        image_updates=image_updates,
        wait_for_hosted_smoke=wait_hosted_smoke,
        hosted_smoke_timeout_seconds=hosted_smoke_timeout_seconds,
        wait_certification=wait_certification,
        certification_timeout_seconds=certification_timeout_seconds,
    )


@app.command("patch-commissioner", cls=_DockerCommand)
def patch_commissioner(
    coworld_name: Annotated[str, typer.Argument(help="Canonical Coworld name to patch.")],
    image: Annotated[str, typer.Argument(help="Commissioner image to upload.")],
    runnable_id: Annotated[
        str | None,
        typer.Option("--runnable-id", help="Commissioner runnable ID. Required when the manifest has multiple."),
    ] = None,
    version: Annotated[
        str | None,
        typer.Option("--version", help="Override the patched Coworld version. Defaults to the next patch version."),
    ] = None,
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
) -> None:
    patch_commissioner_cmd(
        coworld_name,
        image,
        runnable_id=runnable_id,
        version=version,
        server=server,
    )


@app.command("download", cls=_DockerCommand)
def download(
    coworld_ref: Annotated[
        str,
        typer.Argument(help="Coworld ID to download, or Coworld name to download its canonical version."),
    ],
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o", help="Directory for downloaded files.")] = Path(
        "./coworld"
    ),
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    refresh: Annotated[
        bool,
        typer.Option("--refresh", help="Re-fetch the Coworld and re-pull images even when it is already cached."),
    ] = False,
) -> None:
    download_coworld_cmd(
        coworld_ref,
        output_dir,
        server=server,
        refresh=refresh,
    )


@app.command("upload-policy", cls=_DockerCommand)
def upload_policy(
    image: Annotated[str, typer.Argument(help="Local Docker image to upload as a CoWorld policy.")],
    name: Annotated[
        str | None,
        typer.Option(
            "--name",
            "-n",
            help="Policy name override. Defaults to a unique name derived from the active or default player.",
        ),
    ] = None,
    run: Annotated[
        list[str] | None,
        typer.Option("--run", help="Command argv for images that contain multiple Coworld roles."),
    ] = None,
    secret_env: Annotated[
        list[str] | None,
        typer.Option(
            "--secret-env",
            help="Secret environment variable for policy execution (can be repeated). Stored in AWS Secrets Manager.",
        ),
    ] = None,
    tag: Annotated[
        list[str] | None,
        typer.Option(
            "--tag",
            help="Private tag for your own bookkeeping (KEY=VALUE, can be repeated), e.g. --tag purpose=test.",
        ),
    ] = None,
    use_bedrock: Annotated[
        bool,
        typer.Option(
            "--use-bedrock",
            help="Enable AWS Bedrock access for this policy. Sets USE_BEDROCK=true in policy environment.",
        ),
    ] = False,
    bedrock_model: Annotated[
        str | None,
        typer.Option(
            "--bedrock-model",
            help="Bedrock model ID for this policy. Requires --use-bedrock and sets BEDROCK_MODEL.",
        ),
    ] = None,
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
) -> None:
    if bedrock_model is not None and not use_bedrock:
        raise typer.BadParameter("--bedrock-model requires --use-bedrock")
    parsed_secret_env: dict[str, str] = {}
    if secret_env:
        for kv in secret_env:
            key, val = _parse_secret_env(kv)
            parsed_secret_env[key] = val
    if use_bedrock:
        parsed_secret_env["USE_BEDROCK"] = "true"
    if bedrock_model is not None:
        parsed_secret_env["BEDROCK_MODEL"] = bedrock_model
    parsed_tags: dict[str, str] = {}
    if tag:
        for kv in tag:
            key, val = _parse_secret_env(kv)
            parsed_tags[key] = val

    if name is None:
        user_token = softmax_auth.load_user_token(server=server)
        if user_token is None:
            raise RuntimeError(f"Not authenticated. Run: softmax login --server {server}")
        players = list_players(server=server, token=user_token)
        active_player_id = (
            softmax_auth.get_active_player_id(server=server)
            if softmax_auth.load_player_session(server=server) is not None
            else None
        )
        player = (
            next(player for player in players if player.is_default)
            if active_player_id is None
            else next(player for player in players if player.id == active_player_id)
        )
        player_name = player.name.replace(":", "-")[: _DEFAULT_POLICY_NAME_MAX_LENGTH - len(player.id) - 1]
        name = f"{player_name}-{player.id}"
    typer.echo(f"Policy name: {name}")

    upload_policy_cmd(
        image,
        name,
        run=run,
        secret_env=parsed_secret_env if parsed_secret_env else None,
        tags=parsed_tags if parsed_tags else None,
        server=server,
    )


@app.command("submit")
def submit(
    policy: Annotated[str, typer.Argument(help="Policy name, optionally with version suffix NAME:vN.")],
    league: Annotated[
        str,
        typer.Option(
            "--league",
            "-l",
            help="League id.",
        ),
    ],
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    open_browser: Annotated[
        bool,
        typer.Option("--open-browser/--no-open-browser", help="Open the policy page in a browser after submitting."),
    ] = True,
    player: Annotated[
        str | None,
        typer.Option(
            "--player",
            help=(
                "Submit as this player id (ply_...). Defaults to the account's default player; "
                "list yours with GET /players. The player must belong to you."
            ),
        ),
    ] = None,
    auto_champion: Annotated[
        AutoChampion,
        typer.Option(
            "--auto-champion",
            help="Champion promotion mode after the policy qualifies.",
        ),
    ] = AutoChampion.always,
    preference: Annotated[
        list[str] | None,
        typer.Option(
            "--preference",
            help="Submission preference as KEY=VALUE. Repeat for multiple values; JSON values are decoded.",
        ),
    ] = None,
) -> None:
    preferences = dict(_parse_override(value) for value in preference) if preference is not None else None
    submit_policy_to_league_cmd(
        policy,
        league_id=league,
        server=server,
        open_browser=open_browser,
        auto_champion=auto_champion,
        preferences=preferences,
        player_id=player,
    )


@app.command("run-episode", cls=_DockerCommand, help="Run one or more headless local episodes.")
def run_episode(
    manifest_uri: Annotated[str, typer.Argument(help="Path, URI, or Coworld ID for coworld_manifest.json.")],
    episode_request_or_player_images: Annotated[
        list[str] | None,
        typer.Argument(
            help=(
                "Optional episode_request.json, or target policy/player container image override(s). One image is "
                "reused for every player slot; otherwise provide one image per slot."
            )
        ),
    ] = None,
    run: Annotated[
        list[str] | None,
        typer.Option("--run", help="Command argv for supplied player image(s)."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir",
            "-o",
            help=(
                "Directory for episode artifacts. Defaults to ./coworld/<coworld-id>/results for downloaded "
                "Coworlds, or results next to coworld_manifest.json for ordinary local manifests."
            ),
        ),
    ] = None,
    episodes: Annotated[
        int,
        typer.Option(
            "--episodes",
            "-n",
            min=1,
            help=(
                "Number of local episodes to run. With more than one, the game seed is incremented per episode "
                "and each episode's artifacts go in an episode-NNNN subdirectory."
            ),
        ),
    ] = 1,
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    variant_id: Annotated[
        str | None,
        typer.Option(
            "--variant",
            help="Coworld variant ID to run. Defaults to the certification fixture.",
        ),
    ] = None,
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=1.0)] = 3600.0,
    verify_replay: Annotated[bool, typer.Option("--verify-replay/--no-verify-replay")] = False,
    use_bedrock: Annotated[
        bool,
        typer.Option(
            "--use-bedrock",
            help="Enable AWS Bedrock access for player containers using host AWS credentials.",
        ),
    ] = False,
    aws_profile: Annotated[
        str | None,
        typer.Option("--aws-profile", help="AWS profile to use when resolving --use-bedrock credentials."),
    ] = None,
    aws_region: Annotated[
        str | None,
        typer.Option("--aws-region", help="AWS region to use for --use-bedrock player containers."),
    ] = None,
    secret_env: Annotated[
        list[str] | None,
        typer.Option(
            "--secret-env",
            help="Secret environment variable for player containers (KEY=VALUE, can be repeated).",
        ),
    ] = None,
) -> None:
    if not use_bedrock and (aws_profile is not None or aws_region is not None):
        raise typer.BadParameter("--aws-profile and --aws-region require --use-bedrock")
    validate_run_argv(run)
    parsed_secret_env: dict[str, str] = {}
    if use_bedrock:
        parsed_secret_env.update(_resolve_bedrock_aws_env(aws_profile=aws_profile, aws_region=aws_region).container_env)
    if secret_env:
        for kv in secret_env:
            key, val = _parse_secret_env(kv)
            parsed_secret_env[key] = val
    episode_request_path, player_images = _split_episode_request_and_player_images(episode_request_or_player_images)
    if episode_request_path is not None and (variant_id is not None or run):
        raise typer.BadParameter("episode request files cannot be combined with --variant or --run")
    with _materialized_manifest_path(manifest_uri, server=server) as manifest_path:
        package = load_coworld_package(manifest_path, tolerate_newer_fields=True)
        if episode_request_path is None:
            spec = build_manifest_episode_job_spec(
                package,
                variant_id=variant_id,
                player_images=player_images,
                player_run=run,
            )
        else:
            spec = load_manifest_episode_job_spec(package, episode_request_path)
        parsed_manifest_uri = urlparse(manifest_uri)
        if output_dir is not None:
            artifacts_dir = output_dir
        elif manifest_path.name == "coworld_manifest.json" and manifest_path.parent.name.startswith("cow_"):
            artifacts_dir = manifest_path.parent / "results"
        elif (manifest_uri.startswith("cow_") and "/" not in manifest_uri) or parsed_manifest_uri.path.startswith(
            "/v2/coworlds/"
        ):
            artifacts_dir = Path("./coworld") / Path(parsed_manifest_uri.path).name / "results"
        elif parsed_manifest_uri.scheme in ("http", "https"):
            artifacts_dir = Path("./coworld-results")
        else:
            artifacts_dir = manifest_path.parent / "results"
    artifacts_root = artifacts_dir.resolve()
    for index in range(episodes):
        episode_spec = spec
        if index > 0 and "seed" in spec.game_config and isinstance(spec.game_config["seed"], int):
            game_config = dict(spec.game_config)
            game_config["seed"] += index
            episode_spec = spec.model_copy(deep=True, update={"game_config": game_config})
        workspace = artifacts_root if episodes == 1 else artifacts_root / f"episode-{index + 1:04d}"
        artifacts = EpisodeArtifacts.create(workspace, prefix="coworld-run-")
        if episodes > 1:
            typer.echo(f"Episode {index + 1}/{episodes}")
        run_coworld_episode(
            episode_spec,
            artifacts,
            timeout_seconds=timeout_seconds,
            verify_replay=verify_replay,
            container_prefix="coworld-run",
            **({"secret_env": parsed_secret_env} if parsed_secret_env else {}),
        )
        typer.echo(f"Artifacts: {artifacts.workspace}")
        typer.echo(f"Results: {artifacts.results_path}")
        _echo_results_summary(artifacts)
        _echo_replay_paths(artifacts)
        typer.echo(f"Logs: {artifacts.logs_dir}")
        _echo_feedback_commands(
            manifest_uri,
            artifacts,
            server=server,
            uses_static_replay_viewer_bundle=package.manifest.game.replay_viewer is not None,
        )
    if episodes > 1:
        typer.echo(f"Artifacts root: {artifacts_root}")


@app.command("scrimmage", cls=_DockerCommand, help="Run one local episode against a target policy container.")
def scrimmage(
    manifest_uri: Annotated[str, typer.Argument(help="Path, URI, or Coworld ID for coworld_manifest.json.")],
    target_player_image: Annotated[
        str,
        typer.Argument(
            help="Target policy/player container image. Reused for every player slot in the scrimmage episode."
        ),
    ],
    run: Annotated[list[str] | None, typer.Option("--run", help="Command argv for the target player image.")] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", "-o", help="Directory for episode artifacts."),
    ] = None,
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    variant_id: Annotated[
        str | None,
        typer.Option(
            "--variant",
            help="Coworld variant ID to scrimmage. Defaults to the certification fixture.",
        ),
    ] = None,
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=1.0)] = 3600.0,
    verify_replay: Annotated[bool, typer.Option("--verify-replay/--no-verify-replay")] = False,
    use_bedrock: Annotated[
        bool,
        typer.Option(
            "--use-bedrock",
            help="Enable AWS Bedrock access for player containers using host AWS credentials.",
        ),
    ] = False,
    aws_profile: Annotated[
        str | None,
        typer.Option("--aws-profile", help="AWS profile to use when resolving --use-bedrock credentials."),
    ] = None,
    aws_region: Annotated[
        str | None,
        typer.Option("--aws-region", help="AWS region to use for --use-bedrock player containers."),
    ] = None,
    secret_env: Annotated[
        list[str] | None,
        typer.Option(
            "--secret-env",
            help="Secret environment variable for player containers (KEY=VALUE, can be repeated).",
        ),
    ] = None,
) -> None:
    run_episode(
        manifest_uri,
        [target_player_image],
        run=run,
        output_dir=output_dir,
        episodes=1,
        server=server,
        variant_id=variant_id,
        timeout_seconds=timeout_seconds,
        verify_replay=verify_replay,
        use_bedrock=use_bedrock,
        aws_profile=aws_profile,
        aws_region=aws_region,
        secret_env=secret_env,
    )


@contextmanager
def _materialized_manifest_path(manifest_uri: str, *, server: str) -> Iterator[Path]:
    if manifest_uri.startswith("cow_") and "/" not in manifest_uri:
        cached_manifest_path = downloaded_coworld_manifest_path(Path("./coworld"), manifest_uri)
        if not cached_manifest_path.is_file():
            download_coworld_cmd(manifest_uri, Path("./coworld"), server=server)
        yield cached_manifest_path.resolve()
        return
    with materialized_manifest_path(manifest_uri, server=server) as manifest_path:
        yield manifest_path


def _split_episode_request_and_player_images(values: list[str] | None) -> tuple[Path | None, list[str] | None]:
    if not values:
        return None, None
    first_path = Path(values[0])
    if first_path.is_file() or first_path.suffix == ".json":
        if len(values) > 1:
            raise typer.BadParameter("episode request files cannot be combined with positional player image overrides")
        return first_path, None
    return None, values


@app.command("replay", cls=_DockerCommand)
def replay(
    manifest_uri: Annotated[str, typer.Argument(help="Path, URI, or Coworld ID for coworld_manifest.json.")],
    replay_uri: Annotated[str, typer.Argument(help="Path or URI to a replay artifact JSON file.")],
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=1.0, help="Health check timeout.")] = 60.0,
    open_browser: Annotated[
        bool,
        typer.Option("--open-browser/--no-open-browser", help="Open the replay viewer in a browser when ready."),
    ] = True,
) -> None:
    def on_ready(session: ReplaySession) -> None:
        print_replay_session(session)
        if open_browser:
            webbrowser.open(session.link)

    with materialized_manifest_path(manifest_uri, server=server) as manifest_path:
        with materialized_replay_path(replay_uri) as replay_path:
            session = replay_coworld(
                manifest_path,
                replay_path,
                timeout_seconds=timeout_seconds,
                on_ready=on_ready,
            )
    typer.echo(f"Logs: {session.artifacts.logs_dir}")


@app.command("optimize", cls=_DockerCommand)
def optimize(
    manifest_uri: Annotated[
        str | None,
        typer.Argument(
            help=(
                "Optional path, URI, or Coworld ID for coworld_manifest.json. When provided, the Coworld is "
                "imported into the workbench. Omit to open the default optimizer with no game preloaded."
            )
        ),
    ] = None,
    port: Annotated[int, typer.Option("--port", min=1, max=65535, help="Port for the optimizer dev server.")] = (
        DEFAULT_OPTIMIZER_PORT
    ),
    open_browser: Annotated[
        bool,
        typer.Option("--open-browser/--no-open-browser", help="Open the optimizer in a browser when ready."),
    ] = True,
    refresh: Annotated[
        bool,
        typer.Option("--refresh", help="Update the cached optimizer checkout before launching."),
    ] = False,
    optimizer_repo: Annotated[
        str | None,
        typer.Option("--optimizer-repo", help="GitHub URL of the optimizer to run. Overrides the manifest value."),
    ] = None,
    optimizer_ref: Annotated[
        str | None,
        typer.Option("--optimizer-ref", help="Git ref (branch or tag) of the optimizer to run."),
    ] = None,
    optimizer_dir: Annotated[
        Path | None,
        typer.Option("--optimizer-dir", help="Cache root for optimizer checkouts. Defaults to the XDG data dir."),
    ] = None,
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
) -> None:
    """Install and launch the local optimizer workbench, optionally preloaded with a Coworld."""
    install_root = optimizer_dir.resolve() if optimizer_dir is not None else None
    try:
        if manifest_uri is None:
            run_optimizer_session(
                None,
                port=port,
                open_browser=open_browser,
                refresh=refresh,
                optimizer_repo=optimizer_repo,
                optimizer_ref=optimizer_ref,
                install_root=install_root,
            )
            return
        with _materialized_manifest_path(manifest_uri, server=server) as manifest_path:
            run_optimizer_session(
                manifest_path,
                port=port,
                open_browser=open_browser,
                refresh=refresh,
                optimizer_repo=optimizer_repo,
                optimizer_ref=optimizer_ref,
                install_root=install_root,
            )
    except OptimizerSetupError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1) from error


@hosted_game_app.command("create")
def hosted_game_create(
    coworld_id: Annotated[str, typer.Argument(help="Uploaded Coworld ID to host.")],
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    variant_id: Annotated[str | None, typer.Option("--variant", help="Coworld variant ID.")] = None,
    allow_spectators: Annotated[bool, typer.Option("--spectators/--no-spectators")] = True,
    json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    with CoworldUploadClient.from_login(server_url=server) as client:
        session = client.create_hosted_game(
            coworld_id=coworld_id,
            variant_id=variant_id,
            allow_spectators=allow_spectators,
        )
    if json_output:
        emit_json(session.model_dump(mode="json"))
        return
    typer.echo(f"Hosted game: {session.session_id}")
    typer.echo(f"Player slots: {session.player_count}")
    typer.echo(f"Player command: {_hosted_game_join_command(session.session_id, server)}")
    typer.echo(f"Lobby URL: {observatory_web_url(server, session.lobby_url)}")
    if allow_spectators:
        typer.echo(f"Spectator URL: {observatory_web_url(server, session.lobby_url)}")
    else:
        typer.echo("Spectators: disabled")


@hosted_game_app.command("join")
def hosted_game_join(
    session_id: Annotated[str, typer.Argument(help="Hosted play session ID.")],
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    with CoworldUploadClient.from_login(server_url=server) as client:
        join = client.join_hosted_game(session_id)
    if json_output:
        emit_json(join.model_dump(mode="json"))
        return
    if join.entrant_kind == "player":
        assert join.slot is not None
        assert join.player is not None
        typer.echo(f"Slot: {join.slot}")
        typer.echo(f"Player: {join.player.label}")
    else:
        assert join.spectator is not None
        typer.echo(f"Spectator: {join.spectator.label}")
    typer.echo(f"URL: {join.target_url}")


def _echo_replay_paths(artifacts: EpisodeArtifacts) -> None:
    typer.echo(f"Replay: {artifacts.replay_path}")


def _echo_results_summary(artifacts: EpisodeArtifacts) -> None:
    if not artifacts.results_path.exists():
        return
    results = json.loads(artifacts.results_path.read_text(encoding="utf-8"))
    if (
        not isinstance(results, dict)
        or "scores" not in results
        or not isinstance(results["scores"], list)
        or not results["scores"]
    ):
        return
    score_labels = [f"{index}={score}" for index, score in enumerate(results["scores"])]
    typer.echo("Scores: " + ", ".join(score_labels))


def _echo_feedback_commands(
    manifest_uri: str,
    artifacts: EpisodeArtifacts,
    *,
    server: str,
    uses_static_replay_viewer_bundle: bool,
) -> None:
    if uses_static_replay_viewer_bundle:
        typer.echo(
            f"Inspect replay: open {artifacts.replay_path} in your static replay viewer bundle "
            "(see STATIC_REPLAY_VIEWERS.md)"
        )
    else:
        replay_command = ["uv", "run", "coworld", "replay", manifest_uri, str(artifacts.replay_path)]
        if server.rstrip("/") != DEFAULT_SUBMIT_SERVER.rstrip("/"):
            replay_command.extend(["--server", server])
        typer.echo("Inspect replay: " + shlex.join(replay_command))
    typer.echo("Inspect logs: " + shlex.join(["ls", str(artifacts.logs_dir)]))


def _uses_static_replay_viewer_bundle(result: object) -> bool:
    package = getattr(result, "package", None)
    if package is None:
        session = getattr(result, "session", None)
        package = getattr(session, "package", None) if session is not None else None
    manifest = getattr(package, "manifest", None) if package is not None else None
    game = getattr(manifest, "game", None) if manifest is not None else None
    replay_viewer = getattr(game, "replay_viewer", None) if game is not None else None
    return getattr(replay_viewer, "bundle", None) is not None


def _print_play_session(session: PlaySession) -> None:
    typer.echo(f"Artifacts: {session.artifacts.workspace}")
    typer.echo(f"Variant: {session.variant_id}")
    typer.echo(f"Player containers: {len(session.links.players)} launched")
    typer.echo("Player clients:")
    for slot, link in enumerate(session.links.players):
        typer.echo(f"  {slot}: {link}")
    typer.echo(f"Global client: {session.links.global_}")
    typer.echo(f"Admin client: {session.links.admin}")
    local_ports = getattr(session, "local_ports", [])
    if local_ports:
        typer.echo("Extra local ports:")
        for port in local_ports:
            typer.echo(f"  container {port.container_port}/tcp: {port.host}:{port.host_port}")
    typer.echo("Waiting for the game container to exit...")


def _hosted_game_join_command(session_id: str, server: str) -> str:
    command = ["uv", "run", "coworld", "hosted-game", "join", session_id]
    if server.rstrip("/") != DEFAULT_SUBMIT_SERVER.rstrip("/"):
        command.extend(["--server", server])
    return shlex.join(command)


def _print_coworld_table(coworlds: list[CoworldListEntry]) -> None:
    if not coworlds:
        console.print("[yellow]No uploaded Coworlds found.[/yellow]")
        return
    table = Table(title="Uploaded Coworlds", box=box.SIMPLE_HEAVY, show_lines=False, pad_edge=False)
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Version")
    table.add_column("Canonical")
    table.add_column("Size")
    table.add_column("Manifest Hash")
    for coworld in coworlds:
        table.add_row(
            coworld.id,
            coworld.name,
            coworld.version,
            "yes" if coworld.canonical else "no",
            f"{coworld.size_bytes} B",
            coworld.manifest_hash,
        )
    console.print(table)


def _print_coworld_detail(coworld: CoworldListEntry | CoworldUploadResponse) -> None:
    console.print(f"[bold]Coworld:[/bold] {coworld.id}")
    console.print(f"Name: {coworld.name}")
    console.print(f"Version: {coworld.version}")
    console.print(f"Canonical: {'yes' if coworld.canonical else 'no'}")
    console.print(f"Manifest hash: {coworld.manifest_hash}")
    console.print(f"Size: {coworld.size_bytes} bytes")


def _print_coworld_status(result: CoworldStatusResult) -> None:
    _print_coworld_detail(result.coworld)
    _print_certification_status(result.certification)
    if not result.hosted_smoke_episodes:
        console.print("Hosted smoke episodes: none")
        return
    if result.hosted_smoke_passed:
        console.print("Hosted smoke certification: passed")
    elif result.hosted_smoke_failed:
        console.print("[red]Hosted smoke certification: failed[/red]")
    else:
        console.print("[yellow]Hosted smoke certification: pending[/yellow]")
    table = Table(box=box.SIMPLE)
    table.add_column("Episode request")
    table.add_column("Status")
    table.add_column("Error")
    for episode in result.hosted_smoke_episodes:
        table.add_row(episode.id, episode.status, episode.error or "-")
    console.print(table)


def _print_certification_status(certification: CoworldCertificationStatus | None) -> None:
    if certification is None:
        return
    if certification.state == "certified":
        console.print(f"Hosted certification: certified ({certification.contract_version})")
    elif certification.state == "failed":
        console.print("[red]Hosted certification: failed[/red]")
        if certification.failed_step is not None:
            console.print(f"  Failed step: {certification.failed_step}")
        if certification.failure is not None:
            console.print(f"  Reason: {certification.failure.detail}")
            console.print(f"  Fix: {certification.failure.remediation}")
        console.print(f"  Retry: uv run coworld retry-certification {certification.coworld_id}")
    elif certification.state == "never_run":
        console.print("Hosted certification: never run")
    else:
        console.print(f"[yellow]Hosted certification: {certification.state}[/yellow]")
    for step in certification.transcript_summary:
        console.print(f"  {step.status:<4}  {step.id}")


def _print_image_table(images: list[ContainerImageResponse]) -> None:
    if not images:
        console.print("[yellow]No uploaded images found.[/yellow]")
        return
    table = Table(title="Uploaded Images", box=box.SIMPLE_HEAVY, show_lines=False, pad_edge=False)
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Version")
    table.add_column("Status")
    table.add_column("Public URI")
    for image in images:
        table.add_row(image.id, image.name, f"v{image.version}", image.status, image.public_image_uri or "")
    console.print(table)


def _print_image_detail(image: ContainerImageResponse) -> None:
    console.print(f"[bold]Image:[/bold] {image.id}")
    console.print(f"Name: {image.name}")
    console.print(f"Version: v{image.version}")
    console.print(f"Status: {image.status}")
    if image.client_hash is not None:
        console.print(f"Client hash: {image.client_hash}")
    if image.image_uri is not None:
        console.print(f"Image URI: {image.image_uri}")
    if image.image_digest is not None:
        console.print(f"Image digest: {image.image_digest}")
    if image.public_image_uri is not None:
        console.print(f"Public URI: {image.public_image_uri}")
