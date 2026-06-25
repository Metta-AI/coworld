from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from coworld.examples.paintarena.grader import paint_arena_grader as grader


def test_paintarena_grader_writes_margin_score(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    paint_arena_episode_bundle_path: Callable[[list[int], int, int], Path],
) -> None:
    bundle_path = paint_arena_episode_bundle_path([60, 36], 12, 8)
    grade_path = tmp_path / "grade.json"
    monkeypatch.setenv("COGAME_EPISODE_BUNDLE_URI", bundle_path.as_uri())
    monkeypatch.setenv("COGAME_GRADE_URI", grade_path.as_uri())

    grade = grader.run(grader.load_grader_inputs())
    artifact = json.loads(grade_path.read_text(encoding="utf-8"))

    assert grade.score == 0.25
    assert artifact == {
        "grader_id": "paint-arena-grader",
        "score": 0.25,
        "scale": "absolute painted-tile margin divided by board area",
        "margin_tiles": 24,
        "total_tiles": 96,
        "winner_slot": 0,
    }


def test_paintarena_grader_rejects_non_two_player_results(
    tmp_path: Path,
    paint_arena_episode_bundle_path: Callable[[list[int], int, int], Path],
) -> None:
    bundle_path = paint_arena_episode_bundle_path([10], 12, 8)
    inputs = grader.GraderInputs(
        episode_bundle_uri=bundle_path.as_uri(),
        grade_uri=(tmp_path / "grade.json").as_uri(),
    )

    with pytest.raises(ValueError, match="exactly two painted_tiles"):
        grader.run(inputs)
