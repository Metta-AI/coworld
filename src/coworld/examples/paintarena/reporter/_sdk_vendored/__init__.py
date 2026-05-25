"""Vendored copy of the reporter SDK from ``Metta-AI/reporters``.

This directory is a direct copy of the ``reporter_sdk`` package from the
``Metta-AI/reporters`` repo, pinned to a specific commit so the
paintarena reference reporters in this directory
(``paint_arena_summarizer``, ``stats_reporter``) can run on the canonical
Coworld reporter contract without taking a cross-repo dependency.

**Source of truth (do not edit here):**

- Repo: ``https://github.com/Metta-AI/reporters``
- Path: ``reporters/reporter_sdk/reporter_sdk``
- Commit: ``f9cc98760aac059e1e21e32c05e21dd2442d2362`` (branch
  ``at-summ-09-reporter-sdk-extraction`` at vendor time; the post-F2
  extraction commit)

**Why vendored, not pip-installed:** the upstream SDK's
``pyproject.toml`` currently pins ``requires-python = ">=3.13"``, which
prevents an editable install into ``packages/coworld`` (Python
3.11-3.12). The SDK source itself uses no 3.13-specific syntax, so the
pin is incidental and is expected to be loosened upstream. Once that
lands and is merged to ``reporters`` main, this vendored directory
should be deleted and the import switched to a normal dependency:

.. code-block:: toml

    "reporter-sdk @ git+https://github.com/Metta-AI/reporters.git#subdirectory=reporters/reporter_sdk"

**Why scoped under the paintarena reporter dir rather than at
``coworld.``-root:** keeping the SDK inside ``examples/paintarena/reporter/``
means the existing paintarena Docker build (which copies that directory
into ``/app/coworld/examples/paintarena/reporter/``) picks the SDK up
automatically — no Dockerfile or compose-context changes needed. The
SDK has one consumer in metta today (the two paintarena reference
reporters), so the narrower scope is honest about the dependency graph.

The public surface is identical to the upstream SDK's ``__init__``;
importers use ``from coworld.examples.paintarena.reporter._sdk_vendored
import X``.
"""

from .bundle import BundleInnerManifest, BundleReader
from .event_log import EVENT_LOG_SCHEMA, write_events_parquet
from .io import (
    ReporterInputs,
    load_reporter_inputs,
    read_json,
    read_uri,
    write_uri,
)
from .output_manifest import (
    EVENT_LOG_EXTENSIONS,
    RENDERABLE_EXTENSIONS,
    OutputManifest,
    build_report_zip,
)
from .zip_writer import MTIME_SENTINEL, stable_json, write_deterministic_zip

__all__ = [
    "EVENT_LOG_EXTENSIONS",
    "EVENT_LOG_SCHEMA",
    "MTIME_SENTINEL",
    "RENDERABLE_EXTENSIONS",
    "BundleInnerManifest",
    "BundleReader",
    "OutputManifest",
    "ReporterInputs",
    "build_report_zip",
    "load_reporter_inputs",
    "read_json",
    "read_uri",
    "stable_json",
    "write_deterministic_zip",
    "write_events_parquet",
    "write_uri",
]
