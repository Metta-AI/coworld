"""`coworld campaign` — the player-facing campaign API.

Read the board and your battle history, and manage your player's standing-orders
strategy prompt (the text the league strategist follows each round).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich import box
from rich.table import Table

from coworld.api_client import CampaignBoardPublic, CoworldApiClient
from coworld.cli_support import console, emit_json, resolve_league_id
from coworld.config import DEFAULT_SUBMIT_SERVER

_SERVER_OPTION = typer.Option("--server", help="Observatory API server URL.")
_PLAYER_OPTION = typer.Option(
    "--player", help="Player name or id. Defaults to your only player in the league's campaign."
)


def _resolve_player_id(board: CampaignBoardPublic, player: str | None) -> str:
    if player is None:
        if len(board.viewer_player_ids) == 1:
            return board.viewer_player_ids[0]
        names = {p.id: p.name for p in board.players}
        owned = ", ".join(f"{names.get(pid, '?')} ({pid})" for pid in board.viewer_player_ids) or "none"
        raise typer.BadParameter(f"--player required; your players in this campaign: {owned}")
    matches = [p for p in board.players if player in (p.id, p.name) or player.lower() == p.name.lower()]
    if not matches:
        raise typer.BadParameter(f"player not in this campaign: {player}")
    if len(matches) > 1:
        ids = ", ".join(p.id for p in matches)
        raise typer.BadParameter(f"ambiguous player name {player!r}; use one of: {ids}")
    return matches[0].id


def register_campaign_commands(app: typer.Typer) -> None:
    campaign_app = typer.Typer(
        no_args_is_help=True,
        help="Campaign leagues: read the board and your history, set your strategy prompt.",
    )
    app.add_typer(campaign_app, name="campaign")

    @campaign_app.command("board")
    def campaign_board(
        league: Annotated[str, typer.Argument(help="League id or name.")],
        server: Annotated[str, _SERVER_OPTION] = DEFAULT_SUBMIT_SERVER,
        json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
    ) -> None:
        """Board summary: round, config, and each player's territory."""
        with CoworldApiClient.from_login(server_url=server) as client:
            board = client.get_campaign_board(resolve_league_id(client, league))
        if json_output:
            emit_json(board.model_dump(mode="json"))
            return
        cfg = board.config
        console.print(
            f"[bold]Round {board.round}[/bold] — {cfg.width}x{cfg.height} board, "
            f"modes {'/'.join(sorted(set(board.modes)))}, max {cfg.max_invasions} invasions/round, "
            f"outcomes: {cfg.outcomes}"
        )
        if not board.frames:
            console.print("[dim]The campaign has not started yet — no rounds played.[/dim]")
            return
        territory = board.frames[-1]["territory"]
        total_cells = cfg.width * cfg.height
        table = Table(box=box.SIMPLE)
        table.add_column("Player")
        table.add_column("Territory", justify="right")
        table.add_column("Board %", justify="right")
        for p in sorted(board.players, key=lambda p: -territory.get(p.id, 0)):
            cells = territory.get(p.id, 0)
            marker = " [dim](you)[/dim]" if p.id in board.viewer_player_ids else ""
            table.add_row(
                f"{p.symbol or ''} {p.name}{marker}", str(cells), f"{100.0 * cells / max(total_cells, 1):.1f}"
            )
        console.print(table)
        if board.pending_round:
            console.print(f"[yellow]Round {board.pending_round.get('round')} in flight[/yellow]")

    @campaign_app.command("history")
    def campaign_history(
        league: Annotated[str, typer.Argument(help="League id or name.")],
        player: Annotated[str | None, _PLAYER_OPTION] = None,
        rounds: Annotated[int | None, typer.Option("--rounds", help="Only the last N rounds.")] = None,
        server: Annotated[str, _SERVER_OPTION] = DEFAULT_SUBMIT_SERVER,
        json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
    ) -> None:
        """A player's battle log and head-to-head; transfers and the full
        territory series are in the --json output."""
        with CoworldApiClient.from_login(server_url=server) as client:
            league_id = resolve_league_id(client, league)
            board = client.get_campaign_board(league_id)
            player_id = _resolve_player_id(board, player)
            history = client.get_campaign_history(league_id, player_id=player_id, rounds=rounds)
        if json_output:
            emit_json(history.model_dump(mode="json"))
            return

        def name(pid: str | None) -> str:
            return history.names.get(pid or "", pid or "filler")

        console.print(f"[bold]{name(player_id)}[/bold] — campaign history through round {history.round}")
        if history.territory:
            console.print(f"Territory: {history.territory[-1].cells} cells (round {history.territory[-1].round})")
        table = Table(box=box.SIMPLE)
        table.add_column("Rd", justify="right")
        table.add_column("Role")
        table.add_column("Mode")
        table.add_column("Cell")
        table.add_column("Vs")
        table.add_column("Outcome")
        table.add_column("Result")
        for b in history.battles:
            style = {"won": "green", "lost": "red", "draw": "yellow"}.get(b.result, "dim")
            table.add_row(
                str(b.round),
                b.role,
                b.mode,
                b.target,
                ", ".join(name(o) for o in b.opponents) or "-",
                b.outcome,
                f"[{style}]{b.result}[/{style}]",
            )
        console.print(table)
        if history.head_to_head:
            window = f"last {rounds} rounds" if rounds is not None else "all retained rounds"
            h2h = Table(box=box.SIMPLE, title=f"Head-to-head (episode seats, {window})")
            h2h.add_column("Opponent")
            h2h.add_column("W", justify="right")
            h2h.add_column("L", justify="right")
            for pid, record in sorted(history.head_to_head.items(), key=lambda kv: -kv[1].wins):
                h2h.add_row(name(pid), str(record.wins), str(record.losses))
            console.print(h2h)

    @campaign_app.command("prompt")
    def campaign_prompt(
        league: Annotated[str, typer.Argument(help="League id or name.")],
        player: Annotated[str | None, _PLAYER_OPTION] = None,
        server: Annotated[str, _SERVER_OPTION] = DEFAULT_SUBMIT_SERVER,
        json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
    ) -> None:
        """Show your player's current strategy prompt (standing orders)."""
        with CoworldApiClient.from_login(server_url=server) as client:
            league_id = resolve_league_id(client, league)
            board = client.get_campaign_board(league_id)
            player_id = _resolve_player_id(board, player)
            result = client.get_campaign_prompt(league_id, player_id=player_id)
        if json_output:
            emit_json(result.model_dump(mode="json"))
            return
        if result.is_default:
            console.print("[dim]No saved prompt — the league default applies:[/dim]")
        console.print(result.prompt)

    @campaign_app.command("set-prompt")
    def campaign_set_prompt(
        league: Annotated[str, typer.Argument(help="League id or name.")],
        text: Annotated[str | None, typer.Argument(help="The prompt text; omit to use --file.")] = None,
        file: Annotated[Path | None, typer.Option("--file", help="Read the prompt from a file.")] = None,
        player: Annotated[str | None, _PLAYER_OPTION] = None,
        server: Annotated[str, _SERVER_OPTION] = DEFAULT_SUBMIT_SERVER,
    ) -> None:
        """Set your player's strategy prompt (max 4000 chars)."""
        if (text is None) == (file is None):
            raise typer.BadParameter("Provide the prompt text or --file, not both")
        prompt = text if text is not None else file.read_text()  # type: ignore[union-attr]
        with CoworldApiClient.from_login(server_url=server) as client:
            league_id = resolve_league_id(client, league)
            board = client.get_campaign_board(league_id)
            player_id = _resolve_player_id(board, player)
            client.set_campaign_prompt(league_id, player_id=player_id, prompt=prompt)
        console.print(f"[green]Prompt saved[/green] for player {player_id} ({len(prompt)} chars)")

    @campaign_app.command("conversation")
    def campaign_conversation(
        league: Annotated[str, typer.Argument(help="League id or name.")],
        round_no: Annotated[
            int | None, typer.Option("--round", help="Round number; defaults to the latest retained round.")
        ] = None,
        player: Annotated[str | None, _PLAYER_OPTION] = None,
        server: Annotated[str, _SERVER_OPTION] = DEFAULT_SUBMIT_SERVER,
        json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
    ) -> None:
        """The full strategist exchange for one round of your player: rendered
        board context, model response, and issued orders. Recent rounds only."""
        with CoworldApiClient.from_login(server_url=server) as client:
            league_id = resolve_league_id(client, league)
            board = client.get_campaign_board(league_id)
            player_id = _resolve_player_id(board, player)
            conv = client.get_campaign_conversation(league_id, player_id=player_id, round_no=round_no)
        if json_output:
            emit_json(conv.model_dump(mode="json"))
            return
        flight = " (in flight)" if conv.pending else ""
        console.print(f"[bold]Round {conv.round}{flight}[/bold] — model {conv.model}, {conv.latency_s}s")
        console.print(f"[dim]Retained rounds: {', '.join(str(r) for r in conv.rounds_available)}[/dim]\n")
        if conv.error:
            console.print(f"[red]Strategist call failed:[/red] {conv.error}\n")
        console.print("[bold]Context sent (system frame in --json):[/bold]")
        console.print(conv.context or "(unavailable)")
        console.print("\n[bold]Response:[/bold]")
        for block in conv.response or []:
            if block.get("type") == "text":
                console.print(block.get("text", ""))
            elif block.get("type") == "tool_use":
                console.print(f"[cyan]{block.get('name')}[/cyan] {block.get('input')}")

    @campaign_app.command("full-prompt")
    def campaign_full_prompt(
        league: Annotated[str, typer.Argument(help="League id or name.")],
        player: Annotated[str | None, _PLAYER_OPTION] = None,
        server: Annotated[str, _SERVER_OPTION] = DEFAULT_SUBMIT_SERVER,
        json_output: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
    ) -> None:
        """The complete strategist prompt as it would be sent next round."""
        with CoworldApiClient.from_login(server_url=server) as client:
            league_id = resolve_league_id(client, league)
            board = client.get_campaign_board(league_id)
            player_id = _resolve_player_id(board, player)
            result = client.get_campaign_full_prompt(league_id, player_id=player_id)
        if json_output:
            emit_json(result.model_dump(mode="json"))
            return
        console.print(f"[bold]Model:[/bold] {result.model}")
        console.print(f"[bold]Tools:[/bold] {', '.join(t['name'] for t in result.tools)} (schemas in --json)\n")
        console.print("[bold]System frame:[/bold]")
        console.print(result.system)
        console.print("\n[bold]Board context + your standing orders:[/bold]")
        console.print(result.context)
