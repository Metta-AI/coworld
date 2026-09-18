from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_player_artifact_docs_describe_cli_and_ownership_route() -> None:
    artifact_doc = (PACKAGE_ROOT / "src" / "coworld" / "docs" / "artifacts" / "PLAYER_ARTIFACT.md").read_text(
        encoding="utf-8"
    )
    player_doc = (PACKAGE_ROOT / "src" / "coworld" / "docs" / "roles" / "PLAYER.md").read_text(encoding="utf-8")
    upload_skill = (
        PACKAGE_ROOT / "agents" / "coworlds-expert-agent" / "skills" / "upload-player-artifact" / "SKILL.md"
    ).read_text(encoding="utf-8")
    readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")

    assert "COWORLD_PLAYER_ARTIFACT_UPLOAD_URL" in artifact_doc
    assert "GET /v2/episode-requests/{episode_request_id}/{policy_version_id}/policy-artifact/{agent_idx}" in (
        artifact_doc
    )
    assert "uv run coworld episode-logs ereq_... --agent 0 --artifact --download-dir logs/" in artifact_doc
    assert "uv run coworld replay-open ereq_... --with-artifacts --artifacts-dir artifacts/" in artifact_doc
    assert "an ownership-scoped route does not exist yet" not in artifact_doc
    for contract in (artifact_doc, player_doc, upload_skill):
        assert "Each successful upload replaces" in contract
    assert "Save per-player debugging files after an episode" in readme
    assert "src/coworld/docs/artifacts/PLAYER_ARTIFACT.md" in readme


def test_results_docs_describe_the_seat_display_contract() -> None:
    docs = PACKAGE_ROOT / "src" / "coworld" / "docs"
    results_doc = (docs / "artifacts" / "RESULTS.md").read_text(encoding="utf-8")
    game_doc = (docs / "roles" / "GAME.md").read_text(encoding="utf-8")
    ladder_doc = (docs / "PLATFORM_LADDER_LEAGUE.md").read_text(encoding="utf-8")
    guide = (PACKAGE_ROOT / "docs" / "concepts" / "competition.mdx").read_text(encoding="utf-8")

    assert "## Seat Display (Optional)" in results_doc
    assert '{"slot": 1, "model": "anthropic/claude-haiku-4.5", "label": "briefing only"}' in results_doc
    assert "Never copy prompt or player-file text" in results_doc
    for doc in (results_doc, game_doc, ladder_doc, guide):
        assert "results.players[].model" in doc
    for doc in (game_doc, ladder_doc):
        assert "artifacts/RESULTS.md#seat-display-optional" in doc
    assert "<model> · <policy>:v<N> by <player>" in ladder_doc
