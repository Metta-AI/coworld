from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_coworld_author_docs_describe_certify_replay_liveness() -> None:
    cookbook = (PACKAGE_ROOT / "COOKBOOK.md").read_text(encoding="utf-8")
    game_role = (PACKAGE_ROOT / "src" / "coworld" / "docs" / "roles" / "GAME.md").read_text(encoding="utf-8")

    assert "verifies `GET /client/replay`" in cookbook
    assert "waits for a frame from" in cookbook
    assert "the `/replay` WebSocket" in cookbook
    assert "open the printed replay command and watch the replay once before upload" in cookbook
    assert "`coworld certify` validates replay liveness for game authors" in game_role
    assert "inspect the browser replay before uploading" in " ".join(game_role.split())
