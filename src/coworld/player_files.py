from __future__ import annotations

import io
import zipfile
from pathlib import Path

PLAYER_FILE_MAX_BYTES = 100 * 1024 * 1024


def resolve_player_file(source: Path, *, package_root: Path | None = None) -> Path:
    """Resolve a manifest ``player[].file`` reference to an existing file or directory.

    Rejects symlinks (the path itself or, for a directory, anything inside it) and paths
    that escape ``package_root``; the same rules apply whether the caller packs, copies
    or hashes the player.
    """
    candidate = source if package_root is None else package_root.resolve() / source
    if candidate.is_symlink():
        raise ValueError(f"Player file cannot be a symlink: {source}")
    resolved = candidate.resolve()
    if package_root is not None and not resolved.is_relative_to(package_root.resolve()):
        raise ValueError(f"Player file must stay within the Coworld package: {source}")
    if resolved.is_dir():
        if any(path.is_symlink() for path in resolved.rglob("*")):
            raise ValueError(f"Player file directory cannot contain symlinks: {source}")
    elif not resolved.is_file():
        raise ValueError(f"Player file path does not exist: {source}")
    return resolved


def player_file_bytes(source: Path, *, package_root: Path | None = None) -> bytes:
    resolved = resolve_player_file(source, package_root=package_root)
    size_error = f"Player file exceeds the {PLAYER_FILE_MAX_BYTES // 1024 // 1024} MB size limit: {source}"
    if resolved.is_file():
        if resolved.stat().st_size > PLAYER_FILE_MAX_BYTES:
            raise ValueError(size_error)
        contents = resolved.read_bytes()
    else:
        entries = list(resolved.rglob("*"))
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
            for path in sorted(path for path in entries if path.is_file()):
                info = zipfile.ZipInfo(path.relative_to(resolved).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                output.writestr(info, path.read_bytes())
        contents = archive.getvalue()
    if len(contents) > PLAYER_FILE_MAX_BYTES:
        raise ValueError(size_error)
    return contents
