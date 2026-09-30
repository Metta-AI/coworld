from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict


class LlmEnablement(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool
    model: str | None = None


def resolve_player_llm(policy_secret_env: Mapping[str, str]) -> LlmEnablement:
    return LlmEnablement(
        enabled=policy_secret_env.get("COWORLD_LLM_ENABLED") == "true",
        model=policy_secret_env.get("COWORLD_LLM_MODEL"),
    )
