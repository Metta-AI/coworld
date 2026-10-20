"""Offline statistics extraction and validation using the public reporter contract."""

from __future__ import annotations

import hashlib
import json
import webbrowser
from concurrent.futures import ProcessPoolExecutor
from html import escape
from pathlib import Path
from typing import Annotated

import typer
from pydantic import Field, TypeAdapter, ValidationError

from coworld.examples.paintarena.stats import METRICS, ReplayInput, extract_stats
from coworld.stats import EpisodeStats, MeasuredValue, StatsBlock, StatsFailure, get_coworld_stats_schema

stats_app = typer.Typer(no_args_is_help=True, help="Extract and validate versioned Coworld behavior statistics.")


@stats_app.command("schema")
def schema() -> None:
    """Print the supported JSON Schema without contacting a service."""
    typer.echo(json.dumps(get_coworld_stats_schema(), indent=2))


@stats_app.command("validate")
def validate(path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)]) -> None:
    """Validate a complete stats block, including measurement semantics."""
    block = StatsBlock.model_validate_json(path.read_bytes())
    typer.echo(f"Valid coworld.stats.v1: {len(block.episodes)} episodes, {len(block.failures)} failures")


def render_stats(block: StatsBlock) -> str:
    """A script-free evidence table suitable for a reporter render-html output."""
    content = [
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Coworld statistics</title>',
        "<style>body{font:16px system-ui;margin:2rem;color:#27323c}table{border-collapse:collapse;margin:1rem 0}",
        "th,td{padding:.6rem 1rem;text-align:left;border-bottom:1px solid #d8dfe5}",
        "th{background:#edf2f5}.unavailable{color:#69747f}.failure{background:#fae8e8;padding:1rem}</style>",
        "<h1>Coworld statistics</h1>",
        f"<p>{len(block.episodes)} extracted episodes; {len(block.failures)} failed replays.</p>",
    ]
    for episode in block.episodes:
        content.append(f"<h2>{escape(episode.provenance.episode_id)}</h2>")
        content.append("<table><thead><tr><th>Metric</th>")
        content.extend(
            f"<th>{escape(seat.policy_id or 'Unidentified policy')} (seat {escape(seat.seat_id)})</th>"
            for seat in episode.seats
        )
        content.append("</tr></thead><tbody>")
        for category, label in (
            ("direct", "Direct control"),
            ("opportunity_dependent", "Opportunity-dependent control"),
            ("outcome", "Outcomes"),
        ):
            content.append(f'<tr><th colspan="{len(episode.seats) + 1}">{label}</th></tr>')
            for metric in episode.metrics:
                if metric.category != category:
                    continue
                content.append(f"<tr><th>{escape(metric.name)} ({escape(metric.unit)})</th>")
                for seat in episode.seats:
                    measurement = next(item for item in seat.measurements if item.metric_id == metric.id)
                    if isinstance(measurement, MeasuredValue):
                        value = f"{measurement.value:.6g}"
                        if measurement.denominator is not None:
                            value += f" ({measurement.count}/{measurement.denominator})"
                        content.append(f"<td>{value}</td>")
                    else:
                        detail = (
                            "No eligible opportunities"
                            if measurement.status == "no_opportunities"
                            else measurement.reason
                        )
                        content.append(f'<td class="unavailable">{escape(measurement.status)}: {escape(detail)}</td>')
                content.append("</tr>")
        content.append("</tbody></table><details><summary>Definitions and source identity</summary><pre>")
        content.append(
            escape(
                json.dumps(
                    {
                        "provenance": episode.provenance.model_dump(mode="json"),
                        "metrics": [metric.model_dump(mode="json") for metric in episode.metrics],
                    },
                    indent=2,
                )
            )
        )
        content.append("</pre></details>")
    for failure in block.failures:
        content.append(f'<p class="failure">{escape(failure.provenance.episode_id)}: {escape(failure.reason)}</p>')
    content.append("</html>")
    return "\n".join(content)


def _extract_or_reuse(source: ReplayInput, output: Path) -> EpisodeStats:
    identity = hashlib.sha256(source.episode_id.encode()).hexdigest()
    target = output / f"{identity}.json"
    if target.exists():
        episode = EpisodeStats.model_validate_json(target.read_bytes())
        if (
            episode.provenance != source.provenance()
            or episode.metrics != METRICS
            or [(seat.policy_id, seat.policy_sha256) for seat in episode.seats]
            != [(policy.id, policy.sha256) for policy in source.policies]
            or hashlib.sha256(source.path.read_bytes()).hexdigest() != source.replay_sha256
        ):
            raise ValueError("Existing episode evidence differs from the requested input; use a new output directory")
        return episode
    episode = extract_stats(source)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(episode.model_dump_json(indent=2) + "\n")
    temporary.replace(target)
    return episode


@stats_app.command("extract-paintarena")
def extract_paintarena(
    manifest: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="JSON list of replay input receipts.")],
    output: Annotated[Path, typer.Argument(help="Output directory; matching completed episodes are reused.")],
    workers: Annotated[int, typer.Option(min=1, max=32, help="Maximum parallel replay workers.")] = 4,
    open_report: Annotated[
        bool, typer.Option("--open/--no-open", help="Request a browser preview after rendering.")
    ] = True,
) -> None:
    """Extract a replay batch and render its evidence, preserving per-replay failures."""
    sources = TypeAdapter(Annotated[list[ReplayInput], Field(min_length=1)]).validate_json(manifest.read_bytes())
    if len({source.episode_id for source in sources}) != len(sources):
        raise typer.BadParameter("Input episode IDs must be unique")
    for source in sources:
        source.path = (manifest.resolve().parent / source.path).resolve()
    output = output.resolve()
    inputs = {manifest.resolve(), *(source.path for source in sources)}
    reserved_dirs = [(output / name).resolve() for name in ("episodes", "batches")]
    targets = [output, output / "stats.json", output / "report.html"]
    for source in sources:
        identity = hashlib.sha256(source.episode_id.encode()).hexdigest()
        targets.extend(output / "episodes" / f"{identity}{suffix}" for suffix in (".json", ".tmp"))
    targets.extend(path for directory in reserved_dirs for path in directory.glob("*"))
    for path in inputs:
        if any(path.is_relative_to(directory) for directory in reserved_dirs) or any(
            path == target.resolve() or (path.exists() and target.exists() and path.samefile(target))
            for target in targets
        ):
            raise typer.BadParameter("Input files overlap reserved output paths; choose a separate output directory")
    output.mkdir(parents=True, exist_ok=True)
    episodes_dir = output / "episodes"
    episodes_dir.mkdir(exist_ok=True)
    episodes = []
    failures = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        jobs = [executor.submit(_extract_or_reuse, source, episodes_dir) for source in sources]
        for source, job in zip(sources, jobs, strict=True):
            error = job.exception()
            if error is None:
                episodes.append(job.result())
            else:
                reason = (
                    json.dumps(error.errors(include_url=False, include_context=False, include_input=False))
                    if isinstance(error, ValidationError)
                    else f"{type(error).__name__}: {error}"
                )
                failures.append(StatsFailure(provenance=source.provenance(), reason=reason))
    block = StatsBlock(schema_version="coworld.stats.v1", episodes=episodes, failures=failures)
    block_bytes = (block.model_dump_json(indent=2) + "\n").encode()
    batches_dir = output / "batches"
    batches_dir.mkdir(exist_ok=True)
    snapshot = batches_dir / f"{hashlib.sha256(block_bytes).hexdigest()}.json"
    if snapshot.exists():
        if snapshot.read_bytes() != block_bytes:
            raise ValueError("Existing batch snapshot does not match its content hash")
    else:
        temporary = snapshot.with_suffix(".tmp")
        temporary.write_bytes(block_bytes)
        temporary.replace(snapshot)
    (output / "stats.json").write_bytes(block_bytes)
    report = output / "report.html"
    report.write_text(render_stats(block))
    typer.echo(f"{len(episodes)} extracted, {len(failures)} failed. Report: {report.resolve()}")
    if open_report and not webbrowser.open(report.resolve().as_uri()):
        typer.echo("Browser preview unavailable; the HTML report remains available at the printed path.")
    if failures:
        raise typer.Exit(code=1)
