from pathlib import Path

MACOS_SETUP = Path(__file__).resolve().parents[1] / "src" / "coworld" / "docs" / "MACOS.md"


def test_macos_setup_uses_only_public_installation_paths() -> None:
    setup = MACOS_SETUP.read_text(encoding="utf-8").lower()

    assert "orbstack.dev" in setup
    assert "github.com/abiosoft/colima" in setup
    assert "metta install" not in setup
    assert "softmax" not in setup
    assert "checkout" not in setup
    assert "monorepo" not in setup
