from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from coworld.certifier import load_coworld_package
from coworld.types import CoworldManifest

# Deliberately no `.resolve()`: __file__ is the runfiles path, and
# .resolve() would walk symlinks back into the source tree. That made
# undeclared data files silently readable under local exec (where bazel
# stages declared files via per-file symlinks) while failing under RBE
# (where the executor container has no source tree to escape to). See
# invocation 0a4e4f86-5750-4635-b597-a9aa709b3b76 for the original
# upload.sh miss. Staying inside the runfiles tree makes missing data
# deps fail loudly in every environment.
COWORLD_PACKAGE_ROOT = Path(__file__).parent.parent
REPO_ROOT = COWORLD_PACKAGE_ROOT.parents[1]
COWORLD_SRC = COWORLD_PACKAGE_ROOT / "src" / "coworld"
WORLDS = REPO_ROOT / "worlds"
PAINTARENA_EXAMPLE = COWORLD_SRC / "examples" / "paintarena"
VIABILITY_ROLE_SECTIONS = ("player", "optimizer", "commissioner", "reporter", "grader", "diagnoser")
SUPPORTING_ROLE_REPOS = {
    "commissioner": "https://github.com/Metta-AI/commissioners",
    "reporter": "https://github.com/Metta-AI/reporters",
    "grader": "https://github.com/Metta-AI/graders",
    "diagnoser": "https://github.com/Metta-AI/diagnosers",
    "optimizer": "https://github.com/Metta-AI/optimizers",
}
IN_TREE_EXAMPLE_SOURCE_PREFIX = "https://github.com/Metta-AI/coworld/tree/main/src/coworld/examples/paintarena/"
COWORLD_ISSUES_URL = "https://github.com/Metta-AI/coworld/issues"
PLAY_GUIDE_URI_PREFIXES = (
    "https://softmax.com/play_",
    "https://github.com/Metta-AI/coworld/",
    "https://github.com/Metta-AI/coworld-tribal-village/blob/main/docs/play_tribal_village.md",
)
SOURCE_MANIFEST_REFERENCE_COUNTS = {
    "${GAME_CONTEXT}/coworld_manifest.json": 2,
    "${GAME_CONTEXT}/coworld_manifest_template.json": 2,
    "${GAME_CONTEXT}/coworld_four_score_manifest_template.json": 1,
    "${METTA_REPO}/packages/coworld/src/coworld/examples/paintarena/coworld_manifest_template.json": 1,
}


def test_worlds_directory_is_build_index_not_manifest_source() -> None:
    assert sorted(WORLDS.glob("*/coworld_manifest*.json")) == []


def test_world_upload_uses_canonical_source_manifests() -> None:
    upload_text = (WORLDS / "upload.sh").read_text(encoding="utf-8")

    for source_manifest, expected_count in SOURCE_MANIFEST_REFERENCE_COUNTS.items():
        assert upload_text.count(f'template_file="{source_manifest}"') == expected_count
    assert "${SCRIPT_DIR}/${WORLD}/coworld_manifest_template.json" not in upload_text


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
    for template_path in _repo_manifest_templates():
        template_text = template_path.read_text(encoding="utf-8")
        assert "github.com/Metta-AI/metta" not in template_text
        assert "raw.githubusercontent.com/Metta-AI/metta" not in template_text
        assert "ghcr.io/treeform" not in template_text
        assert "src/coworld/examples/cogs_vs_clips" not in template_text
        assert '"version"' not in json.loads(template_text)["game"]


def test_canonical_play_pages_use_known_guidance_sources() -> None:
    for template_path in _repo_manifest_templates():
        template = json.loads(template_path.read_text(encoding="utf-8"))
        play_pages = [page for page in template["game"]["docs"]["pages"] if page["id"].startswith("play_")]
        assert play_pages, template_path

        for page in play_pages:
            content = page["content"]
            value = content["value"]
            if content["type"] == "uri":
                assert value.startswith(PLAY_GUIDE_URI_PREFIXES)
            else:
                assert COWORLD_ISSUES_URL in value
                assert "file an issue in the Coworld repo" in value
                assert "command, league/Coworld ids, logs or replay links, and the smallest repro" in value
                assert "github.com/Metta-AI/coworld-" not in value


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


def test_canonical_cogs_vs_clips_build_declares_role_contexts() -> None:
    compose_text = (WORLDS / "cogs_vs_clips" / "compose.yaml").read_text(encoding="utf-8")

    assert "GAME_CONTEXT" in compose_text
    assert "PLAYER_CONTEXT" in compose_text
    assert "REPORTER_CONTEXT" in compose_text
    assert "COMMISSIONER_CONTEXT" in compose_text
    assert "METTASCOPE_CONTEXT" in compose_text
    assert "coworld-cogs-vs-clips" in compose_text
    assert "reporters/reporters" in compose_text
    assert "commissioners" in compose_text
    assert "Dockerfile.game" in compose_text
    assert "Dockerfile.player" in compose_text
    assert "cogs_vs_clips/cogs_vs_clips_summarizer/Dockerfile" in compose_text
    assert "commissioners/cogs_vs_clips/cogs_vs_clips_commissioner/Dockerfile" in compose_text
    assert "cogs_src:" in compose_text
    assert "mettascope_src:" in compose_text
    assert "../../packages/mettagrid/nim/mettascope" in compose_text
    assert "coworld-cogs-vs-clips-summarizer:latest" in compose_text
    assert "coworld-cogs-vs-clips-commissioner:latest" in compose_text
    assert "games/games/cogsguard" not in compose_text


def test_canonical_four_score_build_declares_role_contexts() -> None:
    assert (WORLDS / "four_score" / "Dockerfile.game").is_file()
    assert (WORLDS / "four_score" / "Dockerfile.player").is_file()
    compose_text = (WORLDS / "four_score" / "compose.yaml").read_text(encoding="utf-8")

    assert "GAME_CONTEXT" in compose_text
    assert "PLAYER_CONTEXT" in compose_text
    assert "REPORTER_CONTEXT" in compose_text
    assert "METTASCOPE_CONTEXT" in compose_text
    assert "COMMISSIONER_CONTEXT" in compose_text
    assert "coworld-four-score" in compose_text
    assert "reporters/reporters" in compose_text
    assert "commissioners/Dockerfile" in compose_text
    assert "RULESET_STRATEGY_CONFIG_NAME" in compose_text
    assert "four_score" in compose_text
    assert "Dockerfile.game" in compose_text
    assert "Dockerfile.player" in compose_text
    assert "cogs_vs_clips/cogs_vs_clips_summarizer/Dockerfile" in compose_text
    assert "cogs_src:" in compose_text
    assert "mettascope_src:" in compose_text
    assert "../../packages/mettagrid/nim/mettascope" in compose_text
    assert "coworld-cogs-vs-clips-summarizer:latest" in compose_text
    assert "coworld-four-score-commissioner:latest" in compose_text
    assert "games/games/cogsguard" not in compose_text


def test_canonical_crewrift_build_declares_game_context() -> None:
    compose_text = (WORLDS / "crewrift" / "compose.yaml").read_text(encoding="utf-8")
    upload_text = (WORLDS / "upload.sh").read_text(encoding="utf-8")

    assert not (WORLDS / "crewrift" / "coworld_manifest_template.json").exists()
    assert "GAME_CONTEXT" in compose_text
    assert "PLAYER_CONTEXT" not in compose_text
    assert 'PLAYER_CONTEXT="${PLAYER_CONTEXT:-${WORKSPACE_DIR}/players}"' not in upload_text
    assert 'template_file="${GAME_CONTEXT}/coworld_manifest.json"' in upload_text
    assert "coworld-crewrift" in compose_text
    assert "Dockerfile" in compose_text
    assert "players/notsus/Dockerfile" in compose_text
    assert "coworld-crewrift-game:latest" in compose_text
    assert "coworld-crewrift-notsus:latest" in compose_text


def test_canonical_world_compose_files_build_manifest_images() -> None:
    for template_path in _repo_manifest_templates():
        template = json.loads(template_path.read_text(encoding="utf-8"))
        compose_text = (WORLDS / template_path.parent.name / "compose.yaml").read_text(encoding="utf-8")
        normalized_compose_text = compose_text.replace("-", "_")

        image_placeholders = [template["game"]["runnable"]["image"]]
        for section in VIABILITY_ROLE_SECTIONS:
            if section in template:
                for runnable in template[section]:
                    image_placeholders.append(runnable["image"])

        for placeholder in image_placeholders:
            if placeholder.startswith("{{"):
                assert placeholder.endswith("_IMAGE}}")
                service_name = placeholder.removeprefix("{{").removesuffix("_IMAGE}}").lower()
                assert f"  {service_name}:" in normalized_compose_text
            else:
                assert placeholder in compose_text


def test_canonical_world_templates_expose_runnable_source_urls() -> None:
    for template_path in _repo_manifest_templates():
        template = json.loads(template_path.read_text(encoding="utf-8"))
        assert template["game"]["runnable"].get("source_url"), template_path
        for section in VIABILITY_ROLE_SECTIONS:
            for runnable in template[section]:
                assert runnable.get("source_url"), f"{template_path}: {section}.{runnable['id']}"


def test_canonical_world_templates_hydrate_to_valid_manifests(tmp_path: Path) -> None:
    for template_path in _repo_manifest_templates():
        load_coworld_package(_materialized_template(tmp_path, template_path))


def test_canonical_world_templates_use_role_types_as_contracts() -> None:
    for template_path in _repo_manifest_templates():
        template = json.loads(template_path.read_text(encoding="utf-8"))
        assert "contracts" not in template
        assert "debugger" not in template
        assert "extractor" not in template
        for section in VIABILITY_ROLE_SECTIONS:
            for runnable in template[section]:
                assert runnable["type"] == section


def test_canonical_world_supporting_roles_point_to_role_repos() -> None:
    for template_path in _repo_manifest_templates():
        template = json.loads(template_path.read_text(encoding="utf-8"))
        for section, repo_url in SUPPORTING_ROLE_REPOS.items():
            for runnable in template[section]:
                source_url = runnable["source_url"]
                if source_url.startswith(IN_TREE_EXAMPLE_SOURCE_PREFIX):
                    continue
                assert source_url == repo_url or source_url.startswith(f"{repo_url}/")


def test_coworld_manifest_rejects_unknown_role_type(tmp_path: Path) -> None:
    manifest_path = _materialized_template(tmp_path, PAINTARENA_EXAMPLE / "coworld_manifest_template.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["reporter"][0]["type"] = "archivist"

    with pytest.raises(ValidationError, match="reporter.0.type"):
        CoworldManifest.model_validate(manifest)


def test_external_canonical_manifests_live_with_source_repos() -> None:
    expected_readme_references = {
        "among_them": (
            "GAME_CONTEXT=/path/to/coworld-among-them",
            "../coworld-among-them/coworld_manifest.json",
        ),
        "cogs_vs_clips": (
            "GAME_CONTEXT=/path/to/coworld-cogs-vs-clips",
            "../coworld-cogs-vs-clips/coworld_manifest_template.json",
        ),
        "four_score": (
            "GAME_CONTEXT=/path/to/coworld-cogs-vs-clips",
            "../coworld-cogs-vs-clips/coworld_four_score_manifest_template.json",
        ),
        "crewrift": (
            "GAME_CONTEXT=/path/to/coworld-crewrift",
            "../coworld-crewrift/coworld_manifest.json",
        ),
        "tribal_village": (
            "GAME_CONTEXT=/path/to/coworld-tribal-village",
            "../coworld-tribal-village/coworld_manifest_template.json",
        ),
    }

    for world_name, readme_references in expected_readme_references.items():
        readme_text = (WORLDS / world_name / "README.md").read_text(encoding="utf-8")
        assert not (WORLDS / world_name / "coworld_manifest_template.json").exists()
        for reference in readme_references:
            assert reference in readme_text


def test_paintarena_template_declares_all_viability_role_sections() -> None:
    paintarena = json.loads((PAINTARENA_EXAMPLE / "coworld_manifest_template.json").read_text(encoding="utf-8"))
    assert set(VIABILITY_ROLE_SECTIONS).issubset(paintarena)
    for section in VIABILITY_ROLE_SECTIONS:
        assert isinstance(paintarena[section], list)

    assert [role["id"] for role in paintarena["commissioner"]] == ["default-commissioner"]
    assert paintarena["grader"] == []
    assert paintarena["diagnoser"] == []
    assert [role["type"] for role in paintarena["reporter"]] == ["reporter", "reporter"]
    assert [role["id"] for role in paintarena["reporter"]] == [
        "paint-arena-summarizer",
        "paint-arena-parquet-stats-reporter",
    ]
    assert [role["type"] for role in paintarena["optimizer"]] == ["optimizer"]
    assert [role["id"] for role in paintarena["optimizer"]] == ["paint-arena-reference-optimizer"]


def test_paintarena_example_keeps_template_and_worlds_build_pointer() -> None:
    upload_text = (WORLDS / "upload.sh").read_text(encoding="utf-8")

    assert (PAINTARENA_EXAMPLE / "coworld_manifest_template.json").is_file()
    assert (PAINTARENA_EXAMPLE / "compose.yaml").is_file()
    assert not (WORLDS / "paintarena" / "coworld_manifest_template.json").exists()
    assert (
        'template_file="${METTA_REPO}/packages/coworld/src/coworld/examples/paintarena/coworld_manifest_template.json"'
    ) in upload_text
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
        WORLDS / "four_score" / "compose.yaml",
        WORLDS / "crewrift" / "compose.yaml",
        WORLDS / "paintarena" / "compose.yaml",
        WORLDS / "tribal_village" / "compose.yaml",
    )


def _repo_manifest_templates() -> tuple[Path, ...]:
    return (PAINTARENA_EXAMPLE / "coworld_manifest_template.json",)


def _materialized_template(base_dir: Path, template_path: Path) -> Path:
    manifest = json.loads(template_path.read_text(encoding="utf-8"))
    manifest["game"]["version"] = "0.1.0"
    image_placeholders = {
        "paintarena": {
            "{{PAINTARENA_IMAGE}}": "coworld-paintarena:latest",
            "{{COMMISSIONER_IMAGE}}": (
                "ghcr.io/metta-ai/commissioners-default@sha256:"
                "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
            ),
        },
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
