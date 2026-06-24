from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict


class BedrockEnablement(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool
    model: str | None = None


# TODO(manifest): replace this signal source with manifest.runnable.bedrock once policies carry manifests.
def resolve_player_bedrock(policy_secret_env: Mapping[str, str]) -> BedrockEnablement:
    return BedrockEnablement(
        enabled=policy_secret_env.get("USE_BEDROCK") == "true",
        model=policy_secret_env.get("BEDROCK_MODEL"),
    )
