from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from coworld.manifest_validation import game_config_with_tokens, validate_coworld_manifest_game_configs
from coworld.runner.runner import (
    EpisodeArtifacts,
    PlayerLaunchSpec,
    RunnableLaunchSpec,
    assert_docker_image_reachable,
    run_coworld_episode,
)
from coworld.schema_validation import (
    JsonObject,
    JsonSchema,
    load_json_object,
    validate_json_schema,
)
from coworld.types import CoworldDoc, CoworldEpisodeJobSpec, CoworldManifest, CoworldPlayerSpec, coworld_manifest_schema


@dataclass(frozen=True)
class CogameProtocolDocs:
    player: CoworldDoc
    global_: CoworldDoc


@dataclass(frozen=True)
class CoworldPackage:
    manifest_path: Path
    manifest: CoworldManifest
    cogame: RunnableLaunchSpec
    config_schema: JsonSchema
    results_schema: JsonSchema
    protocols: CogameProtocolDocs


@dataclass(frozen=True)
class CertificationResult:
    package: CoworldPackage
    artifacts: EpisodeArtifacts
    episode_request: JsonObject
    results: JsonObject


def load_coworld_package(manifest_path: Path) -> CoworldPackage:
    manifest_path = manifest_path.resolve()
    manifest = load_json_object(manifest_path)
    validate_json_schema(manifest, coworld_manifest_schema())
    typed_manifest = CoworldManifest.model_validate(manifest)
    validate_coworld_manifest_game_configs(typed_manifest)

    package = CoworldPackage(
        manifest_path=manifest_path,
        manifest=typed_manifest,
        cogame=RunnableLaunchSpec.from_model(typed_manifest.game.runnable),
        config_schema=typed_manifest.game.config_schema,
        results_schema=typed_manifest.game.results_schema,
        protocols=CogameProtocolDocs(
            player=typed_manifest.game.protocols.player,
            global_=typed_manifest.game.protocols.global_,
        ),
    )
    validate_certification_references(package)
    return package


def validate_certification_references(package: CoworldPackage) -> None:
    _certification_player_specs(package)


def validate_image_references(package: CoworldPackage) -> None:
    for label, image in _image_references(package):
        assert_docker_image_reachable(image, label=label)


def build_game_config(package: CoworldPackage, tokens: list[str]) -> JsonObject:
    game_config = game_config_with_tokens(package.manifest.certification.game_config, tokens)
    validate_json_schema(game_config, package.config_schema)
    return game_config


def build_episode_request(package: CoworldPackage, artifacts: EpisodeArtifacts) -> JsonObject:
    episode_request: JsonObject = {
        key: cast(object, value)
        for key, value in build_manifest_episode_job_spec(package)
        .model_dump(by_alias=True, exclude_defaults=True)
        .items()
    }
    return episode_request


def build_manifest_episode_job_spec(
    package: CoworldPackage,
    *,
    variant_id: str | None = None,
    player_images: list[str] | None = None,
    player_run: list[str] | None = None,
) -> CoworldEpisodeJobSpec:
    players = _certification_player_specs(package)
    if not player_images:
        if player_run:
            raise ValueError("player_run requires at least one player image")
    else:
        slot_count = len(players)
        if len(player_images) == 1:
            slot_images = player_images * slot_count
        elif len(player_images) == slot_count:
            slot_images = player_images
        else:
            expected_counts = "1" if slot_count == 1 else f"1 or {slot_count}"
            raise ValueError(f"expected {expected_counts} player images for {slot_count} player slots")

        players = [
            players[slot].model_copy(update={"image": image, "run": list(player_run or [])})
            for slot, image in enumerate(slot_images)
        ]

    if variant_id is None:
        game_config = dict(package.manifest.certification.game_config)
    else:
        variants = {variant.id: variant for variant in package.manifest.variants}
        if variant_id not in variants:
            raise ValueError(f"unknown Coworld variant_id: {variant_id!r}")
        game_config = dict(variants[variant_id].game_config)

    return CoworldEpisodeJobSpec(
        manifest=package.manifest,
        game_config=game_config,
        players=players,
    )


def build_player_launch_specs(episode_request: JsonObject) -> list[PlayerLaunchSpec]:
    job_spec = build_coworld_episode_job_spec(episode_request)
    return [PlayerLaunchSpec.from_model(player) for player in job_spec.players]


def build_coworld_episode_job_spec(episode_request: JsonObject) -> CoworldEpisodeJobSpec:
    return CoworldEpisodeJobSpec.model_validate(episode_request)


def load_results(package: CoworldPackage, artifacts: EpisodeArtifacts) -> JsonObject:
    results = load_json_object(artifacts.results_path)
    validate_json_schema(results, package.results_schema)
    return results


def certify_coworld(
    manifest_path: Path,
    *,
    workspace: Path | None = None,
    timeout_seconds: float = 60.0,
) -> CertificationResult:
    package = load_coworld_package(manifest_path)
    validate_image_references(package)
    artifacts = EpisodeArtifacts.create(workspace)
    episode_request = build_episode_request(package, artifacts)
    run_coworld_episode(
        build_coworld_episode_job_spec(episode_request),
        artifacts,
        timeout_seconds=timeout_seconds,
        verify_replay=True,
    )

    results = load_results(package, artifacts)
    if not artifacts.replay_path.exists():
        raise FileNotFoundError(f"Replay file was not produced: {artifacts.replay_path}")

    return CertificationResult(
        package=package,
        artifacts=artifacts,
        episode_request=episode_request,
        results=results,
    )


def _image_references(package: CoworldPackage) -> list[tuple[str, str]]:
    references = [("Cogame runnable.image", package.cogame.image)]
    references.extend(
        (f"Certification players[{slot}].image", player.image)
        for slot, player in enumerate(_certification_player_specs(package))
    )
    for section in ("player", "grader", "reporter", "commissioner", "diagnoser", "optimizer"):
        references.extend(
            (f"Coworld {section}[{index}].image", runnable.image)
            for index, runnable in enumerate(getattr(package.manifest, section))
        )
    return list(dict.fromkeys(references))


def _certification_player_specs(package: CoworldPackage) -> list[CoworldPlayerSpec]:
    declared_players = _manifest_items_by_id(package, "player")
    players = package.manifest.certification.players
    specs: list[CoworldPlayerSpec] = []
    for slot, certification_player in enumerate(players):
        player_id = certification_player.player_id
        if player_id not in declared_players:
            raise ValueError(f"unknown certification player_id for slot {slot}: {player_id!r}")
        declared_player = declared_players[player_id]
        episode_player = CoworldPlayerSpec.model_validate(declared_player.model_dump())
        specs.append(episode_player)
    return specs


def _manifest_items_by_id(package: CoworldPackage, section: str):
    items = getattr(package.manifest, section)
    items_by_id = {}
    for item in items:
        if item.id in items_by_id:
            raise ValueError(f"duplicate {section} id: {item.id!r}")
        items_by_id[item.id] = item
    return items_by_id
