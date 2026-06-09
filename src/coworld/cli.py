from __future__ import annotations

import json
import shlex
import webbrowser
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Iterator
from urllib.parse import urlparse

import typer
from rich import box
from rich.table import Table

from coworld.bundle import build_coworld_manifest
from coworld.certifier import (
    build_manifest_episode_job_spec,
    certify_coworld,
    load_coworld_package,
    load_manifest_episode_job_spec,
)
from coworld.cli_support import console, emit_json, observatory_web_url
from coworld.config import DEFAULT_OPTIMIZER_PORT, DEFAULT_SUBMIT_SERVER
from coworld.manifest_uri import materialized_manifest_path, materialized_replay_path
from coworld.optimizer.runtime import OptimizerSetupError, run_optimizer_session
from coworld.play import PlaySession, ReplaySession, _resolve_bedrock_aws_env, play_coworld, replay_coworld
from coworld.runner.runner import EpisodeArtifacts, run_coworld_episode
from coworld.submit import submit_policy_to_league_cmd
from coworld.tournament_cli import register_tournament_commands
from coworld.upload import (
    ContainerImageResponse,
    CoworldListEntry,
    CoworldUploadClient,
    CoworldUploadResponse,
    download_coworld_cmd,
    downloaded_coworld_manifest_path,
    upload_coworld_cmd,
    upload_policy_cmd,
)

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
register_tournament_commands(app)
hosted_game_app = typer.Typer(no_args_is_help=True, help="Create and join hosted Coworld games.")
app.add_typer(hosted_game_app, name="hosted-game")


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


league_app = typer.Typer(no_args_is_help=True, help="Create and inspect Coworld league seeds (team only).")
app.add_typer(league_app, name="league")


@league_app.command("create")
def league_create(
    coworld_name: Annotated[str, typer.Argument(help="Canonical coworld name to promote into a league.")],
    template: Annotated[
        str,
        typer.Option("--template", "-t", help="Template: default | social_deduction | cogs_vs_clips."),
    ] = "default",
    overrides: Annotated[
        list[str] | None,
        typer.Option("--set", help="Override KEY=VALUE (VALUE parsed as JSON when possible). Repeatable."),
    ] = None,
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    override_map = dict(_parse_override(item) for item in overrides) if overrides else None
    with CoworldUploadClient.from_login(server_url=server) as client:
        seed = client.create_league_seed(coworld_name=coworld_name, template=template, overrides=override_map)
    if json_output:
        emit_json(seed.model_dump(mode="json"))
        return
    console.print(
        f"[green]Created league seed[/green] for [bold]{seed.coworld_name}[/bold] (template: {seed.template})"
    )
    if seed.league_id is not None:
        league_url = observatory_web_url(server, f"/observatory/v2#tab=leagues&detail=league:{seed.league_id}")
        console.print(f"[dim]League:[/dim] {seed.league_id}")
        console.print(f"[dim]League page:[/dim] {league_url}", soft_wrap=True)
    else:
        console.print(
            "[yellow]No league materialized yet; reconcile creates it once the coworld is canonical.[/yellow]"
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
    table.add_column("Template")
    table.add_column("Enabled")
    table.add_column("League")
    for seed in seeds:
        table.add_row(
            seed.coworld_name,
            seed.template,
            "yes" if seed.enabled else "no",
            seed.league_id or "-",
        )
    console.print(table)


@app.callback()
def main() -> None:
    """Validate, certify, and play Coworld packages."""


@app.command("certify")
def certify(
    manifest_uri: Annotated[str, typer.Argument(help="Path, URI, or Coworld ID for coworld_manifest.json.")],
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=1.0)] = 60.0,
) -> None:
    with materialized_manifest_path(manifest_uri, server=server) as manifest_path:
        result = certify_coworld(manifest_path, timeout_seconds=timeout_seconds)
    typer.echo(f"Certified {manifest_uri}")
    typer.echo(f"Artifacts: {result.artifacts.workspace}")
    typer.echo(f"Results: {result.artifacts.results_path}")
    _echo_replay_paths(result.artifacts)
    typer.echo(f"Logs: {result.artifacts.logs_dir}")


@app.command("build")
def build(
    compose_file: Annotated[Path, typer.Argument(help="Path to the Coworld compose.yaml build file.")],
    template_path: Annotated[
        Path,
        typer.Argument(help="Path to coworld_manifest_template.json or coworld_manifest.json."),
    ],
    version: Annotated[str, typer.Argument(help="Version to write into the hydrated manifest.")],
    output_path: Annotated[Path, typer.Argument(help="Output path for coworld_manifest.json.")],
    resolve_mutable_images: Annotated[
        bool,
        typer.Option(
            "--resolve-mutable-images",
            help="Resolve mutable registry image refs such as ghcr.io/name:latest to immutable digest refs.",
        ),
    ] = False,
) -> None:
    manifest_path = build_coworld_manifest(
        compose_file,
        template_path,
        version,
        output_path,
        resolve_mutable_image_refs=resolve_mutable_images,
    )
    typer.echo(f"Built Coworld manifest: {manifest_path}")


@app.command("resolve-and-upload")
def resolve_and_upload(
    compose_file: Annotated[Path, typer.Argument(help="Path to the Coworld compose.yaml build file.")],
    template_path: Annotated[
        Path,
        typer.Argument(help="Path to coworld_manifest_template.json or coworld_manifest.json."),
    ],
    version: Annotated[str, typer.Argument(help="Version to write into the hydrated manifest.")],
    output_path: Annotated[Path, typer.Argument(help="Output path for the resolved coworld_manifest.json.")],
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=1.0)] = 60.0,
) -> None:
    manifest_path = build_coworld_manifest(
        compose_file,
        template_path,
        version,
        output_path,
        resolve_mutable_image_refs=True,
    )
    typer.echo(f"Built Coworld manifest: {manifest_path}")
    upload_coworld_cmd(
        manifest_path,
        server=server,
        timeout_seconds=timeout_seconds,
    )


@app.command("play")
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
            on_ready=on_ready,
        )
    typer.echo(f"Artifacts: {result.session.artifacts.workspace}")
    typer.echo(f"Results: {result.session.artifacts.results_path}")
    _echo_replay_paths(result.session.artifacts)
    typer.echo(f"Logs: {result.session.artifacts.logs_dir}")
    _echo_feedback_commands(manifest_uri, result.session.artifacts, server=server)


@app.command("list")
def list_coworlds(
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    limit: Annotated[int, typer.Option("--limit", min=1, max=500, help="Maximum rows to return.")] = 200,
    offset: Annotated[int, typer.Option("--offset", min=0, help="Rows to skip.")] = 0,
    json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    with CoworldUploadClient.from_login(server_url=server) as client:
        coworlds = client.list_coworlds(limit=limit, offset=offset)
    if json_output:
        emit_json([coworld.model_dump(mode="json") for coworld in coworlds])
        return
    _print_coworld_table(coworlds)


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


@app.command("images")
def images(
    image_id: Annotated[str | None, typer.Argument(help="Image ID to inspect. Lists images when omitted.")] = None,
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    limit: Annotated[int, typer.Option("--limit", min=1, max=500, help="Maximum rows to return.")] = 200,
    offset: Annotated[int, typer.Option("--offset", min=0, help="Rows to skip.")] = 0,
    json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    with CoworldUploadClient.from_login(server_url=server) as client:
        if image_id is None:
            image_list = client.list_images(limit=limit, offset=offset)
            if json_output:
                emit_json([image.model_dump(mode="json") for image in image_list])
                return
            _print_image_table(image_list)
            return
        image = client.get_image(image_id)
    if json_output:
        emit_json(image.model_dump(mode="json"))
        return
    _print_image_detail(image)


@app.command("upload-coworld")
def upload_coworld(
    manifest_path: Annotated[Path, typer.Argument(help="Path to coworld_manifest.json.")],
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=1.0)] = 60.0,
) -> None:
    upload_coworld_cmd(
        manifest_path,
        server=server,
        timeout_seconds=timeout_seconds,
    )


@app.command("download")
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


@app.command("upload-policy")
def upload_policy(
    image: Annotated[str, typer.Argument(help="Local Docker image to upload as a CoWorld policy.")],
    name: Annotated[str, typer.Option("--name", "-n", help="Policy name.")],
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

    upload_policy_cmd(
        image,
        name,
        run=run,
        secret_env=parsed_secret_env if parsed_secret_env else None,
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
) -> None:
    submit_policy_to_league_cmd(
        policy,
        league_id=league,
        server=server,
        open_browser=open_browser,
    )


@app.command("run-episode")
def run_episode(
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
    parsed_secret_env: dict[str, str] = {}
    if use_bedrock:
        parsed_secret_env.update(_resolve_bedrock_aws_env(aws_profile=aws_profile, aws_region=aws_region).container_env)
    if secret_env:
        for kv in secret_env:
            key, val = _parse_secret_env(kv)
            parsed_secret_env[key] = val
    episode_request_path, player_images = _split_episode_request_and_player_images(episode_request_or_player_images)
    if episode_request_path is not None and run:
        raise typer.BadParameter("episode request files cannot be combined with --run")
    with _materialized_manifest_path(manifest_uri, server=server) as manifest_path:
        package = load_coworld_package(manifest_path)
        if episode_request_path is None:
            spec = build_manifest_episode_job_spec(package, player_images=player_images, player_run=run)
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
        _echo_replay_paths(artifacts)
        typer.echo(f"Logs: {artifacts.logs_dir}")
        _echo_feedback_commands(manifest_uri, artifacts, server=server)
    if episodes > 1:
        typer.echo(f"Artifacts root: {artifacts_root}")


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


@app.command("replay")
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
        _print_replay_session(session)
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


@app.command("optimize")
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
    typer.echo(f"Player URL: {observatory_web_url(server, session.join_url)}")
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
    typer.echo(f"Slot: {join.slot}")
    typer.echo(f"Player: {join.player.label}")
    typer.echo(f"URL: {join.player_url}")


def _echo_replay_paths(artifacts: EpisodeArtifacts) -> None:
    typer.echo(f"Replay: {artifacts.replay_path}")


def _echo_feedback_commands(manifest_uri: str, artifacts: EpisodeArtifacts, *, server: str) -> None:
    replay_command = ["uv", "run", "coworld", "replay", manifest_uri, str(artifacts.replay_path)]
    if server.rstrip("/") != DEFAULT_SUBMIT_SERVER.rstrip("/"):
        replay_command.extend(["--server", server])
    typer.echo("Inspect replay: " + shlex.join(replay_command))
    typer.echo("Inspect logs: " + shlex.join(["ls", str(artifacts.logs_dir)]))


def _print_play_session(session: PlaySession) -> None:
    typer.echo(f"Artifacts: {session.artifacts.workspace}")
    typer.echo(f"Variant: {session.variant_id}")
    typer.echo(f"Player containers: {len(session.links.players)} launched")
    typer.echo("Player clients:")
    for slot, link in enumerate(session.links.players):
        typer.echo(f"  {slot}: {link}")
    typer.echo(f"Global client: {session.links.global_}")
    typer.echo(f"Admin client: {session.links.admin}")
    typer.echo("Waiting for the game container to exit...")


def _print_replay_session(session: ReplaySession) -> None:
    typer.echo(f"Artifacts: {session.artifacts.workspace}")
    typer.echo(f"Replay file: {session.replay_path}")
    typer.echo(f"Replay client: {session.link}")
    typer.echo("Waiting for the replay container to exit...")


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
