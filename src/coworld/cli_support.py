from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import typer
from pydantic import BaseModel, Field
from rich.console import Console

console = Console()


class _DockerConfig(BaseModel):
    current_context: str = Field(default="default", alias="currentContext")


def active_docker_context() -> str:
    if docker_host := os.environ.get("DOCKER_HOST"):
        return f"default (DOCKER_HOST={docker_host})"
    if docker_context := os.environ.get("DOCKER_CONTEXT"):
        return docker_context

    docker_config = Path(os.environ.get("DOCKER_CONFIG") or Path.home() / ".docker").expanduser()
    config_path = docker_config / "config.json"
    if not config_path.is_file():
        return "default"
    return _DockerConfig.model_validate_json(config_path.read_text(encoding="utf-8")).current_context


def emit_json(payload: Any) -> None:
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")


def validate_run_argv(run: list[str] | None) -> None:
    """Reject a `--run` whose executable token smuggles in a whole command line.

    Typer collects each `--run` flag into one list element, so `--run "node app.js"` arrives as
    `["node app.js"]` and `--run "node app.js" --run config.json` as `["node app.js", "config.json"]`.
    Either way the runner uses the first element as argv[0], so the policy container fails to exec a
    filename containing spaces — on the hosted runner this shows up as an episode that dies with no
    logs, which is nearly impossible to diagnose. Arguments may legitimately contain spaces, but the
    executable cannot, so validate the first token and show the per-token form the user meant.
    """
    if not run:
        return
    executable_tokens = run[0].split()
    if len(executable_tokens) <= 1:
        return
    suggestion = " ".join(f"--run {shlex.quote(token)}" for token in [*executable_tokens, *run[1:]])
    raise typer.BadParameter(
        f"--run takes one token per flag, e.g. `{suggestion}`; "
        f"the first --run value (the executable) contains spaces: {run[0]!r}"
    )


def observatory_web_url(server: str, path: str) -> str:
    if path.startswith(("http://", "https://")):
        return path

    # The Observatory API is mounted under /api (the upload client appends /observatory) on the same
    # host as the web app, so the web origin is the server with that API path prefix stripped.
    parsed = urlparse(server)
    if parsed.path.rstrip("/") in ("/api", "/api/observatory"):
        origin = urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
        return f"{origin}{path}"
    return path
