import json
from pathlib import Path

import pytest

from coworld.manifest.registry import validate_upload_manifest
from coworld.training_provenance import training_environment


@pytest.mark.parametrize("source_kind", ["tree", "blob", "commit"])
def test_training_identity_uses_immutable_source_and_launched_image(source_kind: str) -> None:
    manifest = validate_upload_manifest(
        json.loads((Path(__file__).parent / "manifest_versions/v1/minimal_manifest.json").read_text())
    ).runtime_manifest
    source_revision = "a" * 40
    manifest.game.runnable.source_url = f"https://github.com/Metta-AI/game/{source_kind}/{source_revision}/src"
    image_digest = "b" * 64

    environment = training_environment(
        manifest, manifest.game.runnable, image=f"registry.example/game@sha256:{image_digest}"
    )

    assert environment == {
        "COWORLD_GAME_NAME": manifest.game.name,
        "COWORLD_GAME_VERSION": manifest.game.version,
        "COWORLD_SOURCE_REVISION": source_revision,
        "COWORLD_GAME_IMAGE_DIGEST": f"sha256:{image_digest}",
    }


def test_branch_and_local_image_tag_do_not_claim_immutable_identity() -> None:
    manifest = validate_upload_manifest(
        json.loads((Path(__file__).parent / "manifest_versions/v1/minimal_manifest.json").read_text())
    ).runtime_manifest
    manifest.game.runnable.source_url = "https://github.com/Metta-AI/game/tree/main/src"

    assert training_environment(manifest, manifest.game.runnable, image="game:latest") == {
        "COWORLD_GAME_NAME": manifest.game.name,
        "COWORLD_GAME_VERSION": manifest.game.version,
    }
