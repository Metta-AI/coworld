from __future__ import annotations

import pytest

from coworld.report import ReportRenderError, assert_safe_render_html

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


def test_safe_html_accepts_bundled_relative_assets_with_zip_entries() -> None:
    html = """
    <link rel="stylesheet" href="assets/styles.css">
    <img src="assets/chart.png">
    <script src="assets/app.js"></script>
    """
    assert_safe_render_html(
        html,
        source="index.html",
        zip_entries={"index.html", "assets/styles.css", "assets/chart.png", "assets/app.js"},
    )


def test_safe_html_allows_data_uri_svg_image() -> None:
    # An SVG loaded through <img src=data:> cannot execute script in browsers,
    # so a script-bearing data: SVG image is still safe to embed.
    assert_safe_render_html('<img src="data:image/svg+xml,<svg onload=alert(1)>">')
