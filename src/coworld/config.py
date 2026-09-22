from typing import Any

import httpx

from softmax.docs import DOCS_URL

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


# Public documentation for the workflows the CLI drives. Command help points at the page
# for its workflow so an agent that only ever runs `--help` still finds the docs site.
DOCS_PAGES = {
    "choose-a-coworld": f"{DOCS_URL}/coworld/build-a-player/choose-a-coworld",
    "package-and-verify": f"{DOCS_URL}/coworld/build-a-player/package-and-verify",
    "upload-and-evaluate": f"{DOCS_URL}/coworld/build-a-player/upload-and-evaluate",
    "debug-hosted-episodes": f"{DOCS_URL}/coworld/build-a-player/debug-hosted-episodes",
    "improve-a-policy": f"{DOCS_URL}/coworld/build-a-player/improve-a-policy",
    "submit-to-a-league": f"{DOCS_URL}/coworld/build-a-player/submit-to-a-league",
    "build-certify-upload": f"{DOCS_URL}/coworld/build-a-coworld/build-certify-upload",
    "hosted-verification": f"{DOCS_URL}/coworld/build-a-coworld/hosted-verification",
    "league-lobbies": f"{DOCS_URL}/coworld/build-a-coworld/league-lobbies",
    "competition": f"{DOCS_URL}/coworld/concepts/competition",
    "forums-and-wikis": f"{DOCS_URL}/coworld/concepts/forums-and-wikis",
    "replays": f"{DOCS_URL}/coworld/advanced/replays",
    "troubleshooting": f"{DOCS_URL}/coworld/advanced/troubleshooting",
}


def docs_epilog(*pages: str) -> str:
    """Help epilog naming the documentation page(s) for a command's workflow."""
    urls = " and ".join(DOCS_PAGES[page] for page in pages)
    return f"Docs: {urls}"
