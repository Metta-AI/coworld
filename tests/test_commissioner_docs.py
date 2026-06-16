from pathlib import Path


def test_commissioner_docs_describe_schedule_rounds_boundary() -> None:
    docs_path = Path(__file__).parents[1] / "src" / "coworld" / "docs" / "roles" / "COMMISSIONER.md"
    text = docs_path.read_text()

    assert "schedule_rounds_request" in text
    assert "schedule_rounds_response" in text
    assert "Platform's round-scheduling logic determines a new round is due" not in text
