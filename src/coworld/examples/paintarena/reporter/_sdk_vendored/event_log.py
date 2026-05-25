"""Canonical event-log Parquet schema and writer.

Every reporter in this repo emits its event-log entries against the
same ``(ts, player, key, value)`` schema, regardless of game. This
alignment lets cross-reporter aggregation use one columnar source and
keeps the schema small enough that adding new event kinds does not
require schema changes (the ``value`` column carries a JSON document).

Conventions:

- ``ts``: episode tick, int64.
- ``player``: player slot (0-based), int64. ``-1`` denotes a global /
  episode-level fact (a pair event, a tile-level fact, etc.).
- ``key``: event name, e.g. ``"proximity"`` or ``"input"``. Stable
  across runs.
- ``value``: JSON-encoded payload string (use :func:`stable_json` from
  :mod:`reporter_sdk.zip_writer` for byte-identical reruns).

Determinism note: pyarrow stamps a ``created_by`` field in the parquet
footer that includes the pyarrow version string. Each reporter pins
``pyarrow`` in its ``requirements.txt``, so two runs of the same image
produce byte-identical parquet bytes. Cross-version reproducibility is
not guaranteed.
"""

from __future__ import annotations

import io
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

# The shared event-log schema. Pinned column types and order — change
# this and you change the cross-reporter contract.
EVENT_LOG_SCHEMA = pa.schema(
    [
        pa.field("ts", pa.int64()),
        pa.field("player", pa.int64()),
        pa.field("key", pa.string()),
        pa.field("value", pa.string()),
    ]
)


def write_events_parquet(rows: list[dict[str, Any]]) -> bytes:
    """Encode event-log rows to Parquet bytes using :data:`EVENT_LOG_SCHEMA`.

    Each row must carry the four schema keys (``ts``, ``player``,
    ``key``, ``value``). An empty list produces a well-formed
    zero-row Parquet table so downstream consumers can read it without
    special-casing absence.
    """
    if rows:
        table = pa.table(
            {
                "ts": pa.array([r["ts"] for r in rows], type=pa.int64()),
                "player": pa.array([r["player"] for r in rows], type=pa.int64()),
                "key": pa.array([r["key"] for r in rows], type=pa.string()),
                "value": pa.array([r["value"] for r in rows], type=pa.string()),
            },
            schema=EVENT_LOG_SCHEMA,
        )
    else:
        table = EVENT_LOG_SCHEMA.empty_table()
    buf = io.BytesIO()
    pq.write_table(
        table,
        buf,
        compression="snappy",
        # Pin a single row group so the row-group boundaries don't drift
        # between runs with different row counts.
        row_group_size=max(len(rows), 1),
    )
    return buf.getvalue()
