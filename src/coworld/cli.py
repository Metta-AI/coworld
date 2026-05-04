from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from coworld.certifier import certify_coworld

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)


@app.callback()
def main() -> None:
    """Validate and certify Coworld packages."""


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
