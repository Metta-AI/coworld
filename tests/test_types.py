from __future__ import annotations

import pytest
from pydantic import ValidationError

from coworld.types import (
    CoworldDeclaredRunnableSpec,
    CoworldGameRunnableSpec,
    CoworldPlayerSpec,
    CoworldVariant,
)


def test_variant_does_not_have_parent_id_field() -> None:
    assert "parent_id" not in CoworldVariant.model_fields


def test_variant_rejects_parent_id() -> None:
    with pytest.raises(ValidationError):
        CoworldVariant.model_validate(
            {
                "id": "v1",
                "name": "Variant 1",
                "game_config": {},
                "description": "Variant 1",
                "parent_id": "v0",
            }
        )


def test_game_runnable_spec_accepts_source_url() -> None:
    spec = CoworldGameRunnableSpec(
        image="example/game:latest",
        source_url="https://github.com/Metta-AI/example",
    )

    assert spec.source_url == "https://github.com/Metta-AI/example"


def test_game_runnable_spec_source_url_defaults_to_none() -> None:
    spec = CoworldGameRunnableSpec(image="example/game:latest")

    assert spec.source_url is None


def test_player_spec_does_not_carry_source_url() -> None:
    assert "source_url" not in CoworldPlayerSpec.model_fields
    assert "source_url" in CoworldGameRunnableSpec.model_fields
    assert "source_url" in CoworldDeclaredRunnableSpec.model_fields
