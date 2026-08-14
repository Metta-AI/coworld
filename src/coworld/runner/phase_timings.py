from __future__ import annotations

from pydantic import BaseModel

PHASE_GAME_BOOT = "game_boot"
PHASE_PLAYER_LAUNCH = "player_launch"
PHASE_FIRST_STEP = "first_step"
PHASE_GAMEPLAY = "gameplay"
PHASE_ARTIFACT_UPLOAD = "artifact_upload"


class EpisodePhaseTimings(BaseModel):
    """Wall-clock seconds the k8s worker spends in each in-pod episode phase.

    game_boot: worker start until the game container serves /healthz.
    player_launch: game ready until every player pod create call is issued.
    first_step: player pods launched until the game emits its first /global message
        (covers player pod scheduling, image pull, and the connect handshake).
    gameplay: first /global message until episode results are written.
    artifact_upload: results written until episode outputs are uploaded to S3.
    Incomplete phases remain unset and are omitted from incremental uploads.
    """

    game_boot_s: float | None = None
    player_launch_s: float | None = None
    first_step_s: float | None = None
    gameplay_s: float | None = None
    artifact_upload_s: float | None = None

    def phase_seconds(self) -> dict[str, float]:
        phases = {
            PHASE_GAME_BOOT: self.game_boot_s,
            PHASE_PLAYER_LAUNCH: self.player_launch_s,
            PHASE_FIRST_STEP: self.first_step_s,
            PHASE_GAMEPLAY: self.gameplay_s,
            PHASE_ARTIFACT_UPLOAD: self.artifact_upload_s,
        }
        return {phase: seconds for phase, seconds in phases.items() if seconds is not None}
