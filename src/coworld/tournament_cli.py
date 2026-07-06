from __future__ import annotations

import copy
import json
import re
import shutil
import sys
import tempfile
import webbrowser
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

import httpx
import typer
from rich import box
from rich.table import Table

from coworld.api_client import (
    CoworldApiClient,
    DivisionLadderEntryPublic,
    DivisionPublic,
    EpisodeStatsResponse,
    ExperienceRequestDetail,
    ExperienceRequestRow,
    LeaguePolicyMembershipPublic,
    LeaguePublic,
    LeagueSubmissionPublic,
    RoundDetailPublic,
    RoundPublic,
    V2EpisodeRequestRow,
)
from coworld.cli_support import console, emit_json
from coworld.config import DEFAULT_SUBMIT_SERVER
from coworld.manifest_uri import materialized_replay_path
from coworld.play import ReplaySession, replay_coworld
from coworld.submit import parse_policy_identifier
from coworld.upload import download_coworld, downloaded_coworld_manifest_path, pull_and_tag_image

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_POLICY_LOG_RE = re.compile(r"^policy_agent_(\d+)\.log$")
_POLICY_ARTIFACT_RE = re.compile(r"^policy_artifact_(\d+)\.zip$")
_XP_REQUEST_HELP = (
    "Typical loop: uv run coworld xp-request create xp-request-candidate.json; "
    "uv run coworld xp-request list --mine; uv run coworld xp-request get xreq_... --json; "
    "uv run coworld xp-request episodes xreq_.... "
    "For league-targeted A/B tests, the JSON body usually includes target.league_id, "
    "roster entries with policy_ref/top_n/random players, slot assignments, num_episodes, and notes. "
    "For direct Coworld runs, use coworld_id, roster, and num_episodes. "
    "Compare the previous best and candidate with matching target, roster, episode count, and notes format."
)


def register_tournament_commands(app: typer.Typer) -> None:
    xp_request_app = typer.Typer(
        no_args_is_help=True,
        help="Create and inspect hosted Experience Requests.",
        epilog=_XP_REQUEST_HELP,
        rich_markup_mode=None,
    )
    app.add_typer(xp_request_app, name="xp-request")

    @xp_request_app.command("create")
    def xp_request_create(
        body: Annotated[
            str,
            typer.Argument(help="Path to a V2CreateExperienceRequestRequest JSON body, or '-' to read stdin."),
        ],
        server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
        json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
    ) -> None:
        raw = sys.stdin.read() if body == "-" else Path(body).read_text(encoding="utf-8")
        payload = json.loads(raw)
        with CoworldApiClient.from_login(server_url=server) as client:
            detail = client.create_experience_request(payload)
        if json_output:
            emit_json(detail.model_dump(mode="json"))
            return
        _print_experience_request_detail(detail)

    @xp_request_app.command("list")
    def xp_request_list(
        mine: Annotated[bool, typer.Option("--mine", help="Show only my Experience Requests.")] = False,
        limit: Annotated[int, typer.Option("--limit", min=1, max=1000, help="Maximum rows to return.")] = 50,
        offset: Annotated[int, typer.Option("--offset", min=0, help="Rows to skip.")] = 0,
        server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
        json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
    ) -> None:
        with CoworldApiClient.from_login(server_url=server) as client:
            page = client.list_experience_requests(mine=mine, limit=limit, offset=offset)
        if json_output:
            emit_json(page.model_dump(mode="json"))
            return
        _print_experience_requests(page.entries)
        console.print(f"[dim]Rows {page.offset + 1}-{page.offset + len(page.entries)} of {page.total_count}[/dim]")

    @xp_request_app.command("get")
    def xp_request_get(
        experience_request_id: Annotated[str, typer.Argument(help="Experience Request ID (prefix xreq_).")],
        server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
        json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
    ) -> None:
        with CoworldApiClient.from_login(server_url=server) as client:
            detail = client.get_experience_request(experience_request_id)
        if json_output:
            emit_json(detail.model_dump(mode="json"))
            return
        _print_experience_request_detail(detail)

    @xp_request_app.command("episodes")
    def xp_request_episodes(
        experience_request_id: Annotated[str, typer.Argument(help="Experience Request ID (prefix xreq_).")],
        server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
        json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
    ) -> None:
        with CoworldApiClient.from_login(server_url=server) as client:
            rows = client.list_experience_request_episodes(experience_request_id)
        if json_output:
            emit_json(_dump_models(rows))
            return
        _print_episodes(rows)

    @app.command("leagues")
    def leagues(
        league_id: Annotated[
            str | None, typer.Argument(help="League ID to inspect. Lists leagues when omitted.")
        ] = None,
        server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
        json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
    ) -> None:
        with CoworldApiClient.from_login(server_url=server) as client:
            if league_id is None:
                rows = client.list_leagues()
                if json_output:
                    emit_json(_dump_models(rows))
                    return
                _print_leagues(rows)
                return
            league = client.get_league(league_id)
        if json_output:
            emit_json(league.model_dump(mode="json"))
            return
        _print_league_detail(league)

    @app.command("divisions")
    def divisions(
        division_id: Annotated[
            str | None,
            typer.Argument(help="Division ID to inspect. Lists divisions when omitted."),
        ] = None,
        league_id: Annotated[
            str | None,
            typer.Option("--league", "-l", help="Filter divisions by league ID."),
        ] = None,
        server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
        json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
    ) -> None:
        with CoworldApiClient.from_login(server_url=server) as client:
            if division_id is None:
                rows = client.list_divisions(league_id=league_id)
                if json_output:
                    emit_json(_dump_models(rows))
                    return
                _print_divisions(rows)
                return
            division = client.get_division(division_id)
        if json_output:
            emit_json(division.model_dump(mode="json"))
            return
        _print_division_detail(division)

    @app.command("results")
    def results(
        target_id: Annotated[str, typer.Argument(help="League, division, or round ID.")],
        include_recent_rounds: Annotated[
            int,
            typer.Option("--include-recent-rounds", min=0, help="Recent rounds to include for division results."),
        ] = 3,
        server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
        json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
    ) -> None:
        with CoworldApiClient.from_login(server_url=server) as client:
            if target_id.startswith("league_"):
                rows = client.get_league_division_ladder(target_id)
                if json_output:
                    emit_json(_dump_models(rows))
                    return
                _print_division_ladder(target_id, rows)
                return
            if target_id.startswith("div_"):
                rows = client.get_division_leaderboard(target_id, include_recent_rounds=include_recent_rounds)
                if json_output:
                    emit_json(_dump_models(rows))
                    return
                _print_division_leaderboard(target_id, rows)
                return
            if target_id.startswith("round_"):
                round_detail = client.get_round(target_id)
                if json_output:
                    emit_json(round_detail.model_dump(mode="json"))
                    return
                _print_round_results(round_detail)
                return
        raise typer.BadParameter("target_id must start with league_, div_, or round_")

    @app.command("rounds")
    def rounds(
        round_id: Annotated[str | None, typer.Argument(help="Round ID to inspect. Lists rounds when omitted.")] = None,
        league_id: Annotated[str | None, typer.Option("--league", "-l", help="Filter by league ID.")] = None,
        division_id: Annotated[str | None, typer.Option("--division", "-d", help="Filter by division ID.")] = None,
        status: Annotated[str | None, typer.Option("--status", help="Filter by round status.")] = None,
        limit: Annotated[int, typer.Option("--limit", min=1, max=200, help="Maximum rows to return.")] = 25,
        offset: Annotated[int, typer.Option("--offset", min=0, help="Rows to skip.")] = 0,
        server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
        json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
    ) -> None:
        with CoworldApiClient.from_login(server_url=server) as client:
            if round_id is None:
                rows = client.list_rounds(
                    league_id=league_id,
                    division_id=division_id,
                    status=status,
                    limit=limit,
                    offset=offset,
                )
                if json_output:
                    emit_json(rows.model_dump(mode="json"))
                    return
                _print_rounds(rows.entries)
                console.print(
                    f"[dim]Rows {rows.offset + 1}-{rows.offset + len(rows.entries)} of {rows.total_count}[/dim]"
                )
                return
            round_detail = client.get_round(round_id)
        if json_output:
            emit_json(round_detail.model_dump(mode="json"))
            return
        _print_round_detail(round_detail)

    @app.command("memberships")
    def memberships(
        league_id: Annotated[str | None, typer.Option("--league", "-l", help="Filter by league ID.")] = None,
        division_id: Annotated[str | None, typer.Option("--division", "-d", help="Filter by division ID.")] = None,
        policy: Annotated[
            str | None,
            typer.Option("--policy", "-p", help="Filter by policy name/version or policy version UUID."),
        ] = None,
        player_id: Annotated[str | None, typer.Option("--player", help="Filter by player ID.")] = None,
        mine: Annotated[bool, typer.Option("--mine", help="Show memberships for my players/policies.")] = False,
        active_only: Annotated[bool, typer.Option("--active-only", help="Only show active memberships.")] = False,
        champions_only: Annotated[
            bool, typer.Option("--champions-only", help="Only show champion memberships.")
        ] = False,
        limit: Annotated[int | None, typer.Option("--limit", min=1, max=1000, help="Maximum rows to return.")] = None,
        server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
        json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
    ) -> None:
        with CoworldApiClient.from_login(server_url=server) as client:
            policy_version_id = _resolve_policy_filter(client, policy) if policy is not None else None
            rows = client.list_memberships(
                league_id=league_id,
                division_id=division_id,
                policy_version_id=policy_version_id,
                player_id=player_id,
                active_only=active_only,
                champions_only=champions_only,
                mine=mine,
                limit=limit,
            )
        if json_output:
            emit_json(_dump_models(rows))
            return
        _print_memberships(rows)

    @app.command("retire-membership")
    def retire_membership(
        membership_id: Annotated[str, typer.Argument(help="League policy membership ID to retire.")],
        reason: Annotated[
            str | None,
            typer.Option("--reason", help="Audit reason stored on the retired membership."),
        ] = None,
        server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
        json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
    ) -> None:
        with CoworldApiClient.from_login(server_url=server) as client:
            membership = client.retire_membership(membership_id, reason=reason)
        if json_output:
            emit_json(membership.model_dump(mode="json"))
            return
        _print_memberships([membership])

    @app.command("submissions")
    def submissions(
        league_id: Annotated[str | None, typer.Option("--league", "-l", help="Filter by league ID.")] = None,
        policy: Annotated[
            str | None,
            typer.Option("--policy", "-p", help="Filter by policy name/version or policy version UUID."),
        ] = None,
        player_id: Annotated[str | None, typer.Option("--player", help="Filter by player ID.")] = None,
        mine: Annotated[bool, typer.Option("--mine", help="Show my submissions.")] = False,
        limit: Annotated[int | None, typer.Option("--limit", min=1, max=1000, help="Maximum rows to return.")] = None,
        server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
        json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
    ) -> None:
        with CoworldApiClient.from_login(server_url=server) as client:
            policy_version_id = _resolve_policy_filter(client, policy) if policy is not None else None
            rows = client.list_submissions(
                league_id=league_id,
                player_id=player_id,
                policy_version_id=policy_version_id,
                mine=mine,
                limit=limit,
            )
        if json_output:
            emit_json(_dump_models(rows))
            return
        _print_submissions(rows)

    @app.command("events")
    def events(
        league_id: Annotated[str | None, typer.Option("--league", "-l", help="Filter by league ID.")] = None,
        division_id: Annotated[str | None, typer.Option("--division", "-d", help="Filter by division ID.")] = None,
        round_id: Annotated[str | None, typer.Option("--round", "-r", help="Filter by round ID.")] = None,
        event_type: Annotated[str | None, typer.Option("--event-type", help="Filter by event type.")] = None,
        audience: Annotated[str | None, typer.Option("--audience", help="Filter by audience.")] = None,
        policy: Annotated[
            str | None,
            typer.Option("--policy", "-p", help="Filter by policy name/version or policy version UUID."),
        ] = None,
        player_id: Annotated[str | None, typer.Option("--player", help="Filter by player ID.")] = None,
        limit: Annotated[int, typer.Option("--limit", min=1, max=1000, help="Maximum rows to return.")] = 50,
        server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
        json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
    ) -> None:
        with CoworldApiClient.from_login(server_url=server) as client:
            policy_version_id = _resolve_policy_filter(client, policy) if policy is not None else None
            rows = client.list_events(
                league_id=league_id,
                division_id=division_id,
                round_id=round_id,
                event_type=event_type,
                audience=audience,
                player_id=player_id,
                policy_version_id=policy_version_id,
                limit=limit,
            )
        if json_output:
            emit_json(_dump_models(rows))
            return
        _print_events(rows)

    @app.command("episodes")
    def episodes(
        episode_request_id: Annotated[
            str | None,
            typer.Argument(help="Episode request ID to inspect. Lists episode requests when omitted."),
        ] = None,
        division_id: Annotated[str | None, typer.Option("--division", "-d", help="Filter by division ID.")] = None,
        round_id: Annotated[str | None, typer.Option("--round", "-r", help="Filter by round ID.")] = None,
        policy: Annotated[
            str | None,
            typer.Option("--policy", "-p", help="Filter by policy name/version or policy version UUID."),
        ] = None,
        mine: Annotated[
            bool, typer.Option("--mine", help="Filter to episodes involving my league memberships.")
        ] = False,
        with_replay: Annotated[
            bool, typer.Option("--with-replay", help="Only show episodes with replay URLs.")
        ] = False,
        limit: Annotated[int, typer.Option("--limit", min=1, max=1000, help="Maximum rows to return.")] = 200,
        offset: Annotated[int, typer.Option("--offset", min=0, help="Rows to skip.")] = 0,
        server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
        json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
    ) -> None:
        with CoworldApiClient.from_login(server_url=server) as client:
            if episode_request_id is not None:
                episode = client.get_episode_request(episode_request_id)
                if json_output:
                    emit_json(episode.model_dump(mode="json"))
                    return
                _print_episode_detail(episode)
                return
            policy_version_id = _resolve_policy_filter(client, policy) if policy is not None else None
            rows = _collect_episode_requests(
                client,
                division_id=division_id,
                round_id=round_id,
                policy_version_id=policy_version_id,
                limit=limit,
                offset=offset,
            )
            rows = _filter_episode_requests(
                client,
                rows,
                division_id=division_id,
                policy_version_id=policy_version_id,
                mine=mine,
                with_replay=with_replay,
            )
        if json_output:
            emit_json(_dump_models(rows))
            return
        _print_episodes(rows)

    @app.command("episode-stats")
    def episode_stats(
        episode_request_id: Annotated[str, typer.Argument(help="Episode request ID.")],
        server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
        json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
    ) -> None:
        with CoworldApiClient.from_login(server_url=server) as client:
            episode = client.get_episode_request(episode_request_id)
            job_id = _require_job_id(episode)
            stats = client.get_job_episode_stats(job_id)
        if json_output:
            emit_json(stats.model_dump(mode="json"))
            return
        _print_episode_stats(episode_request_id, stats)

    @app.command("episode-results")
    def episode_results(
        episode_request_id: Annotated[str, typer.Argument(help="Episode request ID.")],
        output: Annotated[Path | None, typer.Option("--output", "-o", help="Write results JSON to a file.")] = None,
        server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    ) -> None:
        with CoworldApiClient.from_login(server_url=server) as client:
            episode = client.get_episode_request(episode_request_id)
            job_id = _require_job_id(episode)
            content = client.get_job_artifact_bytes(job_id, "results")
        if output is None:
            typer.echo(json.dumps(json.loads(content.decode("utf-8")), indent=2))
            return
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)
        console.print(f"[green]Results saved to {output}[/green]")

    @app.command("episode-logs")
    def episode_logs(
        episode_request_id: Annotated[str, typer.Argument(help="Episode request ID.")],
        list_logs: Annotated[bool, typer.Option("--list", help="List available policy log files.")] = False,
        game: Annotated[bool, typer.Option("--game", help="Show/download the game log.")] = False,
        agent: Annotated[int | None, typer.Option("--agent", min=0, help="Show/download one agent log.")] = None,
        mine: Annotated[
            bool,
            typer.Option("--mine", help="Restrict listed/downloaded logs to agents controlled by my memberships."),
        ] = False,
        artifact: Annotated[
            bool,
            typer.Option("--artifact", help="Show/download player artifact .zip files."),
        ] = False,
        download_dir: Annotated[
            Path | None,
            typer.Option(
                "--download-dir",
                "-d",
                help=(
                    "Download to a directory. Without --artifact this saves each selected agent's log AND its "
                    "player artifact .zip when one was uploaded; with --artifact it saves only artifacts."
                ),
            ),
        ] = None,
        output: Annotated[
            Path | None,
            typer.Option("--output", "-o", help="Download a single agent's artifact/log to this exact file."),
        ] = None,
        server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
    ) -> None:
        with CoworldApiClient.from_login(server_url=server) as client:
            episode = client.get_episode_request(episode_request_id)
            if game:
                if artifact:
                    console.print("[red]--artifact does not apply to --game logs.[/red]")
                    raise typer.Exit(1)
                content = client.get_episode_request_artifact_text(episode_request_id, "logs")
                if download_dir is None:
                    typer.echo(content)
                    return
                output_path = download_dir / f"{episode_request_id}-game.log"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(content, encoding="utf-8")
                console.print(f"[green]Log saved to {output_path}[/green]")
                return
            job_id = _require_job_id(episode)
            if artifact:
                artifact_indices = _available_artifact_agent_indices(client.list_job_policy_artifacts(job_id))
                if mine:
                    allowed_policy_ids = _mine_policy_version_ids(client, division_id=None)
                    allowed_agent_indices = _agent_indices_for_policies(episode, allowed_policy_ids)
                    artifact_indices = [idx for idx in artifact_indices if idx in allowed_agent_indices]
                if agent is not None:
                    if agent not in artifact_indices:
                        if mine:
                            console.print(
                                f"[red]Agent {agent} is not controlled by one of your matched policies.[/red]"
                            )
                        else:
                            available = ", ".join(str(idx) for idx in artifact_indices) or "none"
                            console.print(
                                f"[red]Agent {agent} has no artifact. Available agent indices: {available}.[/red]"
                            )
                        raise typer.Exit(1)
                    content = _download_policy_artifact(client, episode, job_id, agent)
                    output_path = _resolve_artifact_output(episode_request_id, agent, download_dir, output)
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_bytes(content)
                    console.print(f"[green]Artifact saved to {output_path}[/green]")
                    return
                if output is not None:
                    console.print("[red]Use --agent N with --output to pick which artifact to write.[/red]")
                    raise typer.Exit(1)
                if download_dir is not None:
                    written: list[Path] = []
                    for agent_idx in artifact_indices:
                        content = _download_policy_artifact(client, episode, job_id, agent_idx)
                        output_path = download_dir / f"{episode_request_id}-policy_agent_{agent_idx}.zip"
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        output_path.write_bytes(content)
                        written.append(output_path)
                    console.print(f"[green]Downloaded {len(written)} artifact file(s) to {download_dir}[/green]")
                    return
                if list_logs or agent is None:
                    _print_policy_artifacts(artifact_indices)
                return
            available_logs = client.list_job_policy_logs(job_id)
            agent_indices = _available_agent_indices(available_logs)
            artifact_indices = _available_artifact_agent_indices(client.list_job_policy_artifacts(job_id))
            if mine:
                allowed_policy_ids = _mine_policy_version_ids(client, division_id=None)
                allowed_agent_indices = _agent_indices_for_policies(episode, allowed_policy_ids)
                agent_indices = [idx for idx in agent_indices if idx in allowed_agent_indices]
                artifact_indices = [idx for idx in artifact_indices if idx in allowed_agent_indices]
            if agent is not None:
                if mine and agent not in agent_indices:
                    console.print(f"[red]Agent {agent} is not controlled by one of your matched policies.[/red]")
                    raise typer.Exit(1)
                content = client.get_job_policy_log(job_id, agent)
                if download_dir is None:
                    typer.echo(content)
                    if agent in artifact_indices:
                        _print_artifact_hint(episode_request_id, [agent])
                    return
                output_path = download_dir / f"{episode_request_id}-policy_agent_{agent}.log"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(content, encoding="utf-8")
                console.print(f"[green]Log saved to {output_path}[/green]")
                if agent in artifact_indices:
                    _download_agent_artifact(client, episode, job_id, agent, download_dir)
                return
            if download_dir is not None:
                written: list[Path] = []
                for agent_idx in agent_indices:
                    content = client.get_job_policy_log(job_id, agent_idx)
                    output_path = download_dir / f"{episode_request_id}-policy_agent_{agent_idx}.log"
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_text(content, encoding="utf-8")
                    written.append(output_path)
                console.print(f"[green]Downloaded {len(written)} log file(s) to {download_dir}[/green]")
                for agent_idx in artifact_indices:
                    if agent_idx in agent_indices:
                        _download_agent_artifact(client, episode, job_id, agent_idx, download_dir)
                return
        if list_logs or agent is None:
            _print_policy_logs(agent_indices)
            if artifact_indices:
                _print_artifact_hint(episode_request_id, artifact_indices)

    @app.command("replays")
    def replays(
        division_id: Annotated[str | None, typer.Option("--division", "-d", help="Filter by division ID.")] = None,
        round_id: Annotated[str | None, typer.Option("--round", "-r", help="Filter by round ID.")] = None,
        policy: Annotated[
            str | None,
            typer.Option("--policy", "-p", help="Filter by policy name/version or policy version UUID."),
        ] = None,
        mine: Annotated[
            bool, typer.Option("--mine", help="Filter to episodes involving my league memberships.")
        ] = False,
        download_dir: Annotated[
            Path | None, typer.Option("--download-dir", "-o", help="Download replay files.")
        ] = None,
        limit: Annotated[int, typer.Option("--limit", min=1, max=1000, help="Maximum rows to return.")] = 1000,
        offset: Annotated[int, typer.Option("--offset", min=0, help="Rows to skip.")] = 0,
        server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
        json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON metadata.")] = False,
    ) -> None:
        with CoworldApiClient.from_login(server_url=server) as client:
            policy_version_id = _resolve_policy_filter(client, policy) if policy is not None else None
            rows = _collect_episode_requests(
                client,
                division_id=division_id,
                round_id=round_id,
                policy_version_id=policy_version_id,
                limit=limit,
                offset=offset,
            )
            rows = _filter_episode_requests(
                client,
                rows,
                division_id=division_id,
                policy_version_id=policy_version_id,
                mine=mine,
                with_replay=True,
            )
            if download_dir is not None:
                metadata = _download_replays(client, rows, download_dir)
                if json_output:
                    emit_json(metadata)
                    return
                console.print(f"[green]Downloaded {len(metadata)} replay file(s) to {download_dir}[/green]")
                console.print(f"[dim]Metadata: {download_dir / 'index.json'}[/dim]")
                return
        if json_output:
            emit_json(_dump_models(rows))
            return
        _print_replays(rows)

    @app.command("replay-open")
    def replay_open(
        episode_request_id: Annotated[str, typer.Argument(help="Episode request ID.")],
        hosted: Annotated[bool, typer.Option("--hosted", help="Create a hosted Observatory replay session.")] = False,
        server: Annotated[str, typer.Option("--server", help="Observatory API server URL.")] = DEFAULT_SUBMIT_SERVER,
        timeout_seconds: Annotated[
            float, typer.Option("--timeout-seconds", min=1.0, help="Local health timeout.")
        ] = 60.0,
        open_browser: Annotated[
            bool,
            typer.Option("--open-browser/--no-open-browser", help="Open the replay viewer in a browser when ready."),
        ] = True,
        with_artifacts: Annotated[
            bool,
            typer.Option("--with-artifacts", help="Also download this episode's per-player artifact .zip files."),
        ] = False,
        artifacts_dir: Annotated[
            Path | None,
            typer.Option("--artifacts-dir", help="Directory for downloaded artifacts. Defaults to ./<ereq>-artifacts."),
        ] = None,
        mine: Annotated[
            bool,
            typer.Option("--mine", help="Restrict downloaded artifacts to agents controlled by my memberships."),
        ] = False,
    ) -> None:
        def on_ready(session: ReplaySession) -> None:
            _print_replay_session(session)
            if open_browser:
                webbrowser.open(session.link)

        with CoworldApiClient.from_login(server_url=server) as client:
            episode = client.get_episode_request(episode_request_id)
            if with_artifacts:
                _download_episode_artifacts(client, episode, episode_request_id, artifacts_dir, mine)
            if episode.replay_url is None:
                console.print("[red]No replay URL is available for this episode request.[/red]")
                raise typer.Exit(1)
            if episode.coworld_id is None:
                console.print("[red]Episode request is missing coworld_id.[/red]")
                raise typer.Exit(1)
            if episode.episode_id is None:
                console.print("[red]Episode request is missing episode_id.[/red]")
                raise typer.Exit(1)
            if hosted:
                session = client.create_replay_session(
                    coworld_id=episode.coworld_id,
                    episode_id=episode.episode_id,
                    replay_uri=episode.replay_url,
                )
                console.print(session.viewer_url)
                if open_browser:
                    webbrowser.open(session.viewer_url)
                return
        manifest_path = downloaded_coworld_manifest_path(Path("./coworld"), episode.coworld_id)
        with ExitStack() as stack:
            if manifest_path.is_file():
                replay_manifest_path = manifest_path.resolve()
            else:
                coworld = download_coworld(episode.coworld_id, server=server)
                manifest = copy.deepcopy(coworld.manifest)
                game_image = manifest["game"]["runnable"]["image"]
                local_game_image = f"coworld/{coworld.id}/replay-game:downloaded"
                pull_and_tag_image(game_image, local_game_image)
                manifest["game"]["runnable"]["image"] = local_game_image
                manifest_temp_dir = stack.enter_context(tempfile.TemporaryDirectory(prefix="coworld-replay-manifest-"))
                replay_manifest_path = Path(manifest_temp_dir) / "coworld_manifest.json"
                replay_manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            replay_path = stack.enter_context(materialized_replay_path(episode.replay_url))
            session = replay_coworld(
                replay_manifest_path,
                replay_path,
                timeout_seconds=timeout_seconds,
                on_ready=on_ready,
            )
        typer.echo(f"Logs: {session.artifacts.logs_dir}")


def _dump_models(rows: list[Any]) -> list[dict[str, Any]]:
    return [row.model_dump(mode="json") for row in rows]


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def _format_score(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.4f}"


def _policy_label(policy_version: Any) -> str:
    return f"{policy_version.policy.name}:v{policy_version.version}"


def _player_label(player: Any | None) -> str:
    if player is None:
        return "-"
    return player.name or player.id


def _resolve_policy_filter(client: CoworldApiClient, policy: str) -> UUID:
    if _UUID_RE.fullmatch(policy):
        return UUID(policy)
    name, version = parse_policy_identifier(policy)
    row = client.lookup_policy_version(name=name, version=version)
    if row is None:
        version_hint = f":v{version}" if version is not None else ""
        console.print(f"[red]Policy '{name}{version_hint}' not found.[/red]")
        raise typer.Exit(1)
    return row.resolved_id


def _print_leagues(rows: list[LeaguePublic]) -> None:
    table = Table(title="Coworld Leagues", box=box.SIMPLE_HEAVY, show_lines=False, pad_edge=False)
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Game")
    table.add_column("Public")
    table.add_column("Created")
    for row in rows:
        table.add_row(row.id, row.name, row.game.name, str(row.public).lower(), _format_dt(row.created_at))
    console.print(table)


def _print_league_detail(row: LeaguePublic) -> None:
    console.print(f"[bold]League:[/bold] {row.id}")
    console.print(f"Name: {row.name}")
    console.print(f"Game: {row.game.name} ({row.game.id})")
    if row.game.coworld_id is not None:
        console.print(f"Coworld: {row.game.coworld_id}")
    console.print(f"Public: {row.public}")
    console.print(f"Hidden: {row.hidden}")
    console.print(f"Created: {_format_dt(row.created_at)}")


def _print_divisions(rows: list[DivisionPublic]) -> None:
    table = Table(title="Coworld Divisions", box=box.SIMPLE_HEAVY, show_lines=False, pad_edge=False)
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Level", justify="right")
    table.add_column("League")
    table.add_column("Created")
    for row in rows:
        table.add_row(row.id, row.name, str(row.level), row.league.name, _format_dt(row.created_at))
    console.print(table)


def _print_division_detail(row: DivisionPublic) -> None:
    console.print(f"[bold]Division:[/bold] {row.id}")
    console.print(f"Name: {row.name}")
    console.print(f"Level: {row.level}")
    console.print(f"League: {row.league.name} ({row.league.id})")
    console.print(f"Created: {_format_dt(row.created_at)}")
    if row.commissioner_description is not None:
        console.print(f"Round schedule: {row.commissioner_description.round_schedule or '-'}")
        console.print(f"Next round: {row.commissioner_description.next_round or '-'}")


def _print_division_ladder(league_id: str, rows: list[DivisionLadderEntryPublic]) -> None:
    table = Table(title=f"Division Ladder {league_id}", box=box.SIMPLE_HEAVY, show_lines=False, pad_edge=False)
    table.add_column("Division")
    table.add_column("Level", justify="right")
    table.add_column("Members", justify="right")
    for row in rows:
        table.add_row(f"{row.name}\n[dim]{row.id}[/dim]", str(row.level), str(row.member_count))
    console.print(table)


def _print_division_leaderboard(division_id: str, rows: list[Any]) -> None:
    table = Table(title=f"Division Results {division_id}", box=box.SIMPLE_HEAVY, show_lines=False, pad_edge=False)
    table.add_column("Rank", justify="right")
    table.add_column("Player")
    table.add_column("Score", justify="right")
    table.add_column("Rounds", justify="right")
    for rank, row in enumerate(rows, start=1):
        display_rank = row.rank if row.rank is not None else rank
        table.add_row(
            str(display_rank),
            row.player_name or row.player_id,
            _format_score(row.score),
            str(row.rounds_played),
        )
    console.print(table)


def _print_rounds(rows: list[RoundPublic]) -> None:
    table = Table(title="Coworld Rounds", box=box.SIMPLE_HEAVY, show_lines=False, pad_edge=False)
    table.add_column("ID")
    table.add_column("#", justify="right")
    table.add_column("Status")
    table.add_column("Division")
    table.add_column("Started")
    table.add_column("Completed")
    for row in rows:
        table.add_row(
            row.id,
            str(row.round_number),
            row.status,
            row.division.name,
            _format_dt(row.started_at),
            _format_dt(row.completed_at),
        )
    console.print(table)


def _print_round_detail(row: RoundDetailPublic) -> None:
    console.print(f"[bold]Round:[/bold] {row.id}")
    console.print(f"Number: {row.round_number}")
    console.print(f"Status: {row.status}")
    console.print(f"Division: {row.division.name} ({row.division.id})")
    console.print(f"Results: {len(row.results)}")
    if row.error is not None:
        console.print(f"[red]Error:[/red] {row.error}")
    _print_round_results(row)


def _print_round_results(row: RoundDetailPublic) -> None:
    table = Table(title=f"Round Results {row.id}", box=box.SIMPLE_HEAVY, show_lines=False, pad_edge=False)
    table.add_column("Rank", justify="right")
    table.add_column("Player")
    table.add_column("Policy")
    table.add_column("Score", justify="right")
    for result in sorted(row.results, key=lambda item: item.rank):
        table.add_row(
            str(result.rank),
            _player_label(result.player),
            _policy_label(result.policy_version),
            _format_score(result.score),
        )
    console.print(table)


def _print_memberships(rows: list[LeaguePolicyMembershipPublic]) -> None:
    table = Table(title="Coworld League Memberships", box=box.SIMPLE_HEAVY, show_lines=False, pad_edge=False)
    table.add_column("ID")
    table.add_column("Player")
    table.add_column("Policy")
    table.add_column("Division")
    table.add_column("Status")
    table.add_column("Substatus")
    for row in rows:
        table.add_row(
            row.id,
            _player_label(row.player),
            _policy_label(row.policy_version),
            row.division.name,
            row.status,
            row.substatus or "-",
        )
    console.print(table)


def _print_submissions(rows: list[LeagueSubmissionPublic]) -> None:
    table = Table(title="Coworld League Submissions", box=box.SIMPLE_HEAVY, show_lines=False, pad_edge=False)
    table.add_column("ID")
    table.add_column("Status")
    table.add_column("Player")
    table.add_column("Policy")
    table.add_column("League")
    table.add_column("Membership")
    for row in rows:
        table.add_row(
            row.id,
            row.status,
            _player_label(row.player),
            _policy_label(row.policy_version),
            row.league.name,
            row.league_policy_membership_id or "-",
        )
    console.print(table)


def _print_events(rows: list[Any]) -> None:
    table = Table(title="Coworld Competition Events", box=box.SIMPLE_HEAVY, show_lines=False, pad_edge=False)
    table.add_column("ID")
    table.add_column("Type")
    table.add_column("When")
    table.add_column("Headline")
    table.add_column("Summary")
    for row in rows:
        table.add_row(row.id, row.event_type, _format_dt(row.created_at), row.headline, row.summary)
    console.print(table)


def _collect_episode_requests(
    client: CoworldApiClient,
    *,
    division_id: str | None,
    round_id: str | None,
    policy_version_id: UUID | None,
    limit: int,
    offset: int,
) -> list[V2EpisodeRequestRow]:
    return client.list_episode_requests(
        division_id=division_id,
        round_id=round_id,
        policy_version_id=policy_version_id,
        limit=limit,
        offset=offset,
    )


def _mine_policy_version_ids(client: CoworldApiClient, *, division_id: str | None) -> set[UUID]:
    memberships = client.list_memberships(
        division_id=division_id,
        mine=True,
        limit=1000,
    )
    return {membership.policy_version.id for membership in memberships}


def _filter_episode_requests(
    client: CoworldApiClient,
    rows: list[V2EpisodeRequestRow],
    *,
    division_id: str | None,
    policy_version_id: UUID | None,
    mine: bool,
    with_replay: bool,
) -> list[V2EpisodeRequestRow]:
    allowed_policy_ids: set[UUID] | None = None
    if mine:
        allowed_policy_ids = _mine_policy_version_ids(client, division_id=division_id)
    if policy_version_id is not None:
        allowed_policy_ids = (
            {policy_version_id} if allowed_policy_ids is None else allowed_policy_ids & {policy_version_id}
        )

    filtered = []
    for row in rows:
        if with_replay and row.replay_url is None:
            continue
        if allowed_policy_ids is not None and not _episode_has_policy(row, allowed_policy_ids):
            continue
        filtered.append(row)
    return filtered


def _episode_has_policy(row: V2EpisodeRequestRow, policy_version_ids: set[UUID]) -> bool:
    return any(participant.policy_version_id in policy_version_ids for participant in row.participants)


def _print_episodes(rows: list[V2EpisodeRequestRow]) -> None:
    table = Table(title="Coworld Episode Requests", box=box.SIMPLE_HEAVY, show_lines=False, pad_edge=False)
    table.add_column("ID")
    table.add_column("Status")
    table.add_column("Seed", justify="right")
    table.add_column("Participants")
    table.add_column("Scores")
    table.add_column("Replay")
    table.add_column("Created")
    for row in rows:
        scores = {score.policy_version_id: score.score for score in row.scores}
        participant_labels = ", ".join(participant.label for participant in row.participants)
        score_labels = ", ".join(
            f"{participant.label}={_format_score(scores.get(participant.policy_version_id))}"
            for participant in row.participants
        )
        table.add_row(
            row.id,
            row.status,
            "-" if row.seed is None else str(row.seed),
            participant_labels or "-",
            score_labels or "-",
            "yes" if row.replay_url else "-",
            _format_dt(row.created_at),
        )
    console.print(table)


def _print_episode_detail(row: V2EpisodeRequestRow) -> None:
    console.print(f"[bold]Episode request:[/bold] {row.id}")
    console.print(f"Status: {row.status}")
    console.print(f"Round: {row.round_id or '-'}")
    console.print(f"Coworld: {row.coworld_id or '-'}")
    console.print(f"Seed: {row.seed if row.seed is not None else '-'}")
    console.print(f"Job: {row.job_id or '-'}")
    console.print(f"Episode: {row.episode_id or '-'}")
    console.print(f"Replay: {row.replay_url or '-'}")
    _print_episodes([row])


def _print_experience_requests(rows: list[ExperienceRequestRow]) -> None:
    table = Table(title="Experience Requests", box=box.SIMPLE_HEAVY, show_lines=False, pad_edge=False)
    table.add_column("ID")
    table.add_column("Status")
    table.add_column("Coworld")
    table.add_column("Variant")
    table.add_column("Episodes", justify="right")
    table.add_column("Counts")
    table.add_column("Created")
    for row in rows:
        table.add_row(
            row.id,
            row.status,
            f"{row.coworld_name}:{row.coworld_version}",
            row.variant_id or "-",
            str(row.episode_count),
            _experience_request_counts(row),
            _format_dt(row.created_at),
        )
    console.print(table)


def _experience_request_counts(row: ExperienceRequestRow) -> str:
    parts = [
        ("pending", row.pending_count),
        ("submitted", row.submitted_count),
        ("running", row.running_count),
        ("completed", row.completed_count),
        ("failed", row.failed_count),
    ]
    return ", ".join(f"{label}={count}" for label, count in parts if count) or "-"


def _print_experience_request_detail(row: ExperienceRequestDetail) -> None:
    console.print(f"[bold]Experience request:[/bold] {row.id}")
    console.print(f"Status: {row.status}")
    console.print(f"Coworld: {row.coworld_name}:{row.coworld_version} ({row.coworld_id})")
    console.print(f"Variant: {row.variant_id or '-'}")
    console.print(f"Requester: {row.requester or row.requester_user_id}")
    console.print(f"Episodes: {row.episode_count}")
    console.print(f"Counts: {_experience_request_counts(row)}")
    if row.error is not None:
        console.print(f"[red]Error:[/red] {row.error}")
    console.print(f"Created: {_format_dt(row.created_at)}")
    console.print(f"Started: {_format_dt(row.started_at)}")
    console.print(f"Completed: {_format_dt(row.completed_at)}")
    _print_episodes(row.episodes)


def _require_job_id(row: V2EpisodeRequestRow) -> UUID:
    if row.job_id is None:
        console.print("[red]Episode request has no job_id yet.[/red]")
        raise typer.Exit(1)
    return row.job_id


def _print_episode_stats(episode_request_id: str, stats: EpisodeStatsResponse) -> None:
    console.print(f"[bold]Episode stats:[/bold] {episode_request_id}")
    console.print(f"Steps: {stats.steps if stats.steps is not None else '-'}")
    table = Table(title="Policy Stats", box=box.SIMPLE_HEAVY, show_lines=False, pad_edge=False)
    table.add_column("Position", justify="right")
    table.add_column("Policy")
    table.add_column("Agents", justify="right")
    table.add_column("Avg Reward", justify="right")
    for row in stats.policy_stats:
        policy_label = f"{row.policy_name or '-'}:v{row.policy_version}" if row.policy_name else "-"
        table.add_row(str(row.position), policy_label, str(row.num_agents), _format_score(row.avg_reward))
    console.print(table)
    if stats.game_stats:
        console.print(json.dumps(stats.game_stats, indent=2, sort_keys=True))


def _available_agent_indices(log_names: list[str]) -> list[int]:
    indices: list[int] = []
    for name in log_names:
        match = _POLICY_LOG_RE.fullmatch(name)
        if match is not None:
            indices.append(int(match.group(1)))
    return sorted(indices)


def _available_artifact_agent_indices(artifact_names: list[str]) -> list[int]:
    indices: list[int] = []
    for name in artifact_names:
        match = _POLICY_ARTIFACT_RE.fullmatch(name)
        if match is not None:
            indices.append(int(match.group(1)))
    return sorted(indices)


def _policy_version_id_for_agent(episode: V2EpisodeRequestRow, agent_idx: int) -> UUID:
    for participant in episode.participants:
        if participant.position == agent_idx:
            return participant.policy_version_id
    console.print(f"[red]Agent {agent_idx} is not a participant in this episode.[/red]")
    raise typer.Exit(1)


def _download_policy_artifact(
    client: CoworldApiClient,
    episode: V2EpisodeRequestRow,
    job_id: UUID,
    agent_idx: int,
) -> bytes:
    """Fetch one agent's player artifact, preferring the ownership-scoped v2 episode-request
    route and falling back to the job-level route only when v2 is not deployed yet (404).

    The v2 route is the correct, ownership-scoped path once deployed; the job-level route is a
    pragmatic bridge while the v2 route rolls out. A 403 (genuine permission denial) is NOT a
    fallback condition and propagates.
    """
    policy_version_id = _policy_version_id_for_agent(episode, agent_idx)
    try:
        return client.get_episode_request_policy_artifact(episode.id, policy_version_id, agent_idx)
    except httpx.HTTPStatusError as error:
        if error.response.status_code != 404:
            raise
        return client.get_job_policy_artifact(job_id, agent_idx)


def _download_agent_artifact(
    client: CoworldApiClient,
    episode: V2EpisodeRequestRow,
    job_id: UUID,
    agent_idx: int,
    download_dir: Path,
) -> None:
    content = _download_policy_artifact(client, episode, job_id, agent_idx)
    output_path = download_dir / f"{episode.id}-policy_agent_{agent_idx}.zip"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(content)
    console.print(f"[green]Artifact saved to {output_path}[/green]")


def _print_artifact_hint(episode_request_id: str, agent_indices: list[int]) -> None:
    agents = ", ".join(str(idx) for idx in agent_indices)
    plural = "s" if len(agent_indices) > 1 else ""
    console.print(
        f"[yellow]Agent{plural} {agents} also uploaded a player artifact (.zip). "
        f"Pass --download-dir to fetch both, or add --artifact to fetch only the artifact:[/yellow]"
    )
    for agent_idx in agent_indices:
        console.print(
            f"[dim]uv run coworld episode-logs {episode_request_id} --agent {agent_idx} --artifact "
            f"--download-dir logs/[/dim]"
        )


def _resolve_artifact_output(
    episode_request_id: str,
    agent: int,
    download_dir: Path | None,
    output: Path | None,
) -> Path:
    """Pick the destination file for a single agent's artifact.

    Precedence: explicit --output, then --download-dir, then a default name in the cwd. The
    cwd default refuses to clobber an existing file so a re-run does not silently overwrite.
    """
    if output is not None:
        return output
    if download_dir is not None:
        return download_dir / f"{episode_request_id}-policy_agent_{agent}.zip"
    default_path = Path.cwd() / f"{episode_request_id}-policy_agent_{agent}.zip"
    if default_path.exists():
        console.print(
            f"[red]{default_path} already exists. Pass --output or --download-dir to choose a destination.[/red]"
        )
        raise typer.Exit(1)
    return default_path


def _download_episode_artifacts(
    client: CoworldApiClient,
    episode: V2EpisodeRequestRow,
    episode_request_id: str,
    artifacts_dir: Path | None,
    mine: bool,
) -> None:
    job_id = _require_job_id(episode)
    artifact_indices = _available_artifact_agent_indices(client.list_job_policy_artifacts(job_id))
    if mine:
        allowed_policy_ids = _mine_policy_version_ids(client, division_id=None)
        allowed_agent_indices = _agent_indices_for_policies(episode, allowed_policy_ids)
        artifact_indices = [idx for idx in artifact_indices if idx in allowed_agent_indices]
    if not artifact_indices:
        console.print("[yellow]No player artifacts found for this episode.[/yellow]")
        return
    output_dir = artifacts_dir if artifacts_dir is not None else Path.cwd() / f"{episode_request_id}-artifacts"
    output_dir.mkdir(parents=True, exist_ok=True)
    for agent_idx in artifact_indices:
        content = _download_policy_artifact(client, episode, job_id, agent_idx)
        output_path = output_dir / f"policy_artifact_{agent_idx}.zip"
        output_path.write_bytes(content)
        console.print(f"[green]Artifact saved to {output_path}[/green]")


def _agent_indices_for_policies(row: V2EpisodeRequestRow, policy_version_ids: set[UUID]) -> set[int]:
    return {
        participant.position for participant in row.participants if participant.policy_version_id in policy_version_ids
    }


def _print_policy_logs(agent_indices: list[int]) -> None:
    if not agent_indices:
        console.print("[yellow]No policy logs found.[/yellow]")
        return
    table = Table(title="Policy Logs", box=box.SIMPLE_HEAVY, show_lines=False, pad_edge=False)
    table.add_column("Agent", justify="right")
    table.add_column("Filename")
    for agent_idx in agent_indices:
        table.add_row(str(agent_idx), f"policy_agent_{agent_idx}.log")
    console.print(table)


def _print_policy_artifacts(agent_indices: list[int]) -> None:
    if not agent_indices:
        console.print("[yellow]No player artifacts found.[/yellow]")
        return
    table = Table(title="Player Artifacts", box=box.SIMPLE_HEAVY, show_lines=False, pad_edge=False)
    table.add_column("Agent", justify="right")
    table.add_column("Filename")
    for agent_idx in agent_indices:
        table.add_row(str(agent_idx), f"policy_artifact_{agent_idx}.zip")
    console.print(table)


def _download_replays(
    client: CoworldApiClient,
    rows: list[V2EpisodeRequestRow],
    output_dir: Path,
) -> list[dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata: list[dict[str, Any]] = []
    for row in rows:
        assert row.replay_url is not None, "replay download rows must have replay_url"
        local_name = f"{row.id}.replay"
        local_path = output_dir / local_name
        with materialized_replay_path(row.replay_url) as replay_path:
            shutil.copyfile(replay_path, local_path)
        if not local_path.exists() and row.job_id is not None:
            local_path = output_dir / f"{row.id}.replay"
            local_path.write_bytes(client.get_job_artifact_bytes(row.job_id, "replay"))
        metadata.append(
            {
                "episode_request_id": row.id,
                "episode_id": None if row.episode_id is None else str(row.episode_id),
                "job_id": None if row.job_id is None else str(row.job_id),
                "coworld_id": row.coworld_id,
                "replay_url": row.replay_url,
                "local_path": str(local_path),
                "seed": row.seed,
                "status": row.status,
                "participants": [participant.model_dump(mode="json") for participant in row.participants],
                "scores": [score.model_dump(mode="json") for score in row.scores],
            }
        )
    (output_dir / "index.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def _print_replays(rows: list[V2EpisodeRequestRow]) -> None:
    table = Table(title="Coworld Replays", box=box.SIMPLE_HEAVY, show_lines=False, pad_edge=False)
    table.add_column("Episode Request")
    table.add_column("Coworld")
    table.add_column("Replay URI")
    table.add_column("Local Command")
    for row in rows:
        command = f"uv run coworld replay {row.coworld_id} {row.replay_url}" if row.coworld_id else "-"
        table.add_row(row.id, row.coworld_id or "-", row.replay_url or "-", command)
    console.print(table)


def _print_replay_session(session: ReplaySession) -> None:
    typer.echo(f"Artifacts: {session.artifacts.workspace}")
    typer.echo(f"Replay file: {session.replay_path}")
    typer.echo(f"Replay client: {session.link}")
    typer.echo("Waiting for the replay container to exit...")
