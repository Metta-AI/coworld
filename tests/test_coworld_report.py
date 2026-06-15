from __future__ import annotations

import io
import json
import zipfile

import pytest

from coworld.report import (
    ReportRenderError,
    ReportValidationError,
    assert_safe_render_html,
    validate_report_zip,
)


def _report_zip(manifest: dict[str, object], entries: dict[str, bytes] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, payload in (entries or {}).items():
            archive.writestr(name, payload)
    return buffer.getvalue()


# ---------- report-zip structural validation ----------


def test_validate_report_zip_accepts_markdown_render() -> None:
    zip_bytes = _report_zip(
        {"reporter_id": "r", "render": "summary.md"},
        {"summary.md": b"# Episode\n"},
    )

    manifest = validate_report_zip(zip_bytes)

    assert manifest.reporter_id == "r"
    assert manifest.render == "summary.md"


def test_validate_report_zip_accepts_event_log_and_trace_pointers() -> None:
    zip_bytes = _report_zip(
        {"reporter_id": "r", "event_log": "events.parquet", "trace": "trace.jsonl"},
        {"events.parquet": b"PAR1", "trace.jsonl": b"{}\n"},
    )

    manifest = validate_report_zip(zip_bytes)

    assert manifest.event_log == "events.parquet"
    assert manifest.trace == "trace.jsonl"


def test_validate_report_zip_requires_manifest() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        archive.writestr("summary.md", b"# hi")

    with pytest.raises(ReportValidationError, match="missing a top-level manifest.json"):
        validate_report_zip(buffer.getvalue())


def test_validate_report_zip_rejects_missing_render_entry() -> None:
    zip_bytes = _report_zip({"reporter_id": "r", "render": "summary.md"})

    with pytest.raises(ReportValidationError, match="not present in the report zip"):
        validate_report_zip(zip_bytes)


def test_validate_report_zip_rejects_wrong_render_extension() -> None:
    zip_bytes = _report_zip(
        {"reporter_id": "r", "render": "summary.txt"},
        {"summary.txt": b"plain"},
    )

    with pytest.raises(ReportValidationError, match="expected one of"):
        validate_report_zip(zip_bytes)


def test_validate_report_zip_requires_utf8_render_text() -> None:
    zip_bytes = _report_zip(
        {"reporter_id": "r", "render": "summary.md"},
        {"summary.md": b"\xff"},
    )

    with pytest.raises(UnicodeDecodeError):
        validate_report_zip(zip_bytes)


def test_validate_report_zip_rejects_extra_manifest_fields() -> None:
    zip_bytes = _report_zip({"reporter_id": "r", "surprise": "x"})

    with pytest.raises(ValueError, match="surprise"):
        validate_report_zip(zip_bytes)


def test_validate_report_zip_rejects_bad_zip() -> None:
    with pytest.raises(ReportValidationError, match="not a valid zip"):
        validate_report_zip(b"not a zip")


def test_validate_report_zip_runs_render_safety_for_html() -> None:
    zip_bytes = _report_zip(
        {"reporter_id": "r", "render": "summary.html"},
        {"summary.html": b"<p>ok<script>alert(1)</script></p>"},
    )

    with pytest.raises(ReportRenderError, match="inline <script>"):
        validate_report_zip(zip_bytes)


def test_validate_report_zip_accepts_bundled_render_assets() -> None:
    zip_bytes = _report_zip(
        {"reporter_id": "r", "render": "index.html"},
        {
            "index.html": b"""
            <html>
              <head><link rel="stylesheet" href="assets/styles.css"></head>
              <body>
                <img src="assets/chart.png">
                <script src="assets/app.js"></script>
              </body>
            </html>
            """,
            "assets/styles.css": b"body{background:#fff}",
            "assets/chart.png": b"png",
            "assets/app.js": b"console.log('blocked by renderer CSP')",
        },
    )

    manifest = validate_report_zip(zip_bytes)

    assert manifest.render == "index.html"


# ---------- safe render HTML profile ----------


def test_safe_html_accepts_self_contained_document() -> None:
    html = """
    <style>.box { background: url(#none); color: red; }</style>
    <h1>Episode</h1>
    <table><tr><td>Slot 0</td><td>42 tiles</td></tr></table>
    <img src="data:image/png;base64,iVBORw0KGgo=" alt="heatmap">
    <svg viewBox="0 0 10 10"><rect width="10" height="10" fill="#abc"/></svg>
    <a href="https://example.com/policy">policy</a>
    """
    assert_safe_render_html(html)


@pytest.mark.parametrize(
    ("html", "needle"),
    [
        ("<script>alert(1)</script>", "inline <script>"),
        ('<div onclick="x()">hi</div>', "event-handler"),
        ('<a href="javascript:alert(1)">x</a>', "script URL"),
        ('<iframe src="data:text/html,x"></iframe>', "<iframe>"),
        ('<object data="data:x"></object>', "<object>"),
        ('<form action="#"></form>', "<form>"),
        ('<base href="https://evil/">', "<base>"),
        ('<link rel="preconnect" href="data:text/css,x">', "<link> without rel=stylesheet"),
        ('<meta http-equiv="refresh" content="0;url=https://evil/">', "<meta http-equiv>"),
        ('<img src="https://tracker.example/p.gif">', "external resource URL"),
        ('<img src="/local/path.png">', "external resource URL"),
        ('<img src="local/path.png">', "external resource URL"),
        ('<div style="background:url(https://evil/x.png)">x</div>', "external CSS url()"),
        ('<div style="width:expression(alert(1))">x</div>', "unsafe CSS token"),
        ("<style>@import url(https://evil/x.css);</style>", "@import"),
    ],
)
def test_safe_html_rejects_unsafe_constructs(html: str, needle: str) -> None:
    with pytest.raises(ReportRenderError, match=needle):
        assert_safe_render_html(html)


def test_safe_html_reports_every_violation() -> None:
    html = '<script>a</script><div onclick="b()"></div><img src="http://x/y.png">'

    with pytest.raises(ReportRenderError) as excinfo:
        assert_safe_render_html(html)

    message = str(excinfo.value)
    assert "<script>" in message
    assert "event-handler" in message
    assert "external resource URL" in message


def test_safe_html_allows_data_uri_svg_image() -> None:
    # An SVG loaded through <img src=data:> cannot execute script in browsers,
    # so a script-bearing data: SVG image is still safe to embed.
    assert_safe_render_html('<img src="data:image/svg+xml,<svg onload=alert(1)>">')
