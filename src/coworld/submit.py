from __future__ import annotations

import webbrowser
from typing import Any

import typer

from coworld.cli_support import console, observatory_web_url
from coworld.config import DEFAULT_SUBMIT_SERVER
from coworld.upload import AutoChampion, CoworldUploadClient, PolicyVersionRow


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
    open_browser: bool = True,
    auto_champion: AutoChampion = AutoChampion.always,
    preferences: dict[str, Any] | None = None,
) -> None:
    with CoworldUploadClient.from_login(server_url=server) as client:
        policy_version = _resolve_policy_version(client, policy_identifier)

        version_label = f":v{policy_version.version}"
        console.print(f"[bold]Submitting {policy_version.name}{version_label} to league {league_id}[/bold]")
        submission = client.submit_to_league(
            league_id,
            policy_version.id,
            auto_champion=auto_champion,
            preferences=preferences,
        )

    placement_runs_async = submission.status in {"pending", "processing"}
    policy_path = (
        f"/observatory/v2?tab=uploads&detail=policy-version:{policy_version.id}"
        if placement_runs_async
        else f"/observatory/policies/versions/{policy_version.id}"
    )
    policy_url = observatory_web_url(server, policy_path)
    console.print("[green]Submitted to league[/green]")
    console.print(f"[dim]League:[/dim] {league_id}")
    console.print(f"[dim]Submission:[/dim] {submission.id}")
    console.print(f"[dim]Status:[/dim] {submission.status}")
    console.print(f"[dim]Auto champion:[/dim] {auto_champion.value}")
    if submission.league_policy_membership_id is not None:
        console.print(f"[dim]Membership:[/dim] {submission.league_policy_membership_id}")
    elif placement_runs_async:
        console.print("[dim]Placement runs asynchronously; check the status page for updates.[/dim]")
    page_label = "Status page" if placement_runs_async else "Policy page"
    console.print(f"[dim]{page_label}:[/dim] {policy_url}", soft_wrap=True)
    if open_browser:
        webbrowser.open(policy_url)
