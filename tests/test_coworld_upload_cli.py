import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Literal, cast

import pytest
from pytest_httpserver import HTTPServer
from typer.testing import CliRunner
from werkzeug import Request, Response

from coworld.cli import app
from coworld.player_files import player_file_bytes
from coworld.runner.external_llm import EXTERNAL_LLM_SECRET_KEY, ExternalLlmRoute
from coworld.upload import (
    CoworldUploadClient,
    CoworldUploadResponse,
    ReplayViewerBundleCompleteResponse,
    _certification_cache_key,
    _certification_snapshot,
    _certified_manifest_cache_path,
    _submit_player_files,
    download_agents_md,
    upload_coworld,
)


@pytest.fixture(autouse=True)
def _fake_softmax_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr("softmax_client.credentials.load_current_token", lambda *, server: "token")
    monkeypatch.setattr("softmax_client.credentials.load_user_token", lambda *, server: "token")


@pytest.fixture(autouse=True)
def _feed_flag_off(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/observatory/flags/me", method="GET").respond_with_json({"flags": {"feed-v1": False}})


class _FakeCoworldUploadClient:
    def __init__(self) -> None:
        self.uploads: list[dict[str, object]] = []

    def __enter__(self) -> "_FakeCoworldUploadClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def upload_manifest(
        self, manifest: dict[str, object], *, visibility: Literal["public", "private"] | None = None
    ) -> CoworldUploadResponse:
        self.uploads.append(manifest)
        return CoworldUploadResponse.model_validate(
            _coworld_entry("cow_00000000-0000-0000-0000-000000000999", manifest, version="0.1.0", canonical=True)
        )


def test_certification_cache_key_changes_with_certifier_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _write_manifest(tmp_path)
    monkeypatch.setattr("coworld.upload._local_image_client_hash", lambda image: "sha256:runtime")

    monkeypatch.setattr("coworld.upload._certification_code_digest", lambda: "sha256:certifier-v1")
    key_v1 = _certification_cache_key(manifest_path)
    key_v1_again = _certification_cache_key(manifest_path)
    monkeypatch.setattr("coworld.upload._certification_code_digest", lambda: "sha256:certifier-v2")
    key_v2 = _certification_cache_key(manifest_path)

    assert key_v1 == key_v1_again
    assert key_v1 != key_v2


def test_upload_coworld_certification_cache_includes_local_image_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _write_manifest(tmp_path)
    certification_calls: list[tuple[Path, float]] = []
    fake_client = _FakeCoworldUploadClient()
    current_hash = "sha256:runtime-a"

    def fake_hash(image: str) -> str:
        return current_hash

    monkeypatch.setattr(
        "coworld.upload.certify_coworld",
        lambda path, *, workspace, timeout_seconds: certification_calls.append((path, timeout_seconds)),
    )
    monkeypatch.setattr("coworld.upload._local_image_client_hash", fake_hash)
    monkeypatch.setattr("coworld.upload._manifest_with_softmax_image_ids", lambda _client, manifest: manifest)
    monkeypatch.setattr(
        CoworldUploadClient,
        "from_login",
        classmethod(lambda _cls, *, server_url: fake_client),
    )

    upload_coworld(manifest_path, server="https://example.com/api")
    upload_coworld(manifest_path, server="https://example.com/api")
    current_hash = "sha256:runtime-b"
    upload_coworld(manifest_path, server="https://example.com/api")

    assert len(certification_calls) == 2


def test_upload_coworld_does_not_cache_failed_certification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _write_manifest(tmp_path)

    def fail_certification(_manifest_path: Path, *, workspace: Path, timeout_seconds: float) -> None:
        raise RuntimeError("certification failed")

    monkeypatch.setattr("coworld.upload.certify_coworld", fail_certification)
    monkeypatch.setattr("coworld.upload._local_image_client_hash", lambda image: "sha256:runtime")

    with pytest.raises(RuntimeError, match="certification failed"):
        upload_coworld(manifest_path, server="https://example.com/api")

    assert not _certified_manifest_cache_path().exists()


def test_player_file_size_cap_is_enforced_before_reading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    player_file = tmp_path / "player.bin"
    player_file.write_bytes(b"oversized")
    monkeypatch.setattr("coworld.player_files.PLAYER_FILE_MAX_BYTES", 4)
    monkeypatch.setattr(Path, "read_bytes", lambda _self: pytest.fail("oversized file was read"))

    with pytest.raises(ValueError, match="size limit"):
        player_file_bytes(player_file)


@pytest.mark.parametrize("reference", ["missing.wasm", "../outside.wasm"])
def test_submit_player_files_rejects_missing_or_out_of_package_paths(tmp_path: Path, reference: str) -> None:
    (tmp_path.parent / "outside.wasm").write_bytes(b"outside")

    with pytest.raises(ValueError):
        _submit_player_files(cast(CoworldUploadClient, object()), {"player": [{"file": reference}]}, tmp_path)


def test_download_agent_guide_does_not_copy_untrusted_doc_text() -> None:
    manifest = _manifest()
    manifest["game"]["docs"] = {
        "readme": {"type": "text", "value": "UNTRUSTED README INSTRUCTIONS"},
        "pages": [
            {
                "id": "rules",
                "title": "Rules [v1]\n# heading",
                "content": {"type": "uri", "value": "https://example.com/rules(v1)"},
            },
            {
                "id": "strategy",
                "title": "Strategy",
                "content": {"type": "text", "value": "UNTRUSTED STRATEGY INSTRUCTIONS"},
            },
        ],
    }
    guide = download_agents_md("https://softmax.com/api", [], manifest)
    assert "UNTRUSTED" not in guide


def _write_manifest(tmp_path: Path, manifest: dict[str, object] | None = None) -> Path:
    world_dir = tmp_path / "world"
    world_dir.mkdir(parents=True)
    manifest_path = world_dir / "coworld_manifest.json"
    manifest_path.write_text(json.dumps(_manifest() if manifest is None else manifest))
    return manifest_path


def _coworld_entry(
    coworld_id: str,
    manifest: dict[str, object],
    *,
    version: str,
    canonical: bool,
    name: str = "unit-test-game",
) -> dict[str, object]:
    return {
        "id": coworld_id,
        "name": name,
        "version": version,
        "visibility": "public",
        "manifest": manifest,
        "manifest_summary": _manifest_summary(manifest),
        "manifest_hash": "sha256:manifest-hash",
        "size_bytes": 1234,
        "created_at": "2026-05-08T21:00:00Z",
        "canonical": canonical,
        "forum_markdown_url": f"https://softmax.com/api/observatory/v2/forums/{name}.md",
        "wiki_markdown_url": f"https://softmax.com/api/observatory/v2/wikis/{name}/pages.md",
        "documentation_url": "https://softmax.com/docs/coworld/build-a-player/choose-a-coworld",
        "certification_status_url": f"https://softmax.com/api/observatory/v2/coworlds/{coworld_id}/certification",
        "certification_transcript_url": f"https://softmax.com/api/observatory/v2/coworlds/{coworld_id}/certification/transcript",
    }


def _manifest_summary(manifest: dict[str, object]) -> dict[str, object]:
    game = cast(dict[str, object], manifest["game"])
    variants = cast(list[dict[str, object]], manifest["variants"])
    return {
        "description": game["description"],
        "owner": game["owner"],
        "variants": [{"id": variant["id"], "name": variant["name"]} for variant in variants],
        "role_counts": {
            role: len(cast(list[object], manifest.get(role, [])))
            for role in ("player", "commissioner", "grader", "diagnoser", "optimizer")
        },
    }


def _manifest() -> dict[str, object]:
    return {
        "tags": ["test", "multiplayer", "real-time"],
        "game": {
            "name": "unit-test-game",
            "version": "0.1.0",
            "description": "Unit test Coworld manifest.",
            "owner": "coworld@softmax.com",
            "runnable": {
                "type": "game",
                "image": "unit-test-runtime:latest",
                "run": ["python", "-m", "unit_test.game"],
            },
            "config_schema": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": ["tokens"],
                "properties": {
                    "tokens": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 1,
                        "items": {"type": "string"},
                    }
                },
            },
            "results_schema": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "required": ["scores"],
                "properties": {"scores": {"type": "array", "items": {"type": "number"}}},
            },
            "protocols": {
                "player": {"type": "uri", "value": "https://example.com/player_protocol_spec.md"},
                "global": {"type": "uri", "value": "https://example.com/global_protocol_spec.md"},
            },
            "docs": {
                "readme": {"type": "uri", "value": "https://example.com/README.md"},
                "pages": [
                    {
                        "id": "rules.md",
                        "title": "rules.md",
                        "content": {"type": "text", "value": "# Rules\n\nScore one point."},
                    },
                    {
                        "id": "play_unittest.md",
                        "title": "play_unittest.md",
                        "content": {"type": "uri", "value": "https://example.com/play_unittest.md"},
                    },
                ],
            },
        },
        "player": [
            {
                "id": "unit-test-player",
                "name": "Unit Test Player",
                "description": "Unit test player.",
                "type": "player",
                "image": "unit-test-runtime:latest",
                "run": ["python", "-m", "unit_test.player"],
            }
        ],
        "reporter": [{"reporter": "softmax/default@1"}],
        "grader": [
            {
                "id": "unit-test-grader",
                "name": "Unit Test Grader",
                "description": "Default grader stub.",
                "type": "grader",
                "image": "ghcr.io/metta-ai/graders-default@sha256:graderdigest",
                "source_url": "https://github.com/Metta-AI/coworld-tools/tree/e6b7863c2619d260bb29f14364baf09c578c9f30/graders/graders/default/default_grader",
            }
        ],
        "variants": [
            {
                "id": "default",
                "name": "Default",
                "description": "Default unit test variant.",
                "game_config": {},
            }
        ],
        "certification": {"game_config": {}, "players": [{"player_id": "unit-test-player"}]},
    }


def _manifest_with_image(image: str) -> dict[str, object]:
    manifest = _manifest()
    game = manifest["game"]
    assert isinstance(game, dict)
    runnable = game["runnable"]
    assert isinstance(runnable, dict)
    runnable["image"] = image
    players = manifest["player"]
    assert isinstance(players, list)
    player = players[0]
    assert isinstance(player, dict)
    player["image"] = image
    graders = manifest["grader"]
    assert isinstance(graders, list)
    grader = graders[0]
    assert isinstance(grader, dict)
    grader["image"] = image
    return manifest


def _manifest_with_player_file(image: str, content_hash: str) -> dict[str, object]:
    manifest = _manifest_with_image(image)
    game = cast(dict[str, object], manifest["game"])
    game["player_runtime"] = "game-hosted"
    player = cast(list[dict[str, object]], manifest["player"])[0]
    del player["image"]
    player.pop("run", None)
    player["file"] = f"sha256:{content_hash}"
    return manifest


def test_complete_replay_viewer_bundle_treats_504_as_indeterminate(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content_hash = "b" * 64
    bundle = f"sha256:{content_hash}"
    httpserver.expect_request(
        "/observatory/v2/coworlds/replay-viewer-bundles/upload/complete",
        method="POST",
        json={"content_hash": content_hash, "size_bytes": 12},
    ).respond_with_data("softmax.com | 504: Gateway time-out", status=504)
    httpserver.expect_request(
        f"/observatory/v2/coworlds/replay-viewer-bundles/{content_hash}",
        method="GET",
    ).respond_with_json({"bundle": bundle, "status": "ready"})
    monkeypatch.setattr("coworld.upload.time.sleep", lambda _seconds: None)

    with CoworldUploadClient(server_url=httpserver.url_for(""), token="token") as client:
        result = client.complete_replay_viewer_bundle_upload(content_hash=content_hash, size_bytes=12)

    assert result == ReplayViewerBundleCompleteResponse(bundle=bundle, status="ready")


@pytest.mark.parametrize("mutation", ["wasm", "viewer", "add", "rename", "delete"])
def test_certification_cache_key_tracks_payload_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    manifest_path = _write_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    manifest["reporter"] = [{"wasm": "reporter.wasm"}]
    manifest["game"]["replay_viewer"] = {"bundle": "viewer"}
    manifest_path.write_text(json.dumps(manifest))
    (manifest_path.parent / "reporter.wasm").write_bytes(b"wasm-before")
    viewer = manifest_path.parent / "viewer"
    viewer.mkdir()
    (viewer / "index.html").write_text("before")
    (viewer / "asset.js").write_text("asset")
    monkeypatch.setattr("coworld.upload._local_image_client_hash", lambda image: "sha256:runtime")
    before = _certification_cache_key(manifest_path)
    assert _certification_cache_key(manifest_path) == before

    if mutation == "wasm":
        (manifest_path.parent / "reporter.wasm").write_bytes(b"wasm-after")
    elif mutation == "viewer":
        (viewer / "index.html").write_text("after")
    elif mutation == "add":
        (viewer / "new.js").write_text("asset")
    elif mutation == "rename":
        (viewer / "asset.js").rename(viewer / "renamed.js")
    else:
        (viewer / "asset.js").unlink()

    assert _certification_cache_key(manifest_path) != before


@pytest.mark.parametrize("mutation_stage", ["certification", "submission", "cache-hit"])
def test_upload_coworld_submits_certified_payload_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation_stage: str
) -> None:
    manifest_path = _write_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    manifest["game"]["replay_viewer"] = {"bundle": "viewer"}
    manifest_path.write_text(json.dumps(manifest))
    viewer = manifest_path.parent / "viewer"
    viewer.mkdir()
    (viewer / "index.html").write_bytes(b"certified")
    certification_bytes: list[bytes] = []
    submitted_bytes: list[bytes] = []
    client = _FakeCoworldUploadClient()

    def certify(path: Path, *, workspace: Path, timeout_seconds: float) -> None:
        certification_bytes.append((path.parent / "viewer/index.html").read_bytes())
        if mutation_stage == "certification":
            (viewer / "index.html").write_bytes(b"changed")

    def submit_viewer(client: object, manifest: dict[str, object], package_root: Path) -> dict[str, object]:
        submitted_bytes.append((package_root / "viewer/index.html").read_bytes())
        return manifest

    def image_upload(client: object, manifest: dict[str, object]) -> dict[str, object]:
        if mutation_stage == "submission" or (mutation_stage == "cache-hit" and submitted_bytes):
            (viewer / "index.html").write_bytes(b"changed")
        return manifest

    monkeypatch.setattr("coworld.upload.certify_coworld", certify)
    monkeypatch.setattr("coworld.upload._local_image_client_hash", lambda image: "sha256:runtime")
    monkeypatch.setattr("coworld.upload._manifest_with_softmax_image_ids", image_upload)
    monkeypatch.setattr("coworld.upload._submit_replay_viewer_bundle", submit_viewer)
    monkeypatch.setattr(CoworldUploadClient, "from_login", classmethod(lambda cls, *, server_url: client))
    upload_coworld(manifest_path, server="http://localhost:3002/api")
    if mutation_stage == "cache-hit":
        upload_coworld(manifest_path, server="http://localhost:3002/api")
    assert certification_bytes == [b"certified"]
    assert submitted_bytes == [b"certified"] * (2 if mutation_stage == "cache-hit" else 1)
    upload_coworld(manifest_path, server="http://localhost:3002/api")
    assert certification_bytes == [b"certified", b"changed"]
    assert submitted_bytes[-1] == b"changed"


def test_upload_snapshot_payload_hashes_match_http_readback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, httpserver: HTTPServer
) -> None:
    manifest_path = _write_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text())
    wasm_bytes = b"\x00asm-certified"
    attributes = {
        "purpose": "Summarize the episode",
        "world": "softmax:reporter@0.1.0",
        "outputs": [{"name": "summary", "type": "text", "description": "Episode summary"}],
    }
    manifest["reporter"] = [{"wasm": "reporter.wasm", "id": "recap", "attributes": attributes}]
    manifest["game"]["replay_viewer"] = {"bundle": "viewer"}
    manifest_path.write_text(json.dumps(manifest))
    wasm_path = manifest_path.parent / "reporter.wasm"
    wasm_path.write_bytes(wasm_bytes)
    viewer = manifest_path.parent / "viewer"
    viewer.mkdir()
    (viewer / "index.html").write_bytes(b"certified-viewer")
    certified: list[bytes] = []
    received: dict[str, bytes] = {}

    def certify(path: Path, *, workspace: Path, timeout_seconds: float) -> None:
        certified.append((path.parent / "reporter.wasm").read_bytes())

    def submit_images(client: object, data: dict[str, object]) -> dict[str, object]:
        wasm_path.write_bytes(b"changed-wasm")
        (viewer / "index.html").write_bytes(b"changed-viewer")
        return data

    def receive_wasm(request: Request) -> Response:
        received["wasm"] = request.data
        return Response(status=200)

    def receive_viewer(request: Request) -> Response:
        received["viewer"] = request.data
        return Response(status=200)

    def request_viewer(request: Request) -> Response:
        data = json.loads(request.data)
        received["viewer_hash"] = data["content_hash"].encode()
        return Response(
            json.dumps({"bundle": f"sha256:{data['content_hash']}", "upload_url": httpserver.url_for("/viewer")})
        )

    def complete_viewer(request: Request) -> Response:
        data = json.loads(request.data)
        assert data["content_hash"] == hashlib.sha256(received["viewer"]).hexdigest()
        return Response(json.dumps({"bundle": f"sha256:{data['content_hash']}", "status": "ready"}))

    monkeypatch.setattr("coworld.upload.certify_coworld", certify)
    monkeypatch.setattr("coworld.upload._local_image_client_hash", lambda image: "sha256:runtime")
    monkeypatch.setattr("coworld.upload._manifest_with_softmax_image_ids", submit_images)
    prefix = "/observatory/v2"
    httpserver.expect_request("/observatory/whoami").respond_with_json({"owner_user_id": "owner"})
    httpserver.expect_request(f"{prefix}/reporters/register").respond_with_json(
        {"id": "rptr_test", "name": "unit-test-game-recap", "user_id": "owner", "created": True}
    )
    wasm_hash = hashlib.sha256(wasm_bytes).hexdigest()
    httpserver.expect_request(
        f"{prefix}/reporters/upload",
        json={
            "name": "unit-test-game-recap",
            "content_hash": wasm_hash,
            "size_bytes": len(wasm_bytes),
            "attributes": attributes,
        },
    ).respond_with_json({"upload_url": httpserver.url_for("/wasm")})
    httpserver.expect_request("/wasm", method="PUT").respond_with_handler(receive_wasm)
    httpserver.expect_request(f"{prefix}/reporters/upload/complete").respond_with_json(
        {"version": {"id": "rptr_test", "name": "unit-test-game-recap", "version": 1, "content_hash": wasm_hash}}
    )
    httpserver.expect_request(f"{prefix}/coworlds/replay-viewer-bundles/upload").respond_with_handler(request_viewer)
    httpserver.expect_request("/viewer", method="PUT").respond_with_handler(receive_viewer)
    httpserver.expect_request(f"{prefix}/coworlds/replay-viewer-bundles/upload/complete").respond_with_handler(
        complete_viewer
    )
    httpserver.expect_request(f"{prefix}/coworlds/upload").respond_with_json(
        _FakeCoworldUploadClient().upload_manifest(manifest).model_dump()
    )

    upload_coworld(manifest_path, server=httpserver.url_for(""))

    assert certified == [wasm_bytes]
    assert received["wasm"] == wasm_bytes
    assert received["viewer_hash"].decode() == hashlib.sha256(received["viewer"]).hexdigest()
    with zipfile.ZipFile(io.BytesIO(received["viewer"])) as archive:
        assert archive.read("index.html") == b"certified-viewer"
    assert wasm_path.read_bytes() == b"changed-wasm"
    assert (viewer / "index.html").read_bytes() == b"changed-viewer"


def test_certification_snapshot_rejects_player_symlink(tmp_path: Path) -> None:
    manifest_path = _write_manifest(tmp_path)
    manifest = _manifest_with_player_file("public.ecr.aws/softmax/coworld@sha256:public-digest", "unused")
    cast(list[dict[str, object]], manifest["player"])[0]["file"] = "player"
    manifest_path.write_text(json.dumps(manifest))
    target = manifest_path.parent / "policy.py"
    target.write_bytes(b"player")
    (manifest_path.parent / "player").symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        with _certification_snapshot(manifest_path):
            pass


@pytest.mark.parametrize("directory", [False, True])
def test_certification_snapshot_rejects_oversized_players_before_copying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, directory: bool
) -> None:
    manifest = _manifest_with_player_file("public.ecr.aws/softmax/coworld@sha256:public-digest", "unused")
    cast(list[dict[str, object]], manifest["player"])[0]["file"] = "player"
    manifest_path = _write_manifest(tmp_path, manifest)
    source = manifest_path.parent / "player"
    if directory:
        source.mkdir()
        (source / "one.py").write_bytes(b"a" * 600)
        (source / "two.py").write_bytes(b"a" * 600)
    else:
        source.write_bytes(b"a" * 1200)
    monkeypatch.setattr("coworld.player_files.PLAYER_FILE_MAX_BYTES", 1000)
    monkeypatch.setattr(
        "coworld.upload.tempfile.TemporaryDirectory",
        lambda **kwargs: pytest.fail("allocated snapshot before checking player size"),
    )
    with pytest.raises(ValueError, match="size limit"):
        with _certification_snapshot(manifest_path):
            pytest.fail("accepted oversized player")
    with pytest.raises(ValueError, match="size limit"):
        player_file_bytes(source)


def test_external_model_upload_registers_private_route_and_prints_no_key(monkeypatch):
    captured = {}
    monkeypatch.setenv("CONTRIBUTOR_KEY", "private-endpoint-key")
    monkeypatch.setattr("coworld.cli.update_agent_guidance", lambda _: None)
    monkeypatch.setattr("coworld.cli.upload_policy_cmd", lambda *args, **kwargs: captured.update(kwargs))
    monkeypatch.setattr("coworld.cli.print_feed_hello_pointer", lambda *, server: None)
    result = CliRunner().invoke(
        app,
        [
            "upload-policy",
            "my-player:local",
            "--name",
            "E17",
            "--use-llm",
            "--llm-model",
            "E17",
            "--llm-endpoint",
            "https://contributor.example/api/v1",
            "--llm-api-key-env",
            "CONTRIBUTOR_KEY",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "private-endpoint-key" not in result.output
    env = captured["secret_env"]
    route = ExternalLlmRoute.model_validate_json(env[EXTERNAL_LLM_SECRET_KEY])
    assert route.api_key.get_secret_value() == "private-endpoint-key"
    assert route.model == "E17"
    assert env["COWORLD_LLM_MODEL"] == route.model_id
