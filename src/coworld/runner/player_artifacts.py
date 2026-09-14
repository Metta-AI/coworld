from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

DIAGNOSTIC_TARGETS_PATH = "/var/run/coworld-diagnostics/targets.json"


class PersistentDiagnosticSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_id: UUID = Field(description="Persistent controller identity.")
    session_id: UUID = Field(description="Immutable launch identity for this controller session.")
    player_id: str = Field(description="Player identity running this controller session.")
    policy_version_id: UUID = Field(description="Policy version used for this controller session.")
    coworld_id: str = Field(description="Coworld identity used for this controller session.")
    generation: int = Field(description="Persistent runtime generation at launch.")
    created_at: datetime = Field(description="UTC timestamp when this controller session was created.")

    @property
    def prefix(self) -> str:
        return f"jobs/{self.runtime_id}/sessions/{self.session_id}"


class PersistentDiagnosticTargets(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session: PersistentDiagnosticSession
    expires_at: datetime
    targets: dict[str, str]
