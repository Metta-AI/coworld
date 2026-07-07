"""The safe render profile: reject HTML that is unsafe for the platform to embed.

Author-supplied HTML renders (today: commissioner round reports; historically
reporter report zips, retired by spec 0061) are untrusted, so anything a
platform UI embeds must satisfy the **safe render profile** documented in
``docs/artifacts/RENDER.md``: no external resource loads, no event-handler
script hooks, no inline scripts, and no navigation/embedding sinks.
Platform renderers must also serve the entry inside a sandboxed iframe under a
strict Content-Security-Policy — that sandbox is the authoritative
renderer-side boundary; this static check is fast author-facing feedback
layered in front of it.

Wasm reporter outputs (spec 0061) are checked platform-side by the Bureau's
emit validator, which ports this profile; this module remains the coworld-side
checker for commissioner round-report certification.
"""

from __future__ import annotations

import posixpath
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import urlparse

# HTML elements that embed foreign documents or redirect navigation. They have
# no place in an embeddable report and are rejected outright. ``meta`` is
# handled separately because ``<meta charset>`` is benign while
# ``<meta http-equiv="refresh">`` is not.
DISALLOWED_HTML_TAGS = frozenset({"iframe", "frame", "frameset", "object", "embed", "applet", "base", "form"})

# Attributes that auto-load a resource when the document renders. To avoid
# phone-home / tracking-pixel vectors these must reference inline ``data:``
# payloads, same-document fragments, or relative files bundled in the report zip.
RESOURCE_URL_ATTRS = frozenset({"src", "srcset", "poster", "background", "data", "xlink:href"})

# Attributes that navigate only on user action. External ``http(s)``/``mailto``
# links are fine; only script-bearing schemes are rejected.
LINK_URL_ATTRS = frozenset({"href", "cite", "longdesc"})

# URL schemes that can execute script if a browser follows them.
_SCRIPT_URL_SCHEMES = frozenset({"javascript", "vbscript"})


class ReportRenderError(ValueError):
    """Raised when a render entry violates the safe render profile."""


def assert_safe_render_html(html: str, *, source: str = "render", zip_entries: set[str] | None = None) -> None:
    """Reject HTML that is unsafe for the platform to embed.

    Enforces the safe render profile from ``docs/artifacts/RENDER.md``: no
    inline scripting or event-handler hooks, no script-bearing URLs, no
    embedding / navigation sinks (``<iframe>``, ``<object>``, ``<form>``,
    ``<base>``, ``<meta http-equiv>``, ...), and no automatic external resource
    loads. Resource URLs must be inline ``data:`` payloads, fragments, or
    relative files present in ``zip_entries``. Raises ``ReportRenderError``
    listing every violation found.
    """
    scanner = _SafeHtmlScanner(source_path=PurePosixPath(source), zip_entries=zip_entries)
    scanner.feed(html)
    scanner.close()
    if scanner.violations:
        joined = "\n- ".join(scanner.violations)
        raise ReportRenderError(f"render entry {source!r} is unsafe to embed:\n- {joined}")


class _SafeHtmlScanner(HTMLParser):
    """Collects safe-render-profile violations from an HTML document.

    Blocklist-based by design: it catches the high-signal injection vectors and
    gives authors fast feedback. The platform renderer's sandboxed iframe + CSP
    remain the authoritative boundary, so this scanner favors clear errors over an
    exhaustive allowlist.
    """

    def __init__(self, *, source_path: PurePosixPath, zip_entries: set[str] | None) -> None:
        super().__init__(convert_charrefs=True)
        self.violations: list[str] = []
        self._source_path = source_path
        self._zip_entries = zip_entries
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._check_tag(tag, attrs)
        if tag == "style":
            self._in_style = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._check_tag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self._check_css(data, "<style> element")

    def _check_tag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in DISALLOWED_HTML_TAGS:
            self.violations.append(f"disallowed element <{tag}>")
        if tag == "meta" and any(name.lower() == "http-equiv" for name, _ in attrs):
            self.violations.append("disallowed element <meta http-equiv> (page refresh / redirect)")
        if tag == "script" and not any(name.lower() == "src" and value for name, value in attrs):
            self.violations.append("inline <script> element")
        if tag == "link":
            rel = " ".join(value or "" for name, value in attrs if name.lower() == "rel").lower().split()
            if "stylesheet" not in rel:
                self.violations.append("disallowed <link> without rel=stylesheet")

        for raw_name, value in attrs:
            name = raw_name.lower()
            if name.startswith("on"):
                self.violations.append(f"event-handler attribute {raw_name!r} on <{tag}>")
            elif tag == "link" and name == "href" and value:
                self._check_resource_url(name, value, tag)
            elif name == "style" and value:
                self._check_css(value, f"style attribute on <{tag}>")
            elif name in RESOURCE_URL_ATTRS and value:
                self._check_resource_url(name, value, tag)
            elif name in LINK_URL_ATTRS and value:
                self._check_link_url(name, value, tag)

    def _check_resource_url(self, attr: str, value: str, tag: str) -> None:
        # srcset is a comma-separated list of "url descriptor" candidates.
        candidates = [part.split()[0] for part in value.split(",") if part.split()] if attr == "srcset" else [value]
        for candidate in candidates:
            if _is_self_contained_url(candidate, self._source_path, self._zip_entries):
                continue
            self.violations.append(
                f"external resource URL in {attr!r} on <{tag}>: {candidate!r} "
                "(resource URLs must be inline data: payloads, # fragments, or bundled report files)"
            )

    def _check_link_url(self, attr: str, value: str, tag: str) -> None:
        scheme = urlparse(value.strip()).scheme.lower()
        if scheme in _SCRIPT_URL_SCHEMES:
            self.violations.append(f"script URL in {attr!r} on <{tag}>: {value!r}")
        elif value.strip().lower().replace(" ", "").startswith("data:text/html"):
            self.violations.append(f"data:text/html URL in {attr!r} on <{tag}>: {value!r}")

    def _check_css(self, css: str, where: str) -> None:
        lowered = css.lower()
        for token in ("javascript:", "expression(", "@import"):
            if token in lowered:
                self.violations.append(f"unsafe CSS token {token!r} in {where}")
        for fragment in lowered.split("url(")[1:]:
            target = fragment.split(")", 1)[0].strip().strip("'\"")
            if not _is_self_contained_url(target, self._source_path, self._zip_entries):
                self.violations.append(f"external CSS url() in {where}: {target!r}")


def _is_self_contained_url(value: str, source_path: PurePosixPath, zip_entries: set[str] | None) -> bool:
    """True for inline, same-document, or bundled in-zip resource URLs."""
    stripped = value.strip()
    if stripped == "" or stripped.startswith("#"):
        return True

    parsed = urlparse(stripped)
    scheme = parsed.scheme.lower()
    if scheme == "data":
        return True
    if scheme or parsed.netloc or stripped.startswith("/"):
        return False
    if zip_entries is None:
        return False

    normalized = posixpath.normpath((source_path.parent / parsed.path).as_posix())
    if normalized == "." or normalized == ".." or normalized.startswith("../"):
        return False
    return normalized in zip_entries
