from __future__ import annotations

import os

from pydantic import BaseModel

from coworld.examples.paintarena.shared.supporting_role_io import (
    JSON_CONTENT_TYPE,
    PaintArenaEpisode,
    load_paint_arena_episode,
    model_json_bytes,
    paint_arena_outcome,
    write_data,
)

GRADER_ID = "paint-arena-grader"
HTTP_USER_AGENT = "coworld-paintarena-grader/0.1"


class GraderInputs(BaseModel):
    episode_bundle_uri: str
    grade_uri: str


class PaintArenaGrade(BaseModel):
    grader_id: str
    score: float
    scale: str
    margin_tiles: int
    total_tiles: int
    winner_slot: int | None


def load_grader_inputs() -> GraderInputs:
    return GraderInputs(
        episode_bundle_uri=os.environ["COGAME_EPISODE_BUNDLE_URI"],
        grade_uri=os.environ["COGAME_GRADE_URI"],
    )


def build_grade(episode: PaintArenaEpisode) -> PaintArenaGrade:
    outcome = paint_arena_outcome(episode.results, episode.replay)
    return PaintArenaGrade(
        grader_id=GRADER_ID,
        score=outcome.score,
        scale="absolute painted-tile margin divided by board area",
        margin_tiles=outcome.margin_tiles,
        total_tiles=outcome.total_tiles,
        winner_slot=outcome.winner_slot,
    )


def run(inputs: GraderInputs) -> PaintArenaGrade:
    episode = load_paint_arena_episode(inputs.episode_bundle_uri, user_agent=HTTP_USER_AGENT)
    grade = build_grade(episode)
    write_data(
        inputs.grade_uri,
        model_json_bytes(grade),
        content_type=JSON_CONTENT_TYPE,
        user_agent=HTTP_USER_AGENT,
    )
    return grade


def main() -> None:
    run(load_grader_inputs())


if __name__ == "__main__":
    main()
