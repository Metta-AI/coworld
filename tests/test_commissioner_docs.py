from pathlib import Path


def test_commissioner_docs_are_deprecation_stub() -> None:
    docs_path = Path(__file__).parents[1] / "src" / "coworld" / "docs" / "roles" / "COMMISSIONER.md"
    text = docs_path.read_text()

    assert "Deprecated" in text
    assert "platform-ladder-league.md" in text
    assert "commissioner/protocol.py" in text
    assert "Do not scaffold a commissioner image" in text
    assert "schedule_rounds_request" not in text
    assert "commissioner.Dockerfile" not in text
    assert "Platform's round-scheduling logic determines a new round is due" not in text
