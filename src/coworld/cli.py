from __future__ import annotations

import shlex
import webbrowser
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse, urlunparse

import typer
from rich import box
from rich.table import Table

from coworld.certifier import build_manifest_episode_job_spec, certify_coworld, load_coworld_package
from coworld.cli_support import console, emit_json
from coworld.config import DEFAULT_SUBMIT_SERVER
from coworld.manifest_uri import materialized_manifest_path, materialized_replay_path
from coworld.play import PlaySession, ReplaySession, play_coworld, replay_coworld
from coworld.runner.runner import EpisodeArtifacts, run_coworld_episode
from coworld.starter_policy import (
    STARTER_POLICIES,
    STARTER_POLICY_ALIASES,
    write_starter_policy,
)
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
    typer.echo(f"Replay: {result.artifacts.replay_path}")
    typer.echo(f"Logs: {result.artifacts.logs_dir}")


@app.command("play")
def play(
    manifest_uri: Annotated[str, typer.Argument(help="Path, URI, or Coworld ID for coworld_manifest.json.")],
    player_images: Annotated[
        list[str] | None,
        typer.Argument(
            help=(
                "Optional local player image override. One image is reused for every player slot; otherwise provide "
                "one image per slot."
            )
        ),
    ] = None,
    run: Annotated[
        list[str] | None,
        typer.Option("--run", help="Command argv for supplied player image(s)."),
    ] = None,
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    variant_id: Annotated[
        str | None,
        typer.Option(
            "--variant",
            help="Coworld variant ID to play. Defaults to 'default' when present, otherwise the first variant.",
        ),
    ] = None,
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=1.0, help="Health check timeout.")] = 60.0,
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
    open_browser: Annotated[
        bool,
        typer.Option("--open-browser/--no-open-browser", help="Open the global viewer in a browser."),
    ] = True,
) -> None:
    if not use_bedrock and (aws_profile is not None or aws_region is not None):
        raise typer.BadParameter("--aws-profile and --aws-region require --use-bedrock")

    def on_ready(session: PlaySession) -> None:
        _print_play_session(session)
        if open_browser:
            webbrowser.open(session.links.global_)

    if manifest_uri.startswith("cow_") and "/" not in manifest_uri:
        cached_manifest_path = downloaded_coworld_manifest_path(Path("./coworld"), manifest_uri)
        if not cached_manifest_path.is_file():
            download_coworld_cmd(manifest_uri, Path("./coworld"), server=server)
        result = play_coworld(
            cached_manifest_path.resolve(),
            variant_id=variant_id,
            player_images=player_images,
            player_run=run,
            use_bedrock=use_bedrock,
            aws_profile=aws_profile,
            aws_region=aws_region,
            timeout_seconds=timeout_seconds,
            on_ready=on_ready,
        )
    else:
        with materialized_manifest_path(manifest_uri, server=server) as manifest_path:
            result = play_coworld(
                manifest_path,
                variant_id=variant_id,
                player_images=player_images,
                player_run=run,
                use_bedrock=use_bedrock,
                aws_profile=aws_profile,
                aws_region=aws_region,
                timeout_seconds=timeout_seconds,
                on_ready=on_ready,
            )
    typer.echo(f"Results: {result.session.artifacts.results_path}")
    typer.echo(f"Replay: {result.session.artifacts.replay_path}")
    typer.echo(f"Logs: {result.session.artifacts.logs_dir}")


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


@app.command("make-policy")
def make_policy(
    policy: Annotated[
        str,
        typer.Argument(help=f"Starter policy to copy. Choices: {', '.join(sorted(STARTER_POLICIES))}."),
    ],
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Output starter policy project directory."),
    ] = Path("amongthemstarter"),
) -> None:
    if policy not in STARTER_POLICY_ALIASES:
        choices = ", ".join(sorted(STARTER_POLICIES))
        console.print(f"[red]Unknown starter policy '{policy}'. Choices: {choices}[/red]")
        raise typer.Exit(1)
    if output.suffix:
        console.print(
            "[red]Among Them starter policy output must be a project directory, e.g. -o amongthemstarter[/red]"
        )
        raise typer.Exit(1)

    result = write_starter_policy(policy, output)

    console.print(f"[green]{result.display_name} starter policy copied to: {result.output_path}[/green]")
    console.print(f"[dim]Policy source: {result.source_path}[/dim]")
    console.print(
        "[dim]Build: "
        f"docker build --platform=linux/amd64 -t amongthemstarter:latest {shlex.quote(str(result.output_path))}"
        "[/dim]"
    )
    console.print("[dim]Guide: https://softmax.com/play_amongthem.md[/dim]")


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
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
) -> None:
    parsed_secret_env: dict[str, str] = {}
    if use_bedrock:
        parsed_secret_env["USE_BEDROCK"] = "true"
    if secret_env:
        for kv in secret_env:
            key, val = _parse_secret_env(kv)
            parsed_secret_env[key] = val

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
) -> None:
    submit_policy_to_league_cmd(
        policy,
        league_id=league,
        server=server,
    )


@app.command("run-episode")
def run_episode(
    manifest_uri: Annotated[str, typer.Argument(help="Path, URI, or Coworld ID for coworld_manifest.json.")],
    player_images: Annotated[
        list[str] | None,
        typer.Argument(
            help=(
                "Optional local player image override. One image is reused for every player slot; otherwise provide "
                "one image per slot."
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
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=1.0)] = 3600.0,
    verify_replay: Annotated[bool, typer.Option("--verify-replay/--no-verify-replay")] = False,
) -> None:
    with materialized_manifest_path(manifest_uri, server=server) as manifest_path:
        package = load_coworld_package(manifest_path)
        spec = build_manifest_episode_job_spec(package, player_images=player_images, player_run=run)
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
    artifacts = EpisodeArtifacts.create(artifacts_dir.resolve(), prefix="coworld-run-")
    run_coworld_episode(spec, artifacts, timeout_seconds=timeout_seconds, verify_replay=verify_replay)
    typer.echo(f"Artifacts: {artifacts.workspace}")
    typer.echo(f"Results: {artifacts.results_path}")
    typer.echo(f"Replay: {artifacts.replay_path}")
    typer.echo(f"Logs: {artifacts.logs_dir}")


@app.command("replay")
def replay(
    manifest_uri: Annotated[str, typer.Argument(help="Path, URI, or Coworld ID for coworld_manifest.json.")],
    replay_uri: Annotated[str, typer.Argument(help="Path or URI to a replay artifact JSON file.")],
    server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=1.0, help="Health check timeout.")] = 60.0,
) -> None:
    with materialized_manifest_path(manifest_uri, server=server) as manifest_path:
        with materialized_replay_path(replay_uri) as replay_path:
            session = replay_coworld(
                manifest_path,
                replay_path,
                timeout_seconds=timeout_seconds,
                on_ready=_print_replay_session,
            )
    typer.echo(f"Logs: {session.artifacts.logs_dir}")


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
    typer.echo(f"Player URL: {_observatory_web_url(server, session.join_url)}")
    if allow_spectators:
        typer.echo(f"Spectator URL: {_observatory_web_url(server, session.lobby_url)}")
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


def _observatory_web_url(server: str, path: str) -> str:
    if path.startswith(("http://", "https://")):
        return path
    if server.rstrip("/") == DEFAULT_SUBMIT_SERVER.rstrip("/"):
        return f"https://softmax.com{path}"

    parsed = urlparse(server)
    if parsed.path.rstrip("/") == "/api/observatory":
        origin = urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
        return f"{origin}{path}"
    return path


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
