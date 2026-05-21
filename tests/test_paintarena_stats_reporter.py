import json

from coworld.examples.paintarena.reporter import stats_reporter


def test_stats_reporter_builds_replay_stats_rows() -> None:
    replay = stats_reporter.PaintArenaReplay.model_validate(
        {
            "frames": [
                {
                    "tick": 1,
                    "width": 2,
                    "height": 2,
                    "positions": [[0, 0], [1, 0]],
                    "tile_owners": [0, 1, -1, -1],
                    "scores": [1, 1],
                }
            ]
        }
    )
    results = stats_reporter.PaintArenaResults.model_validate(
        {"scores": [1.0, 1.0], "painted_tiles": [1, 1], "ticks": 1}
    )

    rows = stats_reporter.rows_from_episode(replay, results)

    assert [row.ts for row in rows] == [1] * 12
    assert [row.player for row in rows] == [-1, -1, -1, 0, 0, 1, 1, -1, 0, 0, 1, 1]
    assert [row.key for row in rows] == [
        "scores",
        "tile_owners",
        "arena",
        "position",
        "score",
        "position",
        "score",
        "final_results",
        "final_score",
        "painted_tiles",
        "final_score",
        "painted_tiles",
    ]
    assert json.loads(rows[0].value) == [1, 1]
    assert json.loads(rows[-1].value) == 1
