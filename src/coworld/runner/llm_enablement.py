from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict


class LlmEnablement(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool
    model: str | None = None


def resolve_player_llm(env: Mapping[str, str]) -> LlmEnablement:
    return LlmEnablement(
        enabled=env.get("COWORLD_LLM_ENABLED") == "true",
        model=env.get("COWORLD_LLM_MODEL"),
    )
