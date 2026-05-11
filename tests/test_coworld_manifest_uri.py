import gzip
import json
from pathlib import Path

from pytest import MonkeyPatch
from pytest_httpserver import HTTPServer

from coworld import manifest_uri
from coworld.manifest_uri import materialized_manifest_path, materialized_replay_path

COWORLD_ID = "cow_00000000-0000-0000-0000-000000000001"
COWORLD_PATH = f"/v2/coworlds/{COWORLD_ID}"


def test_materialized_manifest_path_accepts_local_paths(tmp_path: Path) -> None:
    manifest_path = tmp_path / "coworld_manifest.json"
    manifest_path.write_text(json.dumps({"game": {}}))

    with materialized_manifest_path(str(manifest_path)) as resolved:
        assert resolved == manifest_path.resolve()


def test_materialized_manifest_path_accepts_local_cow_prefixed_paths(
    tmp_path: Path, monkeypatch: MonkeyPatch, httpserver: HTTPServer
) -> None:
    manifest_path = tmp_path / "cow_paintarena" / "coworld_manifest.json"
    manifest_path.parent.mkdir()
    manifest_path.write_text(json.dumps({"game": {}}))
    monkeypatch.chdir(tmp_path)

    with materialized_manifest_path("cow_paintarena/coworld_manifest.json", server=httpserver.url_for("")) as resolved:
        assert resolved == manifest_path.resolve()


def test_materialized_manifest_path_downloads_raw_manifest(httpserver: HTTPServer) -> None:
    manifest = {"game": {"name": "downloaded"}}
    httpserver.expect_request("/manifest.json").respond_with_json(manifest)

    with materialized_manifest_path(httpserver.url_for("/manifest.json")) as resolved:
        assert json.loads(resolved.read_text()) == manifest


def test_materialized_manifest_path_downloads_coworld_response(httpserver: HTTPServer) -> None:
    manifest = {"game": {"name": "downloaded"}}
    httpserver.expect_request(COWORLD_PATH).respond_with_json({"manifest": manifest})

    with materialized_manifest_path(httpserver.url_for(COWORLD_PATH)) as resolved:
        assert json.loads(resolved.read_text()) == manifest


def test_materialized_manifest_path_resolves_backend_path_against_server(httpserver: HTTPServer) -> None:
    manifest = {"game": {"name": "downloaded"}}
    httpserver.expect_request(COWORLD_PATH).respond_with_json({"manifest": manifest})

    with materialized_manifest_path(COWORLD_PATH, server=httpserver.url_for("")) as resolved:
        assert json.loads(resolved.read_text()) == manifest


def test_materialized_manifest_path_resolves_bare_coworld_id_against_server(httpserver: HTTPServer) -> None:
    manifest = {"game": {"name": "downloaded"}}
    httpserver.expect_request(COWORLD_PATH).respond_with_json({"manifest": manifest})

    with materialized_manifest_path(COWORLD_ID, server=httpserver.url_for("")) as resolved:
        assert json.loads(resolved.read_text()) == manifest


def test_materialized_replay_path_downloads_replay_uri(httpserver: HTTPServer) -> None:
    replay_bytes = gzip.compress(b'{"events":[]}')
    httpserver.expect_request("/replay.json.z").respond_with_data(replay_bytes)

    with materialized_replay_path(httpserver.url_for("/replay.json.z")) as resolved:
        assert resolved.name == "replay.json"
        assert resolved.read_bytes() == b'{"events":[]}'


def test_materialized_replay_path_downloads_s3_uri(monkeypatch: MonkeyPatch) -> None:
    replay_uri = "s3://softmax-public/replays/episode.json.z"
    replay_bytes = gzip.compress(b'{"events":[]}')

    def read_data(uri: str) -> bytes:
        assert uri == replay_uri
        return replay_bytes

    monkeypatch.setattr(manifest_uri, "read_data", read_data)

    with materialized_replay_path(replay_uri) as resolved:
        assert resolved.name == "replay.json"
        assert resolved.read_bytes() == b'{"events":[]}'


def test_materialized_replay_path_decompresses_local_replay(tmp_path: Path) -> None:
    replay_path = tmp_path / "episode.json.z"
    replay_path.write_bytes(gzip.compress(b'{"events":[]}'))

    with materialized_replay_path(str(replay_path)) as resolved:
        assert resolved.name == "replay.json"
        assert resolved.read_bytes() == b'{"events":[]}'
