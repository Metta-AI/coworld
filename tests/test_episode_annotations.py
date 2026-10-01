import json
import zipfile
from io import BytesIO
from types import SimpleNamespace
from typing import cast

import pytest

from coworld.annotations import ANNOTATIONS_TARGETS_ENV, EpisodeAnnotation, annotation_file_error, read_annotations
from coworld.runner import kubernetes_runner
from coworld.runner.phase_timings import EpisodePhaseTimings
from coworld.runner.runner import EpisodeArtifacts
from coworld.types import CoworldEpisodeJobSpec


def test_game_hosted_annotations_are_optional_and_reach_storage(monkeypatch, tmp_path):
    stored = tmp_path / "stored.jsonl"
    monkeypatch.setenv(ANNOTATIONS_TARGETS_ENV, json.dumps({"0": stored.as_uri()}))
    monkeypatch.delenv("PLAYER_ARTIFACT_UPLOAD_URLS", raising=False)
    artifacts = EpisodeArtifacts.create(tmp_path)
    kubernetes_runner._prepare_game_hosted_outputs(
        cast(CoworldEpisodeJobSpec, SimpleNamespace(players=[object()])), artifacts, EpisodePhaseTimings()
    )
    assert kubernetes_runner._upload_player_artifacts(artifacts) == 0
    assert not stored.exists()
    event = EpisodeAnnotation(time=258, kind="intent", function="selectTarget", args={"target": "foo"})
    payload = event.model_dump_json(exclude_none=True).encode() + b"\n"
    artifacts.policy_annotations_path(0).write_bytes(payload)
    kubernetes_runner._prepare_game_hosted_outputs(
        cast(CoworldEpisodeJobSpec, SimpleNamespace(players=[object()])), artifacts, EpisodePhaseTimings()
    )
    assert kubernetes_runner._upload_player_artifacts(artifacts) == 0
    assert stored.read_bytes() == payload
    records = list(read_annotations(BytesIO(payload), participant_slot=0))
    assert json.loads(records[0]) == event.model_dump(exclude_none=True) | {"participant_slot": 0, "seq": 0}


@pytest.mark.parametrize(
    "payload",
    [
        b"{\n",
        b"{}\n",
        b"{}",
        b"x" * 16385 + b"\n",
        b'{"schema_version":2,"time":1,"kind":"intent","function":"f","args":{}}\n',
        b'{"time":1,"kind":"intent","function":"f","args":{"value":NaN}}\n',
    ],
)
def test_collection_rejects_invalid_annotations_without_replacing_output(monkeypatch, tmp_path, payload):
    stored = tmp_path / "stored.jsonl"
    stored.write_bytes(b"previous")
    monkeypatch.setenv(ANNOTATIONS_TARGETS_ENV, json.dumps({"0": stored.as_uri()}))
    monkeypatch.delenv("PLAYER_ARTIFACT_UPLOAD_URLS", raising=False)
    artifacts = EpisodeArtifacts.create(tmp_path)
    artifacts.policy_annotations_path(0).write_bytes(payload)
    artifacts.policy_log_path(0).write_bytes(b"original policy output")
    log = tmp_path / "published.log"
    debug = tmp_path / "debug.zip"
    monkeypatch.setenv("POLICY_LOG_URLS", json.dumps({"0": log.as_uri()}))
    monkeypatch.setenv("DEBUG_URI", debug.as_uri())
    kubernetes_runner._prepare_game_hosted_outputs(
        cast(CoworldEpisodeJobSpec, SimpleNamespace(players=[object()])), artifacts, EpisodePhaseTimings()
    )
    kubernetes_runner._upload_debug_logs(artifacts)
    kubernetes_runner._upload_player_artifacts(artifacts)
    assert stored.read_bytes() == b"previous"
    assert log.read_bytes().startswith(b"[Annotations rejected:")
    assert log.read_bytes().endswith(b"original policy output")
    with zipfile.ZipFile(debug) as archive:
        assert archive.read("policy_agent_0.log") == log.read_bytes()
    assert artifacts.policy_log_path(0).read_bytes() == b"original policy output"


def test_annotation_attribution_is_platform_controlled():
    event = EpisodeAnnotation(time=0, kind="decision", function="move", args={}, participant_slot=999, seq=999)
    source = BytesIO(event.model_dump_json().encode() + b"\n")
    assert annotation_file_error(source) is None
    record = json.loads(next(read_annotations(source, participant_slot=2, first_seq=7)))
    assert (record["participant_slot"], record["seq"]) == (2, 7)
