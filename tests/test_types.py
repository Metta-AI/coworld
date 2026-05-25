from __future__ import annotations

import pytest
from pydantic import ValidationError

from coworld.types import (
    CoworldEpisodeJobSpec,
    CoworldManifest,
    CoworldRunnableSpec,
    CoworldVariant,
    coworld_episode_request_schema,
    coworld_manifest_schema,
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


def test_runnable_and_manifest_role_fields_are_flat() -> None:
    spec = CoworldRunnableSpec(type="game", image="game", source_url="https://example.com")

    assert spec.source_url == "https://example.com"
    assert set(CoworldRunnableSpec.model_fields) == {"type", "image", "run", "env", "source_url"}


def test_manifest_rejects_wrong_game_runnable_type() -> None:
    schema = coworld_manifest_schema()["$defs"]["CoworldGameManifest"]["properties"]["runnable"]["properties"]["type"]
    assert schema == {"const": "game"}
    with pytest.raises(ValidationError, match="game.runnable.type"):
        _manifest(game_type="player")


def test_manifest_rejects_wrong_role_section_type() -> None:
    with pytest.raises(ValidationError, match="player.0.type"):
        _manifest(player_type="reporter")


def test_episode_job_players_are_flat_runnable_payloads() -> None:
    manifest = _manifest()
    job = CoworldEpisodeJobSpec(manifest=manifest, game_config={}, players=[manifest.player[0]])

    assert job.model_dump(exclude_defaults=True)["players"] == [
        {"type": "player", "image": "player", "source_url": "https://example.com/player"}
    ]


def test_episode_job_rejects_non_player_runnable() -> None:
    schema = coworld_episode_request_schema()["properties"]["players"]["items"]["properties"]["type"]
    assert schema == {"const": "player"}
    with pytest.raises(ValidationError, match="players.0.type"):
        CoworldEpisodeJobSpec(
            manifest=_manifest(),
            game_config={},
            players=[CoworldRunnableSpec(type="reporter", image="reporter")],
        )


def _manifest(game_type: str = "game", player_type: str = "player") -> CoworldManifest:
    return CoworldManifest.model_validate(
        {
            "game": {
                "name": "Example",
                "version": "1.0.0",
                "description": "Example Coworld.",
                "owner": "coworld@softmax.com",
                "runnable": {"type": game_type, "image": "game"},
                "config_schema": {},
                "results_schema": {},
                "protocols": {"player": {"type": "text", "value": "p"}, "global": {"type": "text", "value": "g"}},
            },
            "player": [
                {
                    "id": "player",
                    "name": "Player",
                    "description": "Player.",
                    "type": player_type,
                    "image": "player",
                    "source_url": "https://example.com/player",
                }
            ],
            "reporter": [
                {
                    "id": "reporter",
                    "name": "Reporter",
                    "description": "Reporter.",
                    "type": "reporter",
                    "image": "reporter",
                    "source_url": "https://example.com/reporter",
                }
            ],
            "variants": [{"id": "default", "name": "Default", "description": "Default.", "game_config": {}}],
            "certification": {"game_config": {}, "players": [{"player_id": "player"}]},
        }
    )
