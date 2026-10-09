import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from coworld.api_client import CoworldApiClient
from coworld.manifest_uri import materialized_replay_path


@contextmanager
def materialized_episode_replay(
    *, client: CoworldApiClient, episode_request_id: str, replay_uri: str
) -> Iterator[Path]:
    if urlsplit(replay_uri).scheme != "conductor":
        with materialized_replay_path(replay_uri) as path:
            yield path
        return

    with tempfile.TemporaryDirectory(prefix="coworld-replay-") as directory:
        path = Path(directory) / "replay.replay"
        path.write_bytes(client.get_episode_request_artifact_bytes(episode_request_id, "replay"))
        yield path
