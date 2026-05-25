"""PaintArena summarizer reporter (reference / canonical contract).

Pure function of the episode bundle pointed at by ``COGAME_EPISODE_BUNDLE_URI``.
Produces a single ``.zip`` written to ``COGAME_REPORT_URI`` containing a
Markdown summary and a JSON stats blob, plus a top-level ``manifest.json``
flagging ``summary.md`` as the renderable per the canonical Coworld
reporter contract (``docs/roles/reporter.md`` in this package).

This reporter is the minimal *reference* implementation of the contract
for a PaintArena bundle. Grid dimensions come from the game-owned
replay's ``config``. PaintArena's replay format is defined by its game
server in coworld (``examples/paintarena/game/server.py::_replay_payload``).

The richer production summarizer (HTML, SVG heatmap, parquet event log,
back-and-forth highlights) lives in the ``Metta-AI/reporters`` repo at
``reporters/paint_arena/paint_arena_summarizer``. This in-repo reference
intentionally stays markdown-only so the example tree exercises the
contract surface without taking on the production reporter's dependency
surface (pyarrow on the markdown path is optional).

Shared primitives (``BundleReader``, ``ReporterInputs``, ``read_uri`` /
``write_uri``, ``write_deterministic_zip``, the output ``manifest.json``
writer) live in the vendored ``reporter_sdk`` at
``coworld.examples.paintarena.reporter._sdk_vendored`` and are re-exported below so test
code referencing this module's attributes continues to work without
reaching into the vendored package.
"""

from __future__ import annotations

# ``time`` and ``requests`` are intentionally imported (and used by the
# SDK at module-singleton level) so test code can ``monkeypatch.setattr(
# par.time, "sleep", ...)`` and ``monkeypatch.setattr(par.requests,
# "request", ...)`` without reaching into the vendored SDK module.
import json
import sys
import time  # noqa: F401  (re-exported for monkeypatching)
from typing import Any

import requests  # noqa: F401  (re-exported for monkeypatching)
from pydantic import BaseModel, NonNegativeInt

from coworld.examples.paintarena.reporter._sdk_vendored import (
    BundleInnerManifest,
    BundleReader,
    OutputManifest,
    ReporterInputs,
    build_report_zip,
    load_reporter_inputs,
    read_json,
    read_uri,
    write_deterministic_zip,
    write_uri,
)

# Re-exported for the test suite, which references ``par._HTTP_MAX_ATTEMPTS``.
from coworld.examples.paintarena.reporter._sdk_vendored.io import _HTTP_MAX_ATTEMPTS  # noqa: F401

# Public re-exports — tests import these as attributes of this module.
__all__ = [
    "BundleInnerManifest",
    "BundleReader",
    "OutputManifest",
    "ReporterInputs",
    "build_report_zip",
    "load_reporter_inputs",
    "read_json",
    "read_uri",
    "write_deterministic_zip",
    "write_uri",
]

# The reporter's self-identifying id, stamped into the output zip's
# ``manifest.json`` ``reporter_id`` field. Matches the runnable's ``id``
# in ``manifest.reporter[]``.
REPORTER_ID = "paint-arena-summarizer"


# ---------- PaintArena-specific input/output types ----------


class PaintArenaResults(BaseModel):
    scores: list[float]
    painted_tiles: list[NonNegativeInt]
    ticks: NonNegativeInt


class PlayerMetadata(BaseModel):
    slot: int
    policy_name: str | None = None


class EpisodeMetadata(BaseModel):
    """Episode-level metadata used to populate ``stats.json`` and the
    Markdown header.

    The canonical reporter contract does not formally carry these fields
    in the bundle's inner ``manifest.json``; in practice they reach the
    reporter via the bundle's optional ``metadata`` token. When that
    token is absent, every field falls back to a default and ``episode_id``
    is populated from the bundle's ``ereq_id`` so the rendered summary
    still names the episode."""

    episode_id: str | None = None
    variant_id: str = "unknown"
    duration_seconds: float | None = None
    players: list[PlayerMetadata] = []


class ReplayConfig(BaseModel):
    # Subset of the PaintArena replay's `config` dict that this reporter
    # consumes. Other config fields (max_ticks, tick_rate, players, ...) are
    # ignored. See packages/coworld/.../paintarena/game/server.py::_replay_payload.
    width: int
    height: int


class PaintArenaReplay(BaseModel):
    # Subset of the PaintArena replay payload. Other top-level fields
    # (player_names, frames, results) are ignored by this reporter.
    config: ReplayConfig


class SlotStats(BaseModel):
    slot: int
    policy_name: str
    painted_tiles: int
    share_pct: float


class GridStats(BaseModel):
    width: int
    height: int
    total_tiles: int


class PaintArenaStats(BaseModel):
    episode_id: str | None
    variant_id: str
    grid: GridStats
    ticks: int
    duration_seconds: float | None
    slots: list[SlotStats]
    unpainted_tiles: int
    unpainted_share_pct: float
    winner_slot: int | None
    margin_tiles: int
    tie: bool


# ---------- PaintArena-specific logic ----------


def build_stats(
    results: PaintArenaResults,
    metadata: EpisodeMetadata,
    config: ReplayConfig,
) -> PaintArenaStats:
    width = config.width
    height = config.height
    total_tiles = width * height

    policy_by_slot = {p.slot: p.policy_name for p in metadata.players if p.policy_name}
    slots = [
        SlotStats(
            slot=i,
            policy_name=policy_by_slot.get(i) or f"Slot {i}",
            painted_tiles=count,
            share_pct=round(count / total_tiles * 100.0, 2) if total_tiles > 0 else 0.0,
        )
        for i, count in enumerate(results.painted_tiles)
    ]

    total_painted = sum(results.painted_tiles)
    unpainted = max(total_tiles - total_painted, 0)
    unpainted_share = round(unpainted / total_tiles * 100.0, 2) if total_tiles > 0 else 0.0

    if total_painted == 0:
        winner_slot: int | None = None
        margin = 0
        tie = False
    else:
        max_count = max(results.painted_tiles)
        leaders = [i for i, c in enumerate(results.painted_tiles) if c == max_count]
        if len(leaders) > 1:
            winner_slot = None
            margin = 0
            tie = True
        else:
            winner_slot = leaders[0]
            others = [c for i, c in enumerate(results.painted_tiles) if i != winner_slot]
            margin = max_count - max(others) if others else max_count
            tie = False

    return PaintArenaStats(
        episode_id=metadata.episode_id,
        variant_id=metadata.variant_id,
        grid=GridStats(width=width, height=height, total_tiles=total_tiles),
        ticks=results.ticks,
        duration_seconds=metadata.duration_seconds,
        slots=slots,
        unpainted_tiles=unpainted,
        unpainted_share_pct=unpainted_share,
        winner_slot=winner_slot,
        margin_tiles=margin,
        tie=tie,
    )


def render_summary_markdown(stats: PaintArenaStats) -> str:
    grid = stats.grid
    if stats.duration_seconds is not None:
        duration = f"{stats.duration_seconds:.1f} s ({stats.ticks} ticks)"
    else:
        duration = f"{stats.ticks} ticks"

    lines = [
        f"# PaintArena — Episode {stats.episode_id or 'unknown'}",
        "",
        (
            f"**Variant:** {stats.variant_id} · "
            f"**Grid:** {grid.width} × {grid.height} ({grid.total_tiles} tiles) · "
            f"**Duration:** {duration}"
        ),
        "",
        "| Slot | Policy | Tiles painted | Share |",
        "| --- | --- | --- | --- |",
    ]
    for s in stats.slots:
        lines.append(f"| {s.slot} | {s.policy_name} | {s.painted_tiles} / {grid.total_tiles} | {s.share_pct:.1f}% |")
    lines.append(f"| — | unpainted | {stats.unpainted_tiles} / {grid.total_tiles} | {stats.unpainted_share_pct:.1f}% |")
    lines.append("")

    if stats.winner_slot is None and stats.unpainted_tiles == grid.total_tiles:
        lines.append("**Result:** no tiles were painted; no winner.")
    elif stats.tie:
        max_painted = max(s.painted_tiles for s in stats.slots)
        leaders = [s for s in stats.slots if s.painted_tiles == max_painted]
        lines.append(f"**Result:** tied at {max_painted} tiles ({', '.join(s.policy_name for s in leaders)}).")
    else:
        winner = next(s for s in stats.slots if s.slot == stats.winner_slot)
        lines.append(f"**Winner:** Slot {winner.slot} ({winner.policy_name}) by {stats.margin_tiles} tiles.")
    return "\n".join(lines) + "\n"


def build_zip_bytes(
    results: PaintArenaResults,
    metadata: EpisodeMetadata,
    replay: PaintArenaReplay,
) -> bytes:
    """Build the canonical output zip: top-level ``manifest.json`` flagging
    ``summary.md`` as the render target, plus ``summary.md`` (rendered)
    and ``stats.json`` (auxiliary)."""
    stats = build_stats(results, metadata, replay.config)
    summary_md = render_summary_markdown(stats).encode("utf-8")
    stats_json = (json.dumps(stats.model_dump(), indent=2) + "\n").encode("utf-8")
    return build_report_zip(
        OutputManifest(
            reporter_id=REPORTER_ID,
            render="summary.md",
        ),
        [
            ("summary.md", summary_md),
            ("stats.json", stats_json),
        ],
    )


# ---------- orchestration ----------


def run(inputs: ReporterInputs) -> None:
    with BundleReader(inputs.episode_bundle_uri) as bundle:
        inner = bundle.inner_manifest()
        if inner.status != "success":
            raise RuntimeError(f"bundle status={inner.status!r}; reporter cannot operate on a failed episode")
        results = PaintArenaResults.model_validate(bundle.read_json("results"))
        replay = PaintArenaReplay.model_validate(bundle.read_json("replay"))
        metadata_payload = bundle.read_json_optional("metadata")
        # Only None (token absent) coalesces to {}. A present-but-not-dict payload (`[]`, `""`,
        # `0`, etc.) is upstream bundle corruption — fail fast rather than getting an
        # AttributeError on the next line's .setdefault() or a confusing EpisodeMetadata error.
        if metadata_payload is not None and not isinstance(metadata_payload, dict):
            raise ValueError(f"metadata token must be a JSON object, got {type(metadata_payload).__name__}")
        metadata_raw: dict[str, Any] = {} if metadata_payload is None else metadata_payload
    metadata_raw.setdefault("episode_id", inner.ereq_id)
    metadata = EpisodeMetadata.model_validate(metadata_raw)
    payload = build_zip_bytes(results=results, metadata=metadata, replay=replay)
    write_uri(inputs.report_uri, payload, content_type="application/zip")
    print(
        f"[{REPORTER_ID}] wrote zip to {inputs.report_uri}",
        file=sys.stderr,
        flush=True,
    )


if __name__ == "__main__":
    run(load_reporter_inputs())
