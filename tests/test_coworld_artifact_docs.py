from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_player_artifact_docs_describe_cli_and_ownership_route() -> None:
    artifact_doc = (PACKAGE_ROOT / "src" / "coworld" / "docs" / "artifacts" / "PLAYER_ARTIFACT.md").read_text(
        encoding="utf-8"
    )
    readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")

    assert "COWORLD_PLAYER_ARTIFACT_UPLOAD_URL" in artifact_doc
    assert "GET /v2/episode-requests/{episode_request_id}/{policy_version_id}/policy-artifact/{agent_idx}" in (
        artifact_doc
    )
    assert "uv run coworld episode-logs ereq_... --agent 0 --artifact --download-dir logs/" in artifact_doc
    assert "uv run coworld replay-open ereq_... --with-artifacts --artifacts-dir artifacts/" in artifact_doc
    assert "an ownership-scoped route does not exist yet" not in artifact_doc
    assert "Save per-player debugging files after an episode" in readme
    assert "src/coworld/docs/artifacts/PLAYER_ARTIFACT.md" in readme
