"""Runtime identities for private, game-owned decision trajectories."""

import re

from coworld.types import CoworldManifest


def trajectory_identity_env(manifest: CoworldManifest, episode_id: str) -> dict[str, str]:
    """Identify the executed manifest; never infer a source commit from a campaign plan."""
    runnable = manifest.game.runnable
    source = runnable.source_url
    revision = re.search(r"/(?:tree|commit)/([0-9a-f]{40})(?:/|$)", source) if source else None
    return {
        "COWORLD_EPISODE_ID": episode_id,
        "COWORLD_GAME_VERSION": manifest.game.version,
        "COWORLD_SOURCE_REVISION": revision.group(1) if revision else source or runnable.image,
    }
