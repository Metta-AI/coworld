"""Published game identity shared by local and hosted episode launches."""

import re
from urllib.parse import urlsplit

from coworld.types import CoworldManifest, CoworldRunnableSpec


def training_environment(manifest: CoworldManifest, runnable: CoworldRunnableSpec, *, image: str) -> dict[str, str]:
    """Stamp declared version and immutable source/image pins when available.

    A branch source URL or local image tag does not establish immutable identity.
    Leave those pins absent so the export qualification reports missing evidence.
    """
    environment = {
        "COWORLD_GAME_NAME": manifest.game.name,
        "COWORLD_GAME_VERSION": manifest.game.version,
    }
    if runnable.source_url:
        revision = re.search(r"/(?:tree|blob|commit)/([a-f0-9]{40})(?:/|$)", urlsplit(runnable.source_url).path)
        if revision:
            environment["COWORLD_SOURCE_REVISION"] = revision[1]
    image_digest = re.search(r"@(sha256:[a-f0-9]{64})$", image)
    if image_digest:
        environment["COWORLD_GAME_IMAGE_DIGEST"] = image_digest[1]
    return environment
