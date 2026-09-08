from typing import Any

import httpx

DEFAULT_SUBMIT_SERVER = "https://softmax.com/api"


def participation_guide_url(server: str, league_id: str) -> str:
    """The platform-generated Markdown guide for entering a public league (``GET /v2/participate``)."""
    return f"{server.rstrip('/')}/observatory/v2/participate?league_id={league_id}"


# Continuation header on bare-list collection endpoints: when present, its value
# is an opaque cursor token that resumes the listing after the last returned row.
# Absent header = no further page.
NEXT_CURSOR_HEADER = "X-Next-Cursor"


def list_page_payload(response: httpx.Response) -> tuple[list[Any], str | None]:
    """The entries and next-page cursor of one bare-list collection response."""
    return response.json(), response.headers.get(NEXT_CURSOR_HEADER)


DEFAULT_OPTIMIZER_REPO = "https://github.com/Metta-AI/optimizers"
DEFAULT_OPTIMIZER_REF = "main"
DEFAULT_OPTIMIZER_PORT = 3000
