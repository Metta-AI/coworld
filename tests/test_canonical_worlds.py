from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from coworld.certifier import load_coworld_package
from coworld.manifest_validation import (
    game_config_with_player_names,
    game_config_with_tokens,
    infer_fixed_token_count,
    player_names_from_game_config,
)
from coworld.schema_validation import validate_json_schema
from coworld.types import CoworldEpisodeJobSpec, CoworldManifest

COWORLD_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = COWORLD_PACKAGE_ROOT.parents[1]
COWORLD_SRC = COWORLD_PACKAGE_ROOT / "src" / "coworld"
WORLDS = REPO_ROOT / "worlds"
PAINTARENA_EXAMPLE = COWORLD_SRC / "examples" / "paintarena"
VIABILITY_ROLE_SECTIONS = ("player", "optimizer", "commissioner", "reporter", "grader", "diagnoser")


def test_canonical_worlds_use_compose_builds() -> None:
    for compose_file in (*_world_compose_files(), PAINTARENA_EXAMPLE / "compose.yaml"):
        assert compose_file.is_file()
        compose_text = compose_file.read_text(encoding="utf-8")
        assert "services:" in compose_text
        assert "image:" in compose_text
        assert "platform: linux/amd64" in compose_text


def test_canonical_worlds_live_outside_coworld_package() -> None:
    assert not (COWORLD_SRC / "bundles").exists()
    assert not (COWORLD_SRC / "examples" / "cogs_vs_clips").exists()
    assert WORLDS.parent == REPO_ROOT
    assert COWORLD_PACKAGE_ROOT not in WORLDS.parents
    for compose_file in _world_compose_files():
        compose_text = compose_file.read_text(encoding="utf-8")
        assert "METTA_REPO" not in compose_text
        assert str(COWORLD_SRC) not in compose_text
        assert "src/coworld/examples/cogs_vs_clips" not in compose_text


def test_canonical_world_templates_do_not_publish_metta_repo_links() -> None:
    for template_path in _world_templates():
        template_text = template_path.read_text(encoding="utf-8")
        assert "github.com/Metta-AI/metta" not in template_text
        assert "raw.githubusercontent.com/Metta-AI/metta" not in template_text
        assert "ghcr.io/treeform" not in template_text
        assert "src/coworld/examples/cogs_vs_clips" not in template_text
        assert '"version"' not in json.loads(template_text)["game"]


def test_canonical_among_them_build_declares_role_starter_contexts() -> None:
    compose_text = (WORLDS / "among_them" / "compose.yaml").read_text(encoding="utf-8")

    assert "GAME_CONTEXT" in compose_text
    assert "PLAYER_CONTEXT" in compose_text
    assert "REPORTER_CONTEXT" in compose_text
    assert "GRADER_CONTEXT" in compose_text
    assert "DIAGNOSER_CONTEXT" in compose_text
    assert "OPTIMIZER_CONTEXT" in compose_text
    assert "coworld-among-them" in compose_text
    assert "players/ivotewell/Dockerfile" in compose_text
    assert "COMMISSIONER_CONTEXT" not in compose_text
    assert "ghcr.io/metta-ai/commissioners-default:latest" not in compose_text
    assert "reporters/reporters" in compose_text
    assert "among_them/among_them_summarizer/Dockerfile" in compose_text
    assert "graders/graders/among_them/among_them_grader" in compose_text
    assert "diagnosers/diagnosers/among_them/among_them_diagnoser" in compose_text
    assert "optimizers" in compose_text
    assert "coworld-among-them-summarizer:latest" in compose_text
    assert "coworld-among-them-grader:latest" in compose_text
    assert "ghcr.io/metta-ai/reporters-among-them-summarizer" not in compose_text
    assert "ghcr.io/metta-ai/graders-among-them" not in compose_text
    assert "Dockerfile.game" not in compose_text
    assert "Dockerfile.player" not in compose_text
    assert "ghcr.io/treeform" not in compose_text
    assert "policies/symbolic/bitworld/among-them/ivotewell" not in compose_text
    assert "WORLD_CONTEXT" not in compose_text


def test_canonical_cogs_vs_clips_build_declares_game_context() -> None:
    compose_text = (WORLDS / "cogs_vs_clips" / "compose.yaml").read_text(encoding="utf-8")

    assert "GAME_CONTEXT" in compose_text
    assert "PLAYER_CONTEXT" in compose_text
    assert "coworld-cogs-vs-clips" in compose_text
    assert "Dockerfile.game" in compose_text
    assert "Dockerfile.player" in compose_text
    assert "games/games/cogsguard" not in compose_text
    assert "additional_contexts:" not in compose_text


def test_canonical_crewrift_build_declares_game_context() -> None:
    compose_text = (WORLDS / "crewrift" / "compose.yaml").read_text(encoding="utf-8")

    assert "GAME_CONTEXT" in compose_text
    assert "PLAYER_CONTEXT" in compose_text
    assert "coworld-crewrift" in compose_text
    assert "Dockerfile" in compose_text
    assert "players/notsus/Dockerfile" in compose_text
    assert "coworld-crewrift-game:latest" in compose_text
    assert "coworld-crewrift-notsus:latest" in compose_text


def test_canonical_world_compose_files_build_manifest_images() -> None:
    for template_path in _world_templates():
        template = json.loads(template_path.read_text(encoding="utf-8"))
        compose_text = (template_path.parent / "compose.yaml").read_text(encoding="utf-8")

        image_placeholders = [template["game"]["runnable"]["image"]]
        for section in VIABILITY_ROLE_SECTIONS:
            if section in template:
                for runnable in template[section]:
                    image_placeholders.append(runnable["image"])

        for placeholder in image_placeholders:
            if placeholder.startswith("{{"):
                assert placeholder.endswith("_IMAGE}}")
                service_name = placeholder.removeprefix("{{").removesuffix("_IMAGE}}").lower()
                assert f"  {service_name}:" in compose_text
            else:
                assert placeholder in compose_text


def test_canonical_world_templates_hydrate_to_valid_manifests(tmp_path: Path) -> None:
    for template_path in (*_world_templates(), PAINTARENA_EXAMPLE / "coworld_manifest_template.json"):
        load_coworld_package(_materialized_template(tmp_path, template_path))


@pytest.mark.parametrize("world_name", ("among_them", "crewrift"))
def test_bitworld_templates_accept_runner_player_names_in_slots(tmp_path: Path, world_name: str) -> None:
    package = load_coworld_package(
        _materialized_template(tmp_path, WORLDS / world_name / "coworld_manifest_template.json")
    )
    token_count = infer_fixed_token_count(package.manifest.game.config_schema)
    player_names = [f"policy-{slot}:v{slot + 1}" for slot in range(token_count)]

    game_config = game_config_with_player_names(
        package.manifest.variants[0].game_config,
        player_names,
        package.manifest.game.config_schema,
    )

    assert [slot["name"] for slot in game_config["slots"]] == player_names
    assert player_names_from_game_config(game_config) == player_names
    validate_json_schema(
        game_config_with_tokens(game_config, [f"token-{slot}" for slot in range(token_count)]),
        package.manifest.game.config_schema,
    )
    runner_spec = CoworldEpisodeJobSpec(
        manifest=package.manifest,
        game_config=game_config,
        players=[package.manifest.player[0]] * token_count,
    )
    runner_payload = runner_spec.model_dump(mode="json", by_alias=True, exclude_none=True)

    assert "policy_names" not in runner_payload
    with pytest.raises(ValidationError, match="policy_names"):
        CoworldEpisodeJobSpec.model_validate({**runner_payload, "policy_names": player_names})


def test_canonical_world_templates_use_role_types_as_contracts() -> None:
    for template_path in (*_world_templates(), PAINTARENA_EXAMPLE / "coworld_manifest_template.json"):
        template = json.loads(template_path.read_text(encoding="utf-8"))
        assert "contracts" not in template
        assert "debugger" not in template
        assert "extractor" not in template
        for section in VIABILITY_ROLE_SECTIONS:
            for runnable in template[section]:
                assert runnable["type"] == section


def test_coworld_manifest_rejects_unknown_role_type(tmp_path: Path) -> None:
    manifest_path = _materialized_template(tmp_path, WORLDS / "paintarena" / "coworld_manifest_template.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["reporter"][0]["type"] = "archivist"

    with pytest.raises(ValidationError, match="reporter.0.type"):
        CoworldManifest.model_validate(manifest)


def test_canonical_among_them_template_points_to_source_repos(tmp_path: Path) -> None:
    package = load_coworld_package(
        _materialized_template(tmp_path, WORLDS / "among_them" / "coworld_manifest_template.json")
    )
    pages = {page.id: page.content.value for page in package.manifest.game.docs.pages}
    role_source_urls = {
        "player": package.manifest.player[0].source_url,
        "optimizer": package.manifest.optimizer[0].source_url,
        "reporter": package.manifest.reporter[0].source_url,
        "grader": package.manifest.grader[0].source_url,
        "diagnoser": package.manifest.diagnoser[0].source_url,
    }

    assert package.manifest.commissioner == []
    assert [role.id for role in package.manifest.reporter] == ["among-them-summarizer"]
    assert [role.id for role in package.manifest.grader] == ["among-them-grader"]
    assert [role.id for role in package.manifest.diagnoser] == ["among-them-diagnoser"]
    assert [role.id for role in package.manifest.optimizer] == ["coworld-optimizer"]
    assert pages["rules.md"] == "https://github.com/Metta-AI/coworld-among-them/blob/master/docs/rules.md"
    assert pages["play_amongthem.md"] == "https://softmax.com/play_amongthem.md"
    assert pages["player"] == "https://github.com/Metta-AI/coworld-among-them/blob/master/players/how_to_make_a_bot.md"
    assert pages["game-source"] == "https://github.com/Metta-AI/coworld-among-them/tree/master"
    assert pages["submit"] == (
        "https://github.com/Metta-AI/coworld-among-them/blob/master/players/how_to_submit_coworld_policy.md"
    )
    assert pages["optimizer"] == "https://github.com/Metta-AI/coworld-among-them/blob/master/players/SMART_BOT_GUIDE.md"
    assert (
        pages["optimizer-game-spec"]
        == "https://github.com/Metta-AI/coworld-among-them/blob/master/coworld_manifest.json"
    )
    assert pages["optimizer-game-tutorial"] == "https://softmax.com/play_amongthem.md"
    assert pages["optimizer-skills"] == (
        "https://github.com/Metta-AI/coworld-among-them/blob/master/docs/supporting_roles.md#optimizer-inputs"
    )
    assert pages["optimizer-policy-registry"] == (
        "https://github.com/Metta-AI/coworld-among-them/blob/master/docs/supporting_roles.md#optimizer-inputs"
    )
    assert "commissioner" not in pages
    assert pages["reporter"] == (
        "https://github.com/Metta-AI/coworld-among-them/blob/master/docs/supporting_roles.md#reporter"
    )
    assert (
        pages["grader"] == "https://github.com/Metta-AI/coworld-among-them/blob/master/docs/supporting_roles.md#grader"
    )
    assert pages["diagnoser"] == (
        "https://github.com/Metta-AI/coworld-among-them/blob/master/docs/supporting_roles.md#diagnoser"
    )
    assert role_source_urls == {
        "player": "https://github.com/Metta-AI/coworld-among-them/tree/master/players/ivotewell",
        "optimizer": "https://github.com/Metta-AI/optimizers",
        "reporter": "https://github.com/Metta-AI/reporters/tree/main/reporters/among_them/among_them_summarizer",
        "grader": "https://github.com/Metta-AI/graders/tree/main/graders/among_them/among_them_grader",
        "diagnoser": "https://github.com/Metta-AI/diagnosers/tree/main/diagnosers/among_them/among_them_diagnoser",
    }
    assert all("docs/bitworld/among-them" not in source for source in pages.values())


def test_canonical_cogs_vs_clips_template_points_to_source_repo(tmp_path: Path) -> None:
    package = load_coworld_package(
        _materialized_template(tmp_path, WORLDS / "cogs_vs_clips" / "coworld_manifest_template.json")
    )
    pages = {page.id: page.content.value for page in package.manifest.game.docs.pages}

    assert package.manifest.game.runnable.source_url == "https://github.com/Metta-AI/coworld-cogs-vs-clips/tree/main"
    assert package.manifest.game.docs.readme is not None
    assert (
        package.manifest.game.docs.readme.value
        == "https://github.com/Metta-AI/coworld-cogs-vs-clips/blob/main/README.md"
    )
    assert package.manifest.game.protocols.player.value == (
        "https://github.com/Metta-AI/coworld-cogs-vs-clips/blob/main/coworld/game/docs/player_protocol_spec.md"
    )
    assert package.manifest.game.protocols.global_.value == (
        "https://github.com/Metta-AI/coworld-cogs-vs-clips/blob/main/coworld/game/docs/global_protocol_spec.md"
    )
    assert pages["rules.md"] == "https://softmax.com/play_cogsvsclips.md#game-rules"
    assert pages["play_cogsvsclips.md"] == "https://softmax.com/play_cogsvsclips.md"
    assert pages["game-source"] == "https://github.com/Metta-AI/coworld-cogs-vs-clips/tree/main"
    assert pages["player"] == "https://github.com/Metta-AI/coworld-cogs-vs-clips/tree/main/coworld/player"
    assert package.manifest.player[0].source_url == (
        "https://github.com/Metta-AI/coworld-cogs-vs-clips/tree/main/coworld/player"
    )


def test_canonical_crewrift_template_points_to_source_repo(tmp_path: Path) -> None:
    package = load_coworld_package(
        _materialized_template(tmp_path, WORLDS / "crewrift" / "coworld_manifest_template.json")
    )
    pages = {page.id: page.content.value for page in package.manifest.game.docs.pages}

    assert package.manifest.game.runnable.source_url == "https://github.com/Metta-AI/coworld-crewrift/tree/master"
    assert package.manifest.game.docs.readme is not None
    assert (
        package.manifest.game.docs.readme.value == "https://github.com/Metta-AI/coworld-crewrift/blob/master/README.md"
    )
    assert (
        package.manifest.game.protocols.player.value
        == "https://github.com/Metta-AI/coworld-crewrift/blob/master/docs/sprite_v1.md"
    )
    assert (
        package.manifest.game.protocols.global_.value
        == "https://github.com/Metta-AI/coworld-crewrift/blob/master/docs/sprite_v1.md"
    )
    assert pages["rules.md"] == "https://softmax.com/play_crewrift.md#game-rules"
    assert pages["play_crewrift.md"] == "https://softmax.com/play_crewrift.md"
    assert pages["player"] == "https://github.com/Metta-AI/coworld-crewrift/blob/master/players/how_to_make_a_bot.md"
    assert pages["submit"] == (
        "https://github.com/Metta-AI/coworld-crewrift/blob/master/players/how_to_submit_coworld_policy.md"
    )
    assert pages["optimizer"] == "https://github.com/Metta-AI/coworld-crewrift/blob/master/players/SMART_BOT_GUIDE.md"
    assert (
        package.manifest.player[0].source_url
        == "https://github.com/Metta-AI/coworld-crewrift/tree/master/players/notsus"
    )


def test_canonical_among_them_template_declares_all_viability_role_sections() -> None:
    template = json.loads((WORLDS / "among_them" / "coworld_manifest_template.json").read_text(encoding="utf-8"))

    assert set(VIABILITY_ROLE_SECTIONS).issubset(template)
    assert template["commissioner"] == []
    assert [role["type"] for role in template["reporter"]] == ["reporter"]
    assert [role["type"] for role in template["grader"]] == ["grader"]
    assert [role["type"] for role in template["diagnoser"]] == ["diagnoser"]
    assert [role["type"] for role in template["optimizer"]] == ["optimizer"]


def test_cogs_vs_clips_crewrift_and_paintarena_templates_declare_all_viability_role_sections() -> None:
    for world_name in ("cogs_vs_clips", "crewrift", "paintarena"):
        template = json.loads((WORLDS / world_name / "coworld_manifest_template.json").read_text(encoding="utf-8"))

        assert set(VIABILITY_ROLE_SECTIONS).issubset(template)
        for section in VIABILITY_ROLE_SECTIONS:
            assert isinstance(template[section], list)

    cogs_vs_clips = json.loads(
        (WORLDS / "cogs_vs_clips" / "coworld_manifest_template.json").read_text(encoding="utf-8")
    )
    cogs_vs_clips_pages = {page["id"]: page["content"]["value"] for page in cogs_vs_clips["game"]["docs"]["pages"]}
    assert cogs_vs_clips_pages["rules.md"] == "https://softmax.com/play_cogsvsclips.md#game-rules"
    assert cogs_vs_clips_pages["play_cogsvsclips.md"] == "https://softmax.com/play_cogsvsclips.md"
    assert cogs_vs_clips_pages["game-source"] == "https://github.com/Metta-AI/coworld-cogs-vs-clips/tree/main"
    assert cogs_vs_clips_pages["player"] == "https://github.com/Metta-AI/coworld-cogs-vs-clips/tree/main/coworld/player"
    assert "env" not in cogs_vs_clips["player"][0]
    for section in ("commissioner", "reporter", "grader", "optimizer", "diagnoser"):
        assert cogs_vs_clips[section] == []

    crewrift = json.loads((WORLDS / "crewrift" / "coworld_manifest_template.json").read_text(encoding="utf-8"))
    for section in ("commissioner", "reporter", "grader", "optimizer", "diagnoser"):
        assert crewrift[section] == []

    paintarena = json.loads((WORLDS / "paintarena" / "coworld_manifest_template.json").read_text(encoding="utf-8"))
    assert paintarena["commissioner"] == []
    assert paintarena["grader"] == []
    assert paintarena["diagnoser"] == []
    assert [role["type"] for role in paintarena["reporter"]] == ["reporter", "reporter"]
    assert [role["id"] for role in paintarena["reporter"]] == [
        "paint-arena-summarizer",
        "paint-arena-parquet-stats-reporter",
    ]
    assert [role["type"] for role in paintarena["optimizer"]] == ["optimizer"]
    assert [role["id"] for role in paintarena["optimizer"]] == ["paint-arena-reference-optimizer"]


def test_paintarena_example_keeps_template_and_build_copy() -> None:
    assert (PAINTARENA_EXAMPLE / "coworld_manifest_template.json").is_file()
    assert (PAINTARENA_EXAMPLE / "compose.yaml").is_file()
    assert (PAINTARENA_EXAMPLE / "coworld_manifest_template.json").read_text(encoding="utf-8") == (
        WORLDS / "paintarena" / "coworld_manifest_template.json"
    ).read_text(encoding="utf-8")
    assert (PAINTARENA_EXAMPLE / "compose.yaml").read_text(encoding="utf-8") == (
        WORLDS / "paintarena" / "compose.yaml"
    ).read_text(encoding="utf-8").replace("../../packages/coworld/src/coworld/examples/paintarena", ".")
    dockerfile = (PAINTARENA_EXAMPLE / "Dockerfile").read_text(encoding="utf-8")
    for package_dir in ("shared", "game", "player", "reporter", "optimizer"):
        assert f"COPY {package_dir} /app/coworld/examples/paintarena/{package_dir}" in dockerfile


def _world_compose_files() -> tuple[Path, ...]:
    return (
        WORLDS / "among_them" / "compose.yaml",
        WORLDS / "cogs_vs_clips" / "compose.yaml",
        WORLDS / "crewrift" / "compose.yaml",
        WORLDS / "paintarena" / "compose.yaml",
    )


def _world_templates() -> tuple[Path, ...]:
    return (
        WORLDS / "among_them" / "coworld_manifest_template.json",
        WORLDS / "cogs_vs_clips" / "coworld_manifest_template.json",
        WORLDS / "crewrift" / "coworld_manifest_template.json",
        WORLDS / "paintarena" / "coworld_manifest_template.json",
    )


def _materialized_template(base_dir: Path, template_path: Path) -> Path:
    manifest = json.loads(template_path.read_text(encoding="utf-8"))
    manifest["game"]["version"] = "0.1.0"
    image_placeholders = {
        "among_them": {
            "{{GAME_IMAGE}}": "coworld-among-them-game:latest",
            "{{PLAYER_IMAGE}}": "coworld-among-them-ivotewell:latest",
            "{{REPORTER_IMAGE}}": "coworld-among-them-summarizer:latest",
            "{{GRADER_IMAGE}}": "coworld-among-them-grader:latest",
            "{{DIAGNOSER_IMAGE}}": "coworld-among-them-diagnoser:latest",
            "{{OPTIMIZER_IMAGE}}": "coworld-optimizer:latest",
        },
        "cogs_vs_clips": {
            "{{GAME_IMAGE}}": "coworld-cogs-vs-clips-game:latest",
            "{{PLAYER_IMAGE}}": "coworld-cogs-vs-clips-reference-player:latest",
        },
        "crewrift": {
            "{{GAME_IMAGE}}": "coworld-crewrift-game:latest",
            "{{PLAYER_IMAGE}}": "coworld-crewrift-notsus:latest",
        },
        "paintarena": {"{{PAINTARENA_IMAGE}}": "coworld-paintarena:latest"},
    }
    placeholders = image_placeholders[template_path.parent.name]
    game_image = manifest["game"]["runnable"]["image"]
    if game_image in placeholders:
        manifest["game"]["runnable"]["image"] = placeholders[game_image]
    for section in VIABILITY_ROLE_SECTIONS:
        if section in manifest:
            for runnable in manifest[section]:
                image = runnable["image"]
                if image in placeholders:
                    runnable["image"] = placeholders[image]
    output_path = base_dir / template_path.parent.name / "coworld_manifest.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest), encoding="utf-8")
    return output_path
