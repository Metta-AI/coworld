from __future__ import annotations

# Timestamp before module imports. Python has already imported the coworld package;
# that earlier cost is covered by process birth, not this imports interval.
# ruff: noqa: E402
import time

_IMPORT_START_NS = time.monotonic_ns()
_IMPORT_WALL_NS = time.time_ns()
_IMPORT_ANCHOR_END_NS = time.monotonic_ns()

import json
import logging
import os

from pydantic import TypeAdapter

from coworld.runner.bootstrap import COORDINATOR_SPEC_PATH, STATE_PATH, WORKDIR, process_timings
from coworld.runner.bootstrap import read_job_spec as _read_job_spec
from coworld.runner.bootstrap import write_error_info as _write_error_info
from coworld.runner.io import RunnerEpisodeError, exception_summary, read_data, upload_data
from coworld.runner.phase_timings import PlayerFileStageTiming, TimingClock
from coworld.runner.runner import EpisodeArtifacts, coworld_game_config, episode_player_tokens, stage_player_files
from coworld.types import CoworldPlayerFileSpec

_IMPORT_DONE_NS = time.monotonic_ns()
logger = logging.getLogger(__name__)


def init_config_from_env() -> None:
    try:
        timings = process_timings(
            import_start_ns=_IMPORT_START_NS,
            import_wall_ns=_IMPORT_WALL_NS,
            import_anchor_end_ns=_IMPORT_ANCHOR_END_NS,
            import_done_ns=_IMPORT_DONE_NS,
        )
        job, raw_spec = _read_job_spec(timings)
        spec_write_start = time.monotonic_ns()
        # The full immutable spec stays on a volume mounted only by trusted
        # init/worker containers; game-readable /coworld receives only game data.
        # A missing mount must fail instead of writing into the container layer.
        COORDINATOR_SPEC_PATH.write_bytes(raw_spec)
        # Reuse the existing operation vocabulary for rolling backend deployments.
        timings.record("setup", spec_write_start)
        if job.manifest.game.player_runtime == "game-hosted":
            stage_start = time.monotonic_ns()
            player_files = [player for player in job.players if isinstance(player, CoworldPlayerFileSpec)]
            raw_player_file_urls = os.environ.get("PLAYER_FILE_URLS")
            if raw_player_file_urls is None:
                raise RunnerEpisodeError(
                    "PLAYER_FILE_URLS is required for a game-hosted episode",
                    error_type="config_error",
                )
            player_file_urls = TypeAdapter(dict[int, str]).validate_json(raw_player_file_urls)
            if set(player_file_urls) != set(range(len(player_files))):
                raise RunnerEpisodeError(
                    "PLAYER_FILE_URLS must contain exactly one URL for every player-file slot",
                    error_type="config_error",
                )

            def read_player_file(slot: int) -> bytes:
                try:
                    return read_data(player_file_urls[slot])
                except Exception as exc:
                    raise RunnerEpisodeError(
                        f"Player file for slot {slot} could not be downloaded: {exception_summary(exc)}",
                        error_type="player_file_unavailable",
                    ) from None

            artifacts = EpisodeArtifacts.create(WORKDIR, prefix="coworld-job-")
            bytes_total = stage_player_files(player_files, read_player_file, artifacts)
            (WORKDIR / "player_file_stage.json").write_text(
                PlayerFileStageTiming(
                    stage_s=timings.record("player_files", stage_start),
                    count=len(player_files),
                    bytes_total=bytes_total,
                ).model_dump_json(),
                encoding="utf-8",
            )
        config_start = time.monotonic_ns()
        tokens = episode_player_tokens(job)
        upload_data(
            os.environ["COGAME_CONFIG_URI"],
            json.dumps(coworld_game_config(job, tokens), indent=2),
            content_type="application/json",
        )
        STATE_PATH.write_text(json.dumps({"tokens": tokens}), encoding="utf-8")
        timings.record("config_write", config_start)
        timings.record("bootstrap", _IMPORT_START_NS)
        timings.final_clock = TimingClock.capture()
        (WORKDIR / "init_timings.json").write_text(timings.model_dump_json(exclude_none=True), encoding="utf-8")
    except Exception as exc:
        try:
            # Initialization runs no game or policy code; generic failures are infrastructure-only.
            _write_error_info(exc, default_error_type="config_error")
        except Exception as cleanup_exc:
            logger.warning("Failed to upload error info after episode failure: %s", exception_summary(cleanup_exc))
        raise


if __name__ == "__main__":
    init_config_from_env()
