from __future__ import annotations

import os

from pydantic import BaseModel

from coworld.examples.paintarena.shared.supporting_role_io import (
    ZIP_CONTENT_TYPE,
    PaintArenaEpisode,
    deterministic_zip,
    load_paint_arena_episode,
    model_json_bytes,
    paint_arena_outcome,
    write_data,
)

DIAGNOSER_ID = "paint-arena-diagnoser"
HTTP_USER_AGENT = "coworld-paintarena-diagnoser/0.1"


class DiagnoserInputs(BaseModel):
    episode_bundle_uri: str
    target_policy_uri: str
    diagnosis_uri: str


class PaintArenaDiagnosisManifest(BaseModel):
    diagnoser_id: str
    render: str
    findings: str


class PaintArenaDiagnosisFindings(BaseModel):
    diagnoser_id: str
    target_policy_uri: str
    score: float
    scale: str
    margin_tiles: int
    total_tiles: int
    winner_slot: int | None
    recommendations: list[str]


def load_diagnoser_inputs() -> DiagnoserInputs:
    return DiagnoserInputs(
        episode_bundle_uri=os.environ["COGAME_EPISODE_BUNDLE_URI"],
        target_policy_uri=os.environ["COGAME_TARGET_POLICY_URI"],
        diagnosis_uri=os.environ["COGAME_DIAGNOSIS_URI"],
    )


def build_findings(episode: PaintArenaEpisode, target_policy_uri: str) -> PaintArenaDiagnosisFindings:
    outcome = paint_arena_outcome(episode.results, episode.replay)
    recommendations = [
        "Compare the target policy's opening route with the sweep-painter baseline on the same seed.",
        "Use replay frames to find intervals where the target policy walked over already-owned tiles.",
    ]
    if outcome.tie:
        recommendations.append("Break ties by adding an asymmetric first move before entering the sweep loop.")
    elif outcome.score >= 0.2:
        recommendations.append(
            "Large territory margins usually come from missed edge coverage; inspect boundary turns."
        )
    else:
        recommendations.append("The episode was close; prioritize reducing redundant repainting over changing speed.")

    return PaintArenaDiagnosisFindings(
        diagnoser_id=DIAGNOSER_ID,
        target_policy_uri=target_policy_uri,
        score=outcome.score,
        scale="absolute painted-tile margin divided by board area",
        margin_tiles=outcome.margin_tiles,
        total_tiles=outcome.total_tiles,
        winner_slot=outcome.winner_slot,
        recommendations=recommendations,
    )


def render_markdown(findings: PaintArenaDiagnosisFindings) -> str:
    winner = "tie" if findings.winner_slot is None else f"slot {findings.winner_slot}"
    lines = [
        "# Paint Arena Policy Diagnosis",
        "",
        f"- target_policy_uri: `{findings.target_policy_uri}`",
        f"- winner: {winner}",
        f"- margin: {findings.margin_tiles} / {findings.total_tiles} tiles",
        f"- score: {findings.score:.4f}",
        "",
        "## Recommendations",
        "",
    ]
    lines.extend(f"- {recommendation}" for recommendation in findings.recommendations)
    return "\n".join(lines) + "\n"


def build_diagnosis_zip(findings: PaintArenaDiagnosisFindings) -> bytes:
    manifest = PaintArenaDiagnosisManifest(
        diagnoser_id=DIAGNOSER_ID,
        render="diagnosis.md",
        findings="findings.json",
    )
    return deterministic_zip(
        [
            ("manifest.json", model_json_bytes(manifest)),
            ("diagnosis.md", render_markdown(findings).encode("utf-8")),
            ("findings.json", model_json_bytes(findings)),
        ]
    )


def run(inputs: DiagnoserInputs) -> PaintArenaDiagnosisFindings:
    episode = load_paint_arena_episode(inputs.episode_bundle_uri, user_agent=HTTP_USER_AGENT)
    findings = build_findings(episode, inputs.target_policy_uri)
    write_data(
        inputs.diagnosis_uri,
        build_diagnosis_zip(findings),
        content_type=ZIP_CONTENT_TYPE,
        user_agent=HTTP_USER_AGENT,
    )
    return findings


def main() -> None:
    run(load_diagnoser_inputs())


if __name__ == "__main__":
    main()
