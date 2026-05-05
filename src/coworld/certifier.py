from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import unquote, urlparse

from coworld.episode_runner import (
    EpisodeArtifacts,
    EpisodeRunSpec,
    PlayerLaunchSpec,
    assert_docker_image_reachable,
    run_cogame_episode,
)
from coworld.schema_validation import (
    JsonObject,
    JsonSchema,
    load_json_object,
    validate_cogame_manifest,
    validate_coworld_manifest,
    validate_episode_request,
    validate_json_schema,
)


@dataclass(frozen=True)
class CogameProtocolDocs:
    player: str
    global_: str


@dataclass(frozen=True)
class CoworldPackage:
    manifest_path: Path
    manifest: JsonObject
    cogame_manifest_path: Path
    cogame_manifest: JsonObject
    certification: JsonObject
    cogame_image: str
    config_schema: JsonSchema
    results_schema: JsonSchema
    protocols: CogameProtocolDocs


@dataclass(frozen=True)
class CertificationResult:
    package: CoworldPackage
    artifacts: EpisodeArtifacts
    episode_request: JsonObject
    results: JsonObject


def resolve_manifest_uri(base_dir: Path, manifest_uri: str) -> Path:
    parsed = urlparse(manifest_uri)
    if parsed.scheme == "file":
        return Path(unquote(parsed.path)).resolve()
    if parsed.scheme:
        raise ValueError(f"Only local manifest URIs are supported for certification: {manifest_uri}")
    return (base_dir / manifest_uri).resolve()


def load_coworld_package(manifest_path: Path) -> CoworldPackage:
    manifest_path = manifest_path.resolve()
    manifest = load_json_object(manifest_path)
    validate_coworld_manifest(manifest)

    game = cast(JsonObject, manifest["game"])
    cogame_manifest_path = resolve_manifest_uri(manifest_path.parent, cast(str, game["manifest_uri"]))
    cogame_manifest = load_json_object(cogame_manifest_path)
    validate_cogame_manifest(cogame_manifest)

    certification = cast(JsonObject, manifest["certification"])
    protocols = cast(JsonObject, cogame_manifest["protocols"])

    package = CoworldPackage(
        manifest_path=manifest_path,
        manifest=manifest,
        cogame_manifest_path=cogame_manifest_path,
        cogame_manifest=cogame_manifest,
        certification=certification,
        cogame_image=cast(str, cogame_manifest["image_uri"]),
        config_schema=cast(JsonSchema, cogame_manifest["config_schema"]),
        results_schema=cast(JsonSchema, cogame_manifest["results_schema"]),
        protocols=CogameProtocolDocs(player=cast(str, protocols["player"]), global_=cast(str, protocols["global"])),
    )
    validate_certification_references(package)
    validate_referenced_files(package)
    return package


def validate_certification_references(package: CoworldPackage) -> None:
    _certification_variant(package)
    _certification_player_launch_specs(package)


def validate_referenced_files(package: CoworldPackage) -> None:
    for label, path in _referenced_file_paths(package):
        if not path.is_file():
            raise FileNotFoundError(f"{label} does not exist or is not a file: {path}")


def validate_image_references(package: CoworldPackage) -> None:
    for label, image in _image_references(package):
        assert_docker_image_reachable(image, label=label)


def build_game_config(package: CoworldPackage, tokens: list[str]) -> JsonObject:
    game_config = dict(cast(JsonObject, _certification_variant(package)["game_config"]))
    game_config["tokens"] = tokens
    validate_json_schema(game_config, package.config_schema)
    return game_config


def build_episode_request(package: CoworldPackage, artifacts: EpisodeArtifacts) -> JsonObject:
    episode_request: JsonObject = {
        "game_config": dict(cast(JsonObject, _certification_variant(package)["game_config"])),
        "players": [
            _episode_request_player(player_spec) for player_spec in _certification_player_launch_specs(package)
        ],
    }
    episode_request["results_uri"] = artifacts.results_path.as_uri()
    episode_request["replay_uri"] = artifacts.replay_path.as_uri()
    episode_request["logs_uri"] = artifacts.logs_dir.as_uri()
    validate_episode_request(episode_request)
    return episode_request


def build_player_launch_specs(episode_request: JsonObject) -> list[PlayerLaunchSpec]:
    validate_episode_request(episode_request)
    players = cast(list[object], episode_request["players"])
    return [PlayerLaunchSpec.from_episode_player(cast(JsonObject, player)) for player in players]


def build_episode_run_spec(
    package: CoworldPackage,
    episode_request: JsonObject,
    tokens: list[str],
    artifacts: EpisodeArtifacts,
    timeout_seconds: float,
) -> EpisodeRunSpec:
    return EpisodeRunSpec(
        cogame_image=package.cogame_image,
        players=build_player_launch_specs(episode_request),
        tokens=tokens,
        artifacts=artifacts,
        timeout_seconds=timeout_seconds,
    )


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
    tokens = [secrets.token_urlsafe(16) for _ in cast(list[object], package.certification["players"])]
    game_config = build_game_config(package, tokens)
    artifacts.config_path.write_text(json.dumps(game_config, indent=2))

    episode_request = build_episode_request(package, artifacts)
    run_cogame_episode(build_episode_run_spec(package, episode_request, tokens, artifacts, timeout_seconds))

    results = load_results(package, artifacts)
    if not artifacts.replay_path.exists():
        raise FileNotFoundError(f"Replay file was not produced: {artifacts.replay_path}")

    return CertificationResult(
        package=package,
        artifacts=artifacts,
        episode_request=episode_request,
        results=results,
    )


def _referenced_file_paths(package: CoworldPackage) -> list[tuple[str, Path]]:
    cogame_dir = package.cogame_manifest_path.parent
    return [
        ("Cogame protocols.player", resolve_manifest_uri(cogame_dir, package.protocols.player)),
        ("Cogame protocols.global", resolve_manifest_uri(cogame_dir, package.protocols.global_)),
    ]


def _image_references(package: CoworldPackage) -> list[tuple[str, str]]:
    references = [("Cogame image_uri", package.cogame_image)]
    references.extend(
        (f"Certification players[{slot}].image", player.image)
        for slot, player in enumerate(_certification_player_launch_specs(package))
    )
    for section in ("player", "grader", "reporter", "commissioner", "diagnoser", "optimizer"):
        if section in package.manifest:
            references.extend(
                (f"Coworld {section}[{index}].image_uri", cast(str, image["image_uri"]))
                for index, image in enumerate(cast(list[JsonObject], package.manifest[section]))
            )
    return list(dict.fromkeys(references))


def _certification_player_launch_specs(package: CoworldPackage) -> list[PlayerLaunchSpec]:
    declared_players = _manifest_items_by_id(package, "player")
    players = cast(list[object], package.certification["players"])
    specs: list[PlayerLaunchSpec] = []
    for slot, raw_player in enumerate(players):
        certification_player = cast(JsonObject, raw_player)
        player_id = cast(str, certification_player["player_id"])
        if player_id not in declared_players:
            raise ValueError(f"unknown certification player_id for slot {slot}: {player_id!r}")
        declared_player = declared_players[player_id]
        episode_player: JsonObject = {"image": cast(str, declared_player["image_uri"])}
        if "initial_params" in certification_player:
            episode_player["initial_params"] = certification_player["initial_params"]
        specs.append(PlayerLaunchSpec.from_episode_player(episode_player))
    return specs


def _certification_variant(package: CoworldPackage) -> JsonObject:
    variants = _manifest_items_by_id(package, "variants")
    variant_id = cast(str, package.certification["variant_id"])
    if variant_id not in variants:
        raise ValueError(f"unknown certification variant_id: {variant_id!r}")
    return variants[variant_id]


def _manifest_items_by_id(package: CoworldPackage, section: str) -> dict[str, JsonObject]:
    items = cast(list[JsonObject], package.manifest[section])
    items_by_id: dict[str, JsonObject] = {}
    for item in items:
        item_id = cast(str, item["id"])
        if item_id in items_by_id:
            raise ValueError(f"duplicate {section} id: {item_id!r}")
        items_by_id[item_id] = item
    return items_by_id


def _episode_request_player(player_spec: PlayerLaunchSpec) -> JsonObject:
    player: JsonObject = {"image": player_spec.image}
    if player_spec.initial_params:
        player["initial_params"] = dict(player_spec.initial_params)
    return player
