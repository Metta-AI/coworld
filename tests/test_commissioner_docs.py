from pathlib import Path


def test_commissioner_docs_are_deprecation_stub() -> None:
    docs_root = Path(__file__).parents[1] / "src" / "coworld" / "docs"
    text = (docs_root / "roles" / "COMMISSIONER.md").read_text()

    assert "Deprecated" in text
    assert "PLATFORM_LADDER_LEAGUE.md" in text
    assert "MIGRATE_TO_PLATFORM_COMMISSIONER.md" in text
    assert "commissioner/protocol.py" in text
    assert "Do not scaffold a commissioner image" in text
    assert "schedule_rounds_request" not in text
    assert "commissioner.Dockerfile" not in text
    assert "Platform's round-scheduling logic determines a new round is due" not in text


def test_public_ladder_migrate_guides_ship_in_package() -> None:
    docs_root = Path(__file__).parents[1] / "src" / "coworld" / "docs"
    migrate = (docs_root / "MIGRATE_TO_PLATFORM_COMMISSIONER.md").read_text()
    ladder = (docs_root / "PLATFORM_LADDER_LEAGUE.md").read_text()

    assert "github.com/Metta-AI/coworld" in migrate
    assert "Never dual-write" in migrate
    assert "commissioner_key" in migrate
    assert "github.com/Metta-AI/coworld" in ladder
    assert "settings.ladder" in ladder
    assert "docs/specs/" not in migrate
    assert "docs/specs/" not in ladder
