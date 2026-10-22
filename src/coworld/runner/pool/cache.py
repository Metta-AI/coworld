"""Private, sequential-worker cache. Episode files are copies, never shared cache inodes."""

import hashlib
import os
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile

from coworld.runner.io import RunnerEpisodeError
from coworld.types import CoworldPlayerFileSpec


class PlayerFileCache:
    def __init__(self, directory: Path, *, max_bytes: int, max_entries: int = 1024) -> None:
        assert max_bytes > 0 and max_entries > 0
        self.directory = directory
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
        self.hits = 0
        self.misses = 0
        self.download_bytes = 0

    def read(self, player: CoworldPlayerFileSpec, download: Callable[[], bytes]) -> bytes:
        path = self.directory / player.content_hash
        hit = path.exists()
        data = path.read_bytes() if hit else download()
        if len(data) != player.size_bytes or hashlib.sha256(data).hexdigest() != player.content_hash:
            if hit:
                path.unlink()
            raise RunnerEpisodeError(
                "Player file does not match its declared size and SHA-256 digest",
                error_type="player_file_mismatch",
            )
        if hit:
            self.hits += 1
            path.touch()
            return data

        self.misses += 1
        self.download_bytes += len(data)
        # Oversized inputs still execute, without displacing the entire cache.
        if len(data) > self.max_bytes:
            return data
        entries = sorted(self.directory.iterdir(), key=lambda entry: (entry.stat().st_mtime_ns, entry.name))
        total = sum(entry.stat().st_size for entry in entries)
        while entries and (total + len(data) > self.max_bytes or len(entries) >= self.max_entries):
            oldest = entries.pop(0)
            total -= oldest.stat().st_size
            oldest.unlink()
        # Only verified bytes become addressable. A failed write never leaves a partial hit.
        with NamedTemporaryFile(dir=self.directory, delete=False) as temporary:
            temporary_path = Path(temporary.name)
            try:
                temporary.write(data)
                temporary.flush()
                os.replace(temporary_path, path)
            finally:
                temporary_path.unlink(missing_ok=True)
        return data
