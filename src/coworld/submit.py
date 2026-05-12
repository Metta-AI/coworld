from __future__ import annotations

import typer

from coworld.cli_support import console
from coworld.config import DEFAULT_SUBMIT_SERVER
from coworld.upload import CoworldUploadClient, PolicyVersionRow


def parse_policy_identifier(identifier: str) -> tuple[str, int | None]:
    if ":" not in identifier:
        return identifier, None
    name, version_str = identifier.rsplit(":", 1)
    version_str = version_str.removeprefix("v")
    if not name or not version_str.isdecimal():
        raise typer.BadParameter(f"Invalid policy version: {identifier}")
    version = int(version_str)
    if version <= 0:
        raise typer.BadParameter(f"Invalid policy version: {identifier}")
    return name, version


def _resolve_policy_version(client: CoworldUploadClient, policy_identifier: str) -> PolicyVersionRow:
    name, version = parse_policy_identifier(policy_identifier)
    policy_version = client.lookup_policy_version(name=name, version=version)
    if policy_version is None:
        version_hint = f":v{version}" if version is not None else ""
        console.print(f"[red]Policy '{name}{version_hint}' not found.[/red]")
        console.print("[dim]Upload a Coworld policy first with: uv run coworld upload-policy IMAGE --name NAME[/dim]")
        raise typer.Exit(1)
    return policy_version


def submit_policy_to_league_cmd(
    policy_identifier: str,
    *,
    league_id: str,
    server: str = DEFAULT_SUBMIT_SERVER,
) -> None:
    with CoworldUploadClient.from_login(server_url=server) as client:
        policy_version = _resolve_policy_version(client, policy_identifier)

        version_label = f":v{policy_version.version}"
        console.print(f"[bold]Submitting {policy_version.name}{version_label} to league {league_id}[/bold]")
        submission = client.submit_to_league(league_id, policy_version.id)

    console.print("[green]Submitted to league[/green]")
    console.print(f"[dim]League:[/dim] {league_id}")
    console.print(f"[dim]Submission:[/dim] {submission.id}")
    console.print(f"[dim]Status:[/dim] {submission.status}")
    if submission.league_policy_membership_id is not None:
        console.print(f"[dim]Membership:[/dim] {submission.league_policy_membership_id}")
    elif submission.status in {"pending", "processing"}:
        console.print("[dim]Placement runs asynchronously; check the Observatory league page for status.[/dim]")
