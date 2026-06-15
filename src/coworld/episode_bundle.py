"""Assemble an episode bundle zip from a local episode's artifacts.

The bundle is the canonical input handed to post-episode runnables via
``COGAME_EPISODE_BUNDLE_URI`` (see ``docs/artifacts/EPISODE_BUNDLE.md``). The
hosted bundling layer builds it from artifact stores; this assembler builds the
same shape from an :class:`~coworld.runner.runner.EpisodeArtifacts` workspace so
``coworld certify`` (and local reporter runs) can feed real reporters without a
backend.
"""

from __future__ import annotations

import io
import json
import zipfile

from coworld.runner.runner import EpisodeArtifacts


def assemble_episode_bundle(artifacts: EpisodeArtifacts, *, ereq_id: str, status: str = "success") -> bytes:
    """Build an episode bundle zip from ``artifacts``.

    Includes the ``results``, ``replay``, ``game_logs``, and (when present)
    ``player_logs`` tokens, plus the inner ``manifest.json`` that maps each
    token to its in-zip path. Stores ``replay.json`` uncompressed inside the
    already-compressed zip, matching the bundle contract.
    """
    entries: list[tuple[str, bytes]] = []
    files: dict[str, object] = {}
    include: list[str] = []

    entries.append(("results.json", artifacts.results_path.read_bytes()))
    files["results"] = "results.json"
    include.append("results")

    entries.append(("replay.json", artifacts.replay_path.read_bytes()))
    files["replay"] = "replay.json"
    include.append("replay")

    entries.append(("logs/game.stdout.log", artifacts.game_stdout_path.read_bytes()))
    entries.append(("logs/game.stderr.log", artifacts.game_stderr_path.read_bytes()))
    files["game_logs"] = {"stdout": "logs/game.stdout.log", "stderr": "logs/game.stderr.log"}
    include.append("game_logs")

    player_logs: dict[str, str] = {}
    for log_path in sorted(artifacts.logs_dir.glob("policy_agent_*.log")):
        slot = log_path.stem.removeprefix("policy_agent_")
        entry_name = f"logs/{log_path.name}"
        entries.append((entry_name, log_path.read_bytes()))
        player_logs[slot] = entry_name
    if player_logs:
        files["player_logs"] = player_logs
        include.append("player_logs")

    manifest = json.dumps(
        {"ereq_id": ereq_id, "status": status, "include": include, "files": files},
        indent=2,
    ).encode("utf-8")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", manifest)
        for name, payload in entries:
            archive.writestr(name, payload)
    return buffer.getvalue()
