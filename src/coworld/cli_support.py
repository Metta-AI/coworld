from __future__ import annotations

import json
import sys
from typing import Any
from urllib.parse import urlparse, urlunparse

from rich.console import Console

console = Console()


def emit_json(payload: Any) -> None:
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")


def observatory_web_url(server: str, path: str) -> str:
    if path.startswith(("http://", "https://")):
        return path

    # The Observatory API is mounted under /api (the upload client appends /observatory) on the same
    # host as the web app, so the web origin is the server with that API path prefix stripped.
    parsed = urlparse(server)
    if parsed.path.rstrip("/") in ("/api", "/api/observatory"):
        origin = urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
        return f"{origin}{path}"
    return path
