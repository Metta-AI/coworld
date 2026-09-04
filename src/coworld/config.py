from typing import Any

import httpx

DEFAULT_SUBMIT_SERVER = "https://softmax.com/api"

# Continuation header on bare-list endpoints (/v2/coworlds, /v2/container_images,
# /v2/reporters): when present, its value is an opaque cursor token that resumes
# the listing after the last returned row. Absent header = no further page.
NEXT_CURSOR_HEADER = "X-Next-Cursor"


def catalog_page_payload(response: httpx.Response) -> tuple[list[Any], str | None]:
    """The entries and next-page cursor of one bare-list catalog response."""
    return response.json(), response.headers.get(NEXT_CURSOR_HEADER)


DEFAULT_OPTIMIZER_REPO = "https://github.com/Metta-AI/optimizers"
DEFAULT_OPTIMIZER_REF = "main"
DEFAULT_OPTIMIZER_PORT = 3000
