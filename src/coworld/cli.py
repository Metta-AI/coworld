from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from coworld.certifier import certify_coworld
from coworld.play import PlaySession, ReplaySession, play_coworld, replay_coworld

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)


@app.callback()
def main() -> None:
    """Validate, certify, and play Coworld packages."""


@app.command("certify")
def certify(
    manifest_path: Annotated[Path, typer.Argument(help="Path to coworld_manifest.json.")],
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=1.0)] = 60.0,
) -> None:
    result = certify_coworld(manifest_path, timeout_seconds=timeout_seconds)
    typer.echo(f"Certified {manifest_path}")
    typer.echo(f"Artifacts: {result.artifacts.workspace}")
    typer.echo(f"Results: {result.artifacts.results_path}")
    typer.echo(f"Replay: {result.artifacts.replay_path}")
    typer.echo(f"Logs: {result.artifacts.logs_dir}")


@app.command("play")
def play(
    manifest_path: Annotated[Path, typer.Argument(help="Path to coworld_manifest.json.")],
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=1.0, help="Health check timeout.")] = 60.0,
) -> None:
    result = play_coworld(manifest_path, timeout_seconds=timeout_seconds, on_ready=_print_play_session)
    typer.echo(f"Results: {result.session.artifacts.results_path}")
    typer.echo(f"Replay: {result.session.artifacts.replay_path}")
    typer.echo(f"Logs: {result.session.artifacts.logs_dir}")


@app.command("replay")
def replay(
    manifest_path: Annotated[Path, typer.Argument(help="Path to coworld_manifest.json.")],
    replay_path: Annotated[Path, typer.Argument(help="Path to a replay artifact JSON file.")],
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=1.0, help="Health check timeout.")] = 60.0,
) -> None:
    session = replay_coworld(
        manifest_path,
        replay_path,
        timeout_seconds=timeout_seconds,
        on_ready=_print_replay_session,
    )
    typer.echo(f"Logs: {session.artifacts.logs_dir}")


def _print_play_session(session: PlaySession) -> None:
    typer.echo(f"Artifacts: {session.artifacts.workspace}")
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
