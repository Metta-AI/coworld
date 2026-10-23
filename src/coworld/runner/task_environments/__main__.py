"""Run the experimental control service against an explicit local kind cluster."""

import argparse
from datetime import datetime
from pathlib import Path

import uvicorn
from kubernetes import config
from pydantic import BaseModel, ConfigDict, Field

from coworld.runner.task_environments.kubernetes import TaskPods
from coworld.runner.task_environments.service import TaskControl
from coworld.types import CoworldTaskEnvironment


class LocalControlConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kubeconfig: Path
    context: str = Field(pattern=r"^kind-")
    guard_image: str
    namespace: str
    owner_name: str
    owner_uid: str
    expires_at: datetime
    definitions: dict[str, CoworldTaskEnvironment]
    evidence_dir: Path
    token_file: Path
    port: int = Field(ge=1024, le=65535)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    settings = LocalControlConfig.model_validate_json(args.config.read_bytes())
    with config.new_client_from_config(config_file=str(settings.kubeconfig), context=settings.context) as api:
        pods = TaskPods(
            api,
            namespace=settings.namespace,
            owner_name=settings.owner_name,
            owner_uid=settings.owner_uid,
            expires_at=settings.expires_at,
            definitions=settings.definitions,
            evidence_dir=settings.evidence_dir,
            guard_image=settings.guard_image,
        )
        control = TaskControl(pods, settings.token_file.read_text().strip())
        uvicorn.run(
            control,
            host="127.0.0.1",
            port=settings.port,
            limit_concurrency=4,
            timeout_keep_alive=2,
            timeout_graceful_shutdown=20,
        )


if __name__ == "__main__":
    main()
