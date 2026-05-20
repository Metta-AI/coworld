from __future__ import annotations

import json
from pathlib import Path

from coworld.certifier import load_coworld_package

COWORLD_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = COWORLD_PACKAGE_ROOT.parents[1]
COWORLD_SRC = COWORLD_PACKAGE_ROOT / "src" / "coworld"
WORLDS = REPO_ROOT / "worlds"
PAINTARENA_EXAMPLE = COWORLD_SRC / "examples" / "paintarena"
PUBLIC_COWORLD_PACKAGE_DOCS = "https://pypi.org/project/coworld/"
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
    assert WORLDS.parent == REPO_ROOT
    assert COWORLD_PACKAGE_ROOT not in WORLDS.parents
    for compose_file in _world_compose_files():
        compose_text = compose_file.read_text(encoding="utf-8")
        assert "METTA_REPO" not in compose_text
        assert str(COWORLD_SRC) not in compose_text


def test_canonical_world_templates_do_not_publish_metta_repo_links() -> None:
    for template_path in _world_templates():
        template_text = template_path.read_text(encoding="utf-8")
        assert "github.com/Metta-AI/metta" not in template_text
        assert "raw.githubusercontent.com/Metta-AI/metta" not in template_text
        assert "ghcr.io/treeform" not in template_text
        assert '"version"' not in json.loads(template_text)["game"]


def test_canonical_among_them_build_declares_role_starter_contexts() -> None:
    compose_text = (WORLDS / "among_them" / "compose.yaml").read_text(encoding="utf-8")

    assert "GAME_CONTEXT" in compose_text
    assert "PLAYER_CONTEXT" in compose_text
    assert "COMMISSIONER_CONTEXT" in compose_text
    assert "REPORTER_CONTEXT" in compose_text
    assert "OPTIMIZER_CONTEXT" in compose_text
    assert "players/players/among_them/starter" in compose_text
    assert "commissioners/amongthem/starter" in compose_text
    assert "reporters/amongthem/starter" in compose_text
    assert "optimizers/amongthem/starter" in compose_text
    assert "ghcr.io/treeform" not in compose_text
    assert "policies/symbolic/bitworld/among-them/ivotewell" not in compose_text
    assert "WORLD_CONTEXT" not in compose_text


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
            assert placeholder.startswith("{{")
            assert placeholder.endswith("_IMAGE}}")
            service_name = placeholder.removeprefix("{{").removesuffix("_IMAGE}}").lower()
            assert f"  {service_name}:" in compose_text


def test_canonical_world_templates_hydrate_to_valid_manifests(tmp_path: Path) -> None:
    for template_path in (*_world_templates(), PAINTARENA_EXAMPLE / "coworld_manifest_template.json"):
        load_coworld_package(_materialized_template(tmp_path, template_path))


def test_canonical_among_them_template_points_to_source_repos(tmp_path: Path) -> None:
    package = load_coworld_package(
        _materialized_template(tmp_path, WORLDS / "among_them" / "coworld_manifest_template.json")
    )
    pages = {page.id: page.content.value for page in package.manifest.game.docs.pages}

    assert package.manifest.commissioner == []
    assert package.manifest.reporter == []
    assert package.manifest.grader == []
    assert package.manifest.diagnoser == []
    assert package.manifest.optimizer == []
    assert pages["game-source"] == "https://github.com/Metta-AI/bitworld/tree/master/among_them"
    assert pages["player"] == (
        "https://github.com/Metta-AI/bitworld/blob/master/among_them/players/how_to_make_a_bot.md"
    )
    assert pages["submit"] == (
        "https://github.com/Metta-AI/bitworld/blob/master/among_them/players/how_to_submit_coworld_policy.md"
    )
    assert pages["optimizer"] == (
        "https://github.com/Metta-AI/bitworld/blob/master/among_them/players/SMART_BOT_GUIDE.md"
    )
    assert pages["commissioner"] == PUBLIC_COWORLD_PACKAGE_DOCS
    assert pages["reporter"] == PUBLIC_COWORLD_PACKAGE_DOCS
    assert pages["grader"] == PUBLIC_COWORLD_PACKAGE_DOCS
    assert pages["diagnoser"] == PUBLIC_COWORLD_PACKAGE_DOCS
    assert all("github.com/Metta-AI/coworld" not in source for source in pages.values())
    assert all("github.com/Metta-AI/players" not in source for source in pages.values())
    assert all("docs/bitworld/among-them" not in source for source in pages.values())


def test_canonical_among_them_template_declares_all_viability_role_sections() -> None:
    template = json.loads((WORLDS / "among_them" / "coworld_manifest_template.json").read_text(encoding="utf-8"))

    assert set(VIABILITY_ROLE_SECTIONS).issubset(template)
    assert template["commissioner"] == []
    assert template["reporter"] == []
    assert template["grader"] == []
    assert template["diagnoser"] == []
    assert template["optimizer"] == []


def test_cogs_vs_clips_and_paintarena_templates_declare_all_viability_role_sections() -> None:
    for world_name in ("cogs_vs_clips", "paintarena"):
        template = json.loads((WORLDS / world_name / "coworld_manifest_template.json").read_text(encoding="utf-8"))

        assert set(VIABILITY_ROLE_SECTIONS).issubset(template)
        for section in VIABILITY_ROLE_SECTIONS:
            assert isinstance(template[section], list)

    cogs_vs_clips = json.loads(
        (WORLDS / "cogs_vs_clips" / "coworld_manifest_template.json").read_text(encoding="utf-8")
    )
    for section in ("optimizer", "commissioner", "reporter", "grader", "diagnoser"):
        assert cogs_vs_clips[section] == []

    paintarena = json.loads((WORLDS / "paintarena" / "coworld_manifest_template.json").read_text(encoding="utf-8"))
    for section in ("optimizer", "commissioner", "grader", "diagnoser"):
        assert paintarena[section] == []
    assert [role["type"] for role in paintarena["reporter"]] == ["reporter"]


def test_paintarena_example_keeps_template_and_build_copy() -> None:
    assert (PAINTARENA_EXAMPLE / "coworld_manifest_template.json").is_file()
    assert (PAINTARENA_EXAMPLE / "compose.yaml").is_file()
    assert (PAINTARENA_EXAMPLE / "coworld_manifest_template.json").read_text(encoding="utf-8") == (
        WORLDS / "paintarena" / "coworld_manifest_template.json"
    ).read_text(encoding="utf-8")
    assert (PAINTARENA_EXAMPLE / "compose.yaml").read_text(encoding="utf-8") == (
        WORLDS / "paintarena" / "compose.yaml"
    ).read_text(encoding="utf-8").replace("../../packages/coworld/src/coworld/examples/paintarena", ".")


def _world_compose_files() -> tuple[Path, ...]:
    return (
        WORLDS / "among_them" / "compose.yaml",
        WORLDS / "cogs_vs_clips" / "compose.yaml",
        WORLDS / "paintarena" / "compose.yaml",
    )


def _world_templates() -> tuple[Path, ...]:
    return (
        WORLDS / "among_them" / "coworld_manifest_template.json",
        WORLDS / "cogs_vs_clips" / "coworld_manifest_template.json",
        WORLDS / "paintarena" / "coworld_manifest_template.json",
    )


def _materialized_template(base_dir: Path, template_path: Path) -> Path:
    manifest = json.loads(template_path.read_text(encoding="utf-8"))
    manifest["game"]["version"] = "0.1.0"
    image_placeholders = {
        "among_them": {
            "{{GAME_IMAGE}}": "coworld-among-them-game:latest",
            "{{PLAYER_IMAGE}}": "coworld-among-them-ivotewell:latest",
        },
        "cogs_vs_clips": {
            "{{GAME_IMAGE}}": "coworld-cogs-vs-clips-game:latest",
            "{{PLAYER_IMAGE}}": "coworld-mettagrid-policy-player:latest",
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
