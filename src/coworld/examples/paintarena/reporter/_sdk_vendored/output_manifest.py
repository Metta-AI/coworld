"""Output ``manifest.json`` model and validated report-zip builder.

Every reporter writes a zip to ``COGAME_REPORT_URI``. The zip's
top-level ``manifest.json`` self-describes the report for downstream
consumers (Observatory, the platform's report viewer, future
aggregators):

.. code-block:: json

    {
      "reporter_id": "paint-arena-summarizer",
      "render": "summary.html",
      "event_log": "proximity.parquet"
    }

``render`` is optional and at most one entry; if set it must point at an
in-zip ``.md`` or ``.html`` entry. ``event_log`` is optional and at most
one entry; if set it must point at an in-zip ``.parquet`` entry. The
validation in :func:`build_report_zip` enforces both constraints before
the zip is produced — a misdeclared manifest is the kind of bug that
silently breaks the platform's report viewer, so reporters fail fast.

See metta's ``packages/coworld/src/coworld/docs/roles/REPORTER.md`` for
the canonical contract this implements.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from pydantic import BaseModel

from .zip_writer import stable_json, write_deterministic_zip

# Renderable extensions for the ``render`` field. Lowercase compared.
RENDERABLE_EXTENSIONS = frozenset({".md", ".html"})

# Event-log file extensions for the ``event_log`` field. Lowercase compared.
EVENT_LOG_EXTENSIONS = frozenset({".parquet"})


class OutputManifest(BaseModel):
    """The shape of the in-zip ``manifest.json`` a reporter emits.

    ``reporter_id`` is conventionally the runnable's ``id`` from the
    coworld manifest (e.g. ``"paint-arena-summarizer"``). ``render`` is
    the in-zip path to a ``.md`` or ``.html`` UIs should display.
    ``event_log`` is the in-zip path to a Parquet file using the
    canonical event-log schema (see :mod:`reporter_sdk.event_log`).
    """

    reporter_id: str
    render: str | None = None
    event_log: str | None = None


def build_report_zip(
    manifest: OutputManifest,
    entries: list[tuple[str, bytes]],
) -> bytes:
    """Validate ``manifest`` against ``entries`` and build a deterministic
    zip with ``manifest.json`` prepended.

    Validation:

    - ``manifest.render``, if set, must equal the name of an entry in
      ``entries`` whose lowercase extension is in
      :data:`RENDERABLE_EXTENSIONS`.
    - ``manifest.event_log``, if set, must equal the name of an entry in
      ``entries`` whose lowercase extension is in
      :data:`EVENT_LOG_EXTENSIONS`.

    Misdeclared manifests raise ``ValueError``. The output ``manifest.json``
    payload is written with :func:`stable_json` so the bytes are stable
    across runs over identical inputs.
    """
    names = {name for name, _ in entries}

    if manifest.render is not None:
        if manifest.render not in names:
            raise ValueError(f"manifest.render={manifest.render!r} is not present in the report zip entries")
        ext = PurePosixPath(manifest.render).suffix.lower()
        if ext not in RENDERABLE_EXTENSIONS:
            raise ValueError(
                f"manifest.render={manifest.render!r} has extension {ext!r}; "
                f"expected one of {sorted(RENDERABLE_EXTENSIONS)}"
            )

    if manifest.event_log is not None:
        if manifest.event_log not in names:
            raise ValueError(f"manifest.event_log={manifest.event_log!r} is not present in the report zip entries")
        ext = PurePosixPath(manifest.event_log).suffix.lower()
        if ext not in EVENT_LOG_EXTENSIONS:
            raise ValueError(
                f"manifest.event_log={manifest.event_log!r} has extension {ext!r}; "
                f"expected one of {sorted(EVENT_LOG_EXTENSIONS)}"
            )

    manifest_bytes = stable_json(manifest.model_dump(exclude_none=False)).encode("utf-8")
    return write_deterministic_zip([("manifest.json", manifest_bytes), *entries])
