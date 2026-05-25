"""Deterministic zip writer.

The canonical reporter contract recommends — but does not require —
byte-identical reruns over identical inputs. Pinning each entry's
``date_time`` to a fixed sentinel removes the only nondeterministic
field the zip local-file header carries, so two invocations of the same
reporter image over identical inputs produce identical zip bytes.

The sentinel ``(1980, 1, 1, 0, 0, 0)`` is the zip-format minimum
(DOS epoch); it is the conventional choice for deterministic builds
across the Python ecosystem (e.g. ``pip wheel --build-isolation``).

Determinism inside Parquet entries is bounded separately by the pinned
``pyarrow`` version each reporter's ``requirements.txt`` carries — the
parquet footer embeds the writer version string. See
:mod:`reporter_sdk.event_log` for the writer side.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

# Pinned zip-entry mtime for byte-identical reruns. The zip format's DOS
# epoch is its minimum representable value.
MTIME_SENTINEL = (1980, 1, 1, 0, 0, 0)


def write_deterministic_zip(entries: list[tuple[str, bytes]]) -> bytes:
    """Build a zip with pinned mtimes for byte-identical reruns.

    Entry order is preserved as given. Each entry's ``date_time`` is
    pinned to :data:`MTIME_SENTINEL`. Compression is DEFLATE; entries
    are not stored uncompressed.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in entries:
            info = zipfile.ZipInfo(filename=name, date_time=MTIME_SENTINEL)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, payload)
    return buf.getvalue()


def stable_json(obj: Any) -> str:
    """Compact JSON encoding with sorted keys.

    Used for any JSON payload embedded inside another container (event-log
    ``value`` strings, the in-zip ``manifest.json``) where byte stability
    across runs matters. Plain :func:`json.dumps` is fine for top-level
    JSON blobs whose key order is already deterministic by construction.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))
