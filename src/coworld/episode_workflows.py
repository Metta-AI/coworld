from __future__ import annotations

import random
import sys
import time
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

import typer
from pydantic import BaseModel, Field, TypeAdapter

from coworld.api_client import (
    CoworldApiClient,
    EpisodeArtifactCategory,
    EpisodeFeedRestart,
    EpisodeFeedRetry,
    EpisodeView,
)
from coworld.cli_support import emit_json
from coworld.config import DEFAULT_SUBMIT_SERVER
from coworld.episode_downloads import download_episodes, write_json_atomic


class View(str, Enum):
    progress = "progress"
    results = "results"


class Until(str, Enum):
    execution = "execution"
    evidence = "evidence"


class WatchedEpisode(BaseModel):
    revision: int
    status: str
    evidence_state: Literal["pending", "sealed"]


class WatchCheckpoint(BaseModel):
    server: str
    ids: list[str]
    view: EpisodeView
    until: Literal["execution", "evidence"]
    include: list[EpisodeArtifactCategory]
    cursor: str | None = None
    episodes: dict[str, WatchedEpisode] = Field(default_factory=dict)
    inventory_requested: bool = False


def validate_selection(ids: list[str], *, batches_only: bool = False) -> list[str]:
    selected = sorted(set(ids))
    kinds = {value.split("_", 1)[0] for value in selected}
    if not 1 <= len(selected) <= 50 or kinds not in ({"xreq"}, {"ereq"}) or (batches_only and kinds != {"xreq"}):
        raise typer.BadParameter(
            "Select 1–50 batch IDs (xreq_...) or episode IDs (ereq_...); watch accepts batches only."
        )
    return selected


def watch_episodes(
    client: CoworldApiClient,
    state: WatchCheckpoint,
    *,
    checkpoint: Path | None,
    timeout: float,
    jsonl: bool,
) -> int:
    deadline = time.monotonic() + timeout
    idle_delay = 2.0
    while time.monotonic() < deadline:
        page = client.episode_changes(state.ids, view=state.view, cursor=state.cursor)
        if isinstance(page, EpisodeFeedRestart):
            typer.echo(
                f"Watch cannot resume (HTTP {page.status_code}). Check access, then use --reset for a fresh snapshot.",
                err=True,
            )
            return 2
        if isinstance(page, EpisodeFeedRetry):
            delay = page.retry_after_seconds + random.uniform(0, 0.25)
        else:
            for entry in page.entries:
                previous = state.episodes.get(entry.id)
                if previous is None or entry.revision >= previous.revision:
                    state.episodes[entry.id] = WatchedEpisode(
                        revision=entry.revision,
                        status="removed" if entry.episode is None else entry.episode.status,
                        evidence_state="sealed" if entry.episode is None else entry.episode.evidence_state,
                    )
            if jsonl:
                typer.echo(page.model_dump_json())
            else:
                for entry in page.entries:
                    status = "removed" if entry.removed else entry.episode.status if entry.episode else "unavailable"
                    typer.echo(f"{entry.id} {status}")
            sys.stdout.flush()
            state.cursor = page.next_cursor
            if checkpoint is not None:
                write_json_atomic(checkpoint, state)
            if page.has_more:
                continue
            episodes = [e for e in state.episodes.values() if e.status != "removed"]
            terminal = {"completed", "failed", "cancelled"}
            execution_done = all(b.status in terminal for b in page.batches) and all(
                e.status in terminal for e in episodes
            )
            if execution_done:
                failed = any(b.status != "completed" for b in page.batches) or any(
                    e.status != "completed" for e in episodes
                )
                if state.until == "execution":
                    return 2 if failed else 0
                if not state.inventory_requested or all(e.evidence_state == "sealed" for e in episodes):
                    manifest_cursor = None
                    evidence_pending = False
                    evidence_unavailable = False
                    while True:
                        if time.monotonic() >= deadline:
                            return 3
                        manifest = client.episode_download_manifest(
                            state.ids, include=state.include, cursor=manifest_cursor
                        )
                        evidence_pending |= any(e.state == "pending" for e in manifest.entries)
                        evidence_unavailable |= bool(manifest.unavailable_ids) or any(
                            e.state == "unavailable" for e in manifest.entries
                        )
                        manifest_cursor = manifest.next_cursor
                        if manifest_cursor is None:
                            break
                    state.inventory_requested = True
                    if checkpoint is not None:
                        write_json_atomic(checkpoint, state)
                    if not evidence_pending and all(e.evidence_state == "sealed" for e in episodes):
                        return 2 if failed or evidence_unavailable else 0
            idle_delay = 2.0 if page.entries else min(10.0, idle_delay * 1.5)
            delay = max(idle_delay, page.poll_after_seconds) + random.uniform(0, 0.25)
        remaining = deadline - time.monotonic()
        if remaining <= delay:
            typer.echo("Watch timed out; resume with the same checkpoint.", err=True)
            return 3
        time.sleep(delay)
    return 3


def register_episode_workflows(app: typer.Typer) -> None:
    @app.command("episodes", help="Read a page of episodes from up to 50 batches or episode IDs.")
    def episodes(
        ids: Annotated[list[str], typer.Argument()],
        view: Annotated[View, typer.Option()] = View.progress,
        status: Annotated[list[str] | None, typer.Option(help="Execution status; repeat to select several.")] = None,
        limit: Annotated[int, typer.Option(min=1, max=200)] = 200,
        cursor: Annotated[str | None, typer.Option()] = None,
        json_output: Annotated[
            bool, typer.Option("--json", help="Print one JSON page, including its next cursor.")
        ] = False,
        jsonl: Annotated[bool, typer.Option(help="Stream every page as one JSON object per line.")] = False,
        server: Annotated[str, typer.Option()] = DEFAULT_SUBMIT_SERVER,
    ) -> None:
        selected = validate_selection(ids)
        if json_output and jsonl:
            raise typer.BadParameter("Choose --json or --jsonl")
        with CoworldApiClient.from_login(server_url=server) as client:
            while True:
                page = client.list_bulk_episodes(selected, view=view.value, statuses=status, limit=limit, cursor=cursor)
                if jsonl:
                    typer.echo(page.model_dump_json())
                elif json_output:
                    emit_json(page.model_dump(mode="json"))
                else:
                    for entry in page.entries:
                        score = (
                            "" if entry.scores is None else " scores=" + ",".join(str(s.score) for s in entry.scores)
                        )
                        typer.echo(f"{entry.id} {entry.status}{score}")
                    if page.next_cursor is not None:
                        typer.echo(f"Next cursor: {page.next_cursor}")
                if page.unavailable_ids:
                    typer.echo("Unavailable selectors: " + ", ".join(page.unavailable_ids), err=True)
                    raise typer.Exit(2)
                cursor = page.next_cursor
                if not jsonl or cursor is None:
                    break

    @app.command("watch", help="Follow batch changes with a resumable checkpoint.")
    def watch(
        ids: Annotated[list[str], typer.Argument()],
        view: Annotated[View, typer.Option()] = View.progress,
        until: Annotated[Until, typer.Option()] = Until.execution,
        include: Annotated[
            list[str] | None, typer.Option(help="Evidence categories required for --until evidence.")
        ] = None,
        checkpoint: Annotated[Path | None, typer.Option()] = None,
        reset: Annotated[bool, typer.Option(help="Replace the checkpoint with a fresh snapshot.")] = False,
        timeout: Annotated[float, typer.Option(min=1, help="Maximum watch duration in seconds.")] = 3600,
        jsonl: Annotated[bool, typer.Option(help="Emit change pages as JSON Lines; duplicates are possible.")] = False,
        server: Annotated[str, typer.Option()] = DEFAULT_SUBMIT_SERVER,
    ) -> None:
        selected = validate_selection(ids, batches_only=True)
        categories = TypeAdapter(list[EpisodeArtifactCategory]).validate_python(include or [])
        if until == Until.evidence and not categories:
            raise typer.BadParameter("--until evidence requires --include")
        state = WatchCheckpoint(server=server, ids=selected, view=view.value, until=until.value, include=categories)
        if checkpoint is not None and checkpoint.exists() and not reset:
            previous = WatchCheckpoint.model_validate_json(checkpoint.read_text())
            if previous.model_dump(exclude={"cursor", "episodes", "inventory_requested"}) != state.model_dump(
                exclude={"cursor", "episodes", "inventory_requested"}
            ):
                raise typer.BadParameter("Checkpoint selection differs; use --reset to start a new snapshot")
            state = previous
        with CoworldApiClient.from_login(server_url=server) as client:
            code = watch_episodes(client, state, checkpoint=checkpoint, timeout=timeout, jsonl=jsonl)
        raise typer.Exit(code)

    @app.command("download", help="Download selected evidence directly from storage; rerun to resume.")
    def download(
        ids: Annotated[list[str], typer.Argument()],
        include: Annotated[list[str], typer.Option(help="Evidence category; repeat for multiple categories.")],
        directory: Annotated[Path, typer.Option("--directory", "-d")],
        agent: Annotated[list[int] | None, typer.Option(min=0)] = None,
        concurrency: Annotated[int, typer.Option(min=1, max=16)] = 4,
        server: Annotated[str, typer.Option()] = DEFAULT_SUBMIT_SERVER,
    ) -> None:
        selected = validate_selection(ids)
        categories = TypeAdapter(list[EpisodeArtifactCategory]).validate_python(include)
        with CoworldApiClient.from_login(server_url=server) as client:
            complete = download_episodes(
                client, selected, include=categories, agents=agent, directory=directory, concurrency=concurrency
            )
        typer.echo(f"Download receipts: {directory / 'manifest.jsonl'}")
        if not complete:
            typer.echo("Some requested evidence is pending or unavailable; see the receipts.", err=True)
        raise typer.Exit(0 if complete else 2)
