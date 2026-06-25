import hashlib
import io
import json
import os
import re
import subprocess
import tarfile
from pathlib import Path
from typing import BinaryIO, cast

import pytest
from click import unstyle
from pytest_httpserver import HTTPServer
from typer.testing import CliRunner

from coworld.cli import app
from coworld.upload import (
    _REGISTRY_UPLOAD_TIMEOUT,
    ContainerImageResponse,
    CoworldUploadClient,
    _docker_archive_client_hash,
    _load_current_token,
    _local_image_client_hash,
    _local_image_tag,
    _manifest_image_fields,
    _manifest_with_local_images,
    _manifest_with_softmax_image_ids,
    _push_archive_to_registry,
    upload_coworld,
)


@pytest.fixture(autouse=True)
def _fake_softmax_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("softmax.auth.load_current_token", lambda *, server: "token")
    monkeypatch.setattr("softmax.auth.load_user_token", lambda *, server: "token")


def test_upload_client_token_lookup_uses_server_url(monkeypatch: pytest.MonkeyPatch) -> None:
    requested_servers: list[str] = []

    def fake_load_current_token(*, server: str) -> str:
        requested_servers.append(server)
        return "token"

    monkeypatch.setattr("softmax.auth.load_current_token", fake_load_current_token)

    assert _load_current_token(server_url="http://localhost:3102/api") == "token"
    assert requested_servers == ["http://localhost:3102/api"]


def test_upload_client_auth_error_mentions_server_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("softmax.auth.load_current_token", lambda *, server: None)

    with pytest.raises(RuntimeError) as exc_info:
        CoworldUploadClient.from_login(server_url="http://localhost:3102/api")

    assert "uv run softmax login --server http://localhost:3102/api" in str(exc_info.value)


def test_next_version_command_bumps_canonical_patch(httpserver: HTTPServer) -> None:
    coworld_id = "cow_00000000-0000-0000-0000-000000000010"
    manifest = _manifest()
    httpserver.expect_request(
        "/observatory/v2/coworlds",
        method="GET",
        query_string="limit=200&offset=0",
    ).respond_with_json(
        [
            _coworld_entry(coworld_id, manifest, name="cogs_vs_clips", version="0.1.22", canonical=True),
            _coworld_entry(
                "cow_00000000-0000-0000-0000-000000000011",
                manifest,
                name="cogs_vs_clips",
                version="0.1.21",
                canonical=False,
            ),
        ]
    )

    result = CliRunner().invoke(app, ["next-version", "cogs-vs-clips", "--server", httpserver.url_for("")])

    assert result.exit_code == 0, result.output
    assert result.output == "0.1.23\n"


def test_next_version_command_fails_without_canonical_coworld(httpserver: HTTPServer) -> None:
    httpserver.expect_request(
        "/observatory/v2/coworlds",
        method="GET",
        query_string="limit=200&offset=0",
    ).respond_with_json([])

    result = CliRunner().invoke(app, ["next-version", "crewrift", "--server", httpserver.url_for("")], color=False)

    assert result.exit_code == 1
    assert "Canonical Coworld not found: crewrift" in result.output


def test_upload_coworld_rejects_mutable_registry_image_refs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _manifest()
    cast(list[dict[str, object]], manifest["reporter"])[0]["image"] = "ghcr.io/metta-ai/reporters-default:latest"
    manifest_path = _write_manifest(tmp_path, manifest)
    monkeypatch.setattr("coworld.upload.certify_coworld", lambda *_args, **_kwargs: pytest.fail("certified manifest"))

    with pytest.raises(RuntimeError) as exc_info:
        upload_coworld(manifest_path)

    message = str(exc_info.value)
    assert "ghcr.io/metta-ai/reporters-default:latest" in message
    assert "resolve-and-upload" in message


def test_upload_coworld_posts_standalone_manifest(
    tmp_path: Path,
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _write_manifest(tmp_path)
    certification_calls: list[tuple[Path, float]] = []
    image_id = "img_00000000-0000-0000-0000-000000000010"
    grader_image_id = "img_00000000-0000-0000-0000-000000000011"
    softmax_image_uri = "123456789012.dkr.ecr.us-east-1.amazonaws.com/coworld/user/unit-test-runtime@sha256:digest"
    pushed_images: list[tuple[str, str]] = []
    hashed_images: list[str] = []

    def fake_certify(path: Path, *, timeout_seconds: float) -> None:
        certification_calls.append((path, timeout_seconds))
        manifest = json.loads(path.read_text(encoding="utf-8"))
        assert manifest["game"]["runnable"]["image"] == "unit-test-runtime:latest"
        assert manifest["player"][0]["image"] == "unit-test-runtime:latest"
        assert manifest["grader"][0]["image"] == "ghcr.io/metta-ai/graders-default@sha256:graderdigest"

    def fake_hash(image: str) -> str:
        hashed_images.append(image)
        return "sha256:client-hash"

    monkeypatch.setattr("coworld.upload.certify_coworld", fake_certify)
    monkeypatch.setattr("coworld.upload.assert_docker_image_reachable", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("coworld.upload._local_image_client_hash", fake_hash)
    monkeypatch.setattr(
        "coworld.upload._push_container_image",
        lambda source_image, push_info: pushed_images.append((source_image, push_info.image_uri)),
    )
    httpserver.expect_request(
        "/observatory/v2/container_images/upload",
        method="POST",
        headers={"Authorization": "Bearer token"},
        json={"name": "graders-default", "client_hash": "sha256:client-hash"},
    ).respond_with_json(
        {
            "image": {
                "id": grader_image_id,
                "name": "graders-default",
                "version": 1,
                "client_hash": "sha256:client-hash",
                "status": "ready",
                "image_uri": "123456789012.dkr.ecr.us-east-1.amazonaws.com/coworld/user/graders-default@sha256:digest",
                "image_digest": "sha256:digest",
            },
            "pre_signed_info": None,
        }
    )
    httpserver.expect_request(
        "/observatory/v2/container_images/upload",
        method="POST",
        headers={"Authorization": "Bearer token"},
        json={"name": "unit-test-runtime", "client_hash": "sha256:client-hash"},
    ).respond_with_json(
        {
            "image": {
                "id": image_id,
                "name": "unit-test-runtime",
                "version": 1,
                "client_hash": "sha256:client-hash",
                "status": "pending",
            },
            "pre_signed_info": {
                "kind": "ecr",
                "region": "us-east-1",
                "registry": "123456789012.dkr.ecr.us-east-1.amazonaws.com",
                "repository": "coworld/user/unit-test-runtime",
                "tag": "v1",
                "image_uri": "123456789012.dkr.ecr.us-east-1.amazonaws.com/coworld/user/unit-test-runtime:v1",
                "expires_at": "2026-05-06T22:00:00Z",
                "authorization_token": "QVdTOnBhc3N3b3Jk",
            },
        }
    )
    httpserver.expect_request(
        "/observatory/v2/container_images/upload/complete",
        method="POST",
        headers={"Authorization": "Bearer token"},
        json={"id": image_id},
    ).respond_with_json(
        {
            "id": image_id,
            "name": "unit-test-runtime",
            "version": 1,
            "client_hash": "sha256:client-hash",
            "status": "ready",
            "image_uri": softmax_image_uri,
            "image_digest": "sha256:digest",
        }
    )
    httpserver.expect_request(
        "/observatory/v2/coworlds/upload",
        method="POST",
        headers={"Authorization": "Bearer token"},
    ).respond_with_json(
        {
            "id": "cow_00000000-0000-0000-0000-000000000001",
            "name": "unit-test-game",
            "version": "0.1.0",
            "manifest": _manifest_with_image(image_id),
            "manifest_hash": "sha256:manifest-hash",
            "size_bytes": 1234,
            "canonical": True,
        }
    )

    result = upload_coworld(
        manifest_path,
        server=httpserver.url_for(""),
    )

    assert result.name == "unit-test-game"
    assert result.version == "0.1.0"
    assert result.id == "cow_00000000-0000-0000-0000-000000000001"
    assert result.manifest_hash == "sha256:manifest-hash"
    assert result.canonical is True
    assert certification_calls[0][0] == manifest_path.resolve()
    assert certification_calls[0][1] == 60.0
    assert hashed_images == ["ghcr.io/metta-ai/graders-default@sha256:graderdigest", "unit-test-runtime:latest"]
    assert pushed_images == [
        (
            "unit-test-runtime:latest",
            "123456789012.dkr.ecr.us-east-1.amazonaws.com/coworld/user/unit-test-runtime:v1",
        ),
    ]
    upload_req = next(req for req, _ in httpserver.log if req.path == "/observatory/v2/coworlds/upload")
    uploaded_manifest = upload_req.get_json()["manifest"]
    assert uploaded_manifest["game"]["runnable"]["image"] == image_id
    assert uploaded_manifest["player"][0]["image"] == image_id
    assert uploaded_manifest["grader"][0]["image"] == grader_image_id
    assert uploaded_manifest["game"]["protocols"]["player"] == {
        "type": "uri",
        "value": "https://example.com/player_protocol_spec.md",
    }
    assert uploaded_manifest["game"]["protocols"]["global"] == {
        "type": "uri",
        "value": "https://example.com/global_protocol_spec.md",
    }


def test_upload_coworld_command_certifies_before_uploading(
    tmp_path: Path,
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _write_manifest(tmp_path)
    certification_calls: list[tuple[Path, float]] = []
    image_id = "img_00000000-0000-0000-0000-000000000020"
    grader_image_id = "img_00000000-0000-0000-0000-000000000021"
    softmax_image_uri = "123456789012.dkr.ecr.us-east-1.amazonaws.com/coworld/user/unit-test-runtime@sha256:digest"

    monkeypatch.setattr(
        "coworld.upload.certify_coworld",
        lambda manifest_path, *, timeout_seconds: certification_calls.append((manifest_path, timeout_seconds)),
    )
    monkeypatch.setattr("coworld.upload.assert_docker_image_reachable", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("coworld.upload._local_image_client_hash", lambda image: "sha256:client-hash")
    monkeypatch.setattr("coworld.upload._push_container_image", lambda source_image, push_info: None)
    httpserver.expect_request(
        "/observatory/v2/container_images/upload",
        method="POST",
        json={"name": "graders-default", "client_hash": "sha256:client-hash"},
    ).respond_with_json(
        {
            "image": {
                "id": grader_image_id,
                "name": "graders-default",
                "version": 1,
                "client_hash": "sha256:client-hash",
                "status": "ready",
                "image_uri": "123456789012.dkr.ecr.us-east-1.amazonaws.com/coworld/user/graders-default@sha256:digest",
                "image_digest": "sha256:digest",
            },
            "pre_signed_info": None,
        }
    )
    httpserver.expect_request("/observatory/v2/container_images/upload", method="POST").respond_with_json(
        {
            "image": {
                "id": image_id,
                "name": "unit-test-runtime",
                "version": 1,
                "client_hash": "sha256:client-hash",
                "status": "ready",
                "image_uri": softmax_image_uri,
                "image_digest": "sha256:digest",
            },
            "pre_signed_info": None,
        }
    )
    httpserver.expect_request("/observatory/v2/coworlds/upload", method="POST").respond_with_json(
        {
            "id": "cow_00000000-0000-0000-0000-000000000002",
            "name": "unit-test-game",
            "version": "0.1.0",
            "manifest": _manifest_with_image(image_id),
            "manifest_hash": "sha256:manifest-hash",
            "size_bytes": 1234,
            "canonical": True,
        }
    )

    result = CliRunner().invoke(
        app,
        [
            "upload-coworld",
            str(manifest_path),
            "--server",
            httpserver.url_for(""),
            "--no-wait-hosted-smoke",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Upload complete: unit-test-game:0.1.0" in result.output
    assert "Coworld: cow_00000000-0000-0000-0000-000000000002" in result.output
    assert "Manifest hash: sha256:manifest-hash" in result.output
    assert "Canonical: yes" in result.output
    assert certification_calls == [(manifest_path.resolve(), 60.0)]


def test_upload_coworld_command_rejects_partial_options_without_base_manifest(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        ["upload-coworld", str(_write_manifest(tmp_path)), "--version", "0.2.0"],
        color=False,
    )

    assert result.exit_code != 0
    assert "--version, --patch, and --image require --from-coworld" in result.output


def test_upload_coworld_command_waits_for_hosted_smoke_success(httpserver: HTTPServer) -> None:
    old_coworld_id = "cow_00000000-0000-0000-0000-000000000013"
    new_coworld_id = "cow_00000000-0000-0000-0000-000000000014"
    image_id = "img_00000000-0000-0000-0000-000000000099"
    manifest = _manifest_with_image(image_id)

    httpserver.expect_request(
        "/observatory/v2/coworlds",
        method="GET",
        query_string="limit=200&offset=0",
    ).respond_with_json([_coworld_entry(old_coworld_id, manifest, version="0.1.0", canonical=True)])
    httpserver.expect_request("/observatory/v2/coworlds/upload", method="POST").respond_with_json(
        _coworld_entry(new_coworld_id, manifest, version="0.2.0", canonical=False)
    )
    httpserver.expect_request(
        "/observatory/v2/episode-requests",
        method="GET",
        query_string="limit=1000&offset=0",
    ).respond_with_json(
        {
            "entries": [
                _episode_request("ereq_00000000-0000-0000-0000-000000000001", new_coworld_id, "completed"),
                _episode_request("ereq_00000000-0000-0000-0000-000000000002", new_coworld_id, "completed"),
            ]
        }
    )
    httpserver.expect_request(
        f"/observatory/v2/coworlds/{new_coworld_id}",
        method="GET",
    ).respond_with_json(_coworld_entry(new_coworld_id, manifest, version="0.2.0", canonical=True))

    result = CliRunner().invoke(
        app,
        [
            "upload-coworld",
            "--from-coworld",
            old_coworld_id,
            "--version",
            "0.2.0",
            "--server",
            httpserver.url_for(""),
            "--hosted-smoke-timeout-seconds",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Hosted smoke certification: passed" in result.output
    assert "ereq_00000000-0000-0000-0000-000000000001" in result.output
    assert "Canonical: yes" in result.output


def test_upload_coworld_command_fails_on_hosted_smoke_failure(httpserver: HTTPServer) -> None:
    old_coworld_id = "cow_00000000-0000-0000-0000-000000000013"
    new_coworld_id = "cow_00000000-0000-0000-0000-000000000014"
    image_id = "img_00000000-0000-0000-0000-000000000099"
    manifest = _manifest_with_image(image_id)

    httpserver.expect_request(
        "/observatory/v2/coworlds",
        method="GET",
        query_string="limit=200&offset=0",
    ).respond_with_json([_coworld_entry(old_coworld_id, manifest, version="0.1.0", canonical=True)])
    httpserver.expect_request("/observatory/v2/coworlds/upload", method="POST").respond_with_json(
        _coworld_entry(new_coworld_id, manifest, version="0.2.0", canonical=False)
    )
    httpserver.expect_request(
        "/observatory/v2/episode-requests",
        method="GET",
        query_string="limit=1000&offset=0",
    ).respond_with_json(
        {
            "entries": [
                _episode_request(
                    "ereq_00000000-0000-0000-0000-000000000003",
                    new_coworld_id,
                    "failed",
                    error="image pull failed",
                )
            ]
        }
    )

    result = CliRunner().invoke(
        app,
        [
            "upload-coworld",
            "--from-coworld",
            old_coworld_id,
            "--version",
            "0.2.0",
            "--server",
            httpserver.url_for(""),
            "--hosted-smoke-timeout-seconds",
            "1",
        ],
    )

    assert result.exit_code != 0
    assert "Hosted smoke certification failed" in str(result.exception)
    assert "image pull failed" in str(result.exception)


def test_coworld_status_command_waits_for_hosted_smoke_success(httpserver: HTTPServer) -> None:
    coworld_id = "cow_00000000-0000-0000-0000-000000000014"
    image_id = "img_00000000-0000-0000-0000-000000000099"
    manifest = _manifest_with_image(image_id)

    httpserver.expect_request(
        "/observatory/v2/episode-requests",
        method="GET",
        query_string="limit=1000&offset=0",
    ).respond_with_json(
        {
            "entries": [
                _episode_request("ereq_00000000-0000-0000-0000-000000000001", coworld_id, "completed"),
                _episode_request("ereq_00000000-0000-0000-0000-000000000002", coworld_id, "completed"),
            ]
        }
    )
    httpserver.expect_request(
        f"/observatory/v2/coworlds/{coworld_id}",
        method="GET",
    ).respond_with_json(_coworld_entry(coworld_id, manifest, version="0.2.0", canonical=True))

    result = CliRunner().invoke(
        app,
        [
            "status",
            coworld_id,
            "--server",
            httpserver.url_for(""),
            "--wait-hosted-smoke",
            "--hosted-smoke-timeout-seconds",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Coworld: cow_00000000-0000-0000-0000-000000000014" in result.output
    assert "Hosted smoke certification: passed" in result.output
    assert "ereq_00000000-0000-0000-0000-000000000001" in result.output
    assert "Canonical: yes" in result.output


def test_coworld_status_command_prints_pending_hosted_smoke(httpserver: HTTPServer) -> None:
    coworld_id = "cow_00000000-0000-0000-0000-000000000014"
    image_id = "img_00000000-0000-0000-0000-000000000099"
    manifest = _manifest_with_image(image_id)

    httpserver.expect_request(
        "/observatory/v2/episode-requests",
        method="GET",
        query_string="limit=1000&offset=0",
    ).respond_with_json(
        {"entries": [_episode_request("ereq_00000000-0000-0000-0000-000000000001", coworld_id, "running")]}
    )
    httpserver.expect_request(
        f"/observatory/v2/coworlds/{coworld_id}",
        method="GET",
    ).respond_with_json(_coworld_entry(coworld_id, manifest, version="0.2.0", canonical=False))

    result = CliRunner().invoke(
        app,
        [
            "status",
            coworld_id,
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Hosted smoke certification: pending" in result.output
    assert "running" in result.output
    assert "Canonical: no" in result.output


def test_upload_coworld_from_existing_manifest_applies_patch_without_images(
    tmp_path: Path,
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coworld_id = "cow_00000000-0000-0000-0000-000000000013"
    existing_image_id = "img_00000000-0000-0000-0000-000000000099"
    manifest = _manifest_with_image(existing_image_id)
    patch_path = tmp_path / "manifest_patch.json"
    patch_path.write_text(json.dumps({"game": {"owner": "new-owner@softmax.com"}}), encoding="utf-8")

    monkeypatch.setattr("coworld.upload.certify_coworld", lambda *_args, **_kwargs: pytest.fail("certified manifest"))
    monkeypatch.setattr(
        "coworld.upload._local_image_client_hash",
        lambda image: pytest.fail(f"hashed unchanged image {image}"),
    )
    httpserver.expect_request(
        "/observatory/v2/coworlds",
        method="GET",
        query_string="limit=200&offset=0",
    ).respond_with_json(
        [
            {
                "id": coworld_id,
                "name": "unit-test-game",
                "version": "0.1.0",
                "manifest": manifest,
                "manifest_hash": "sha256:old-manifest-hash",
                "size_bytes": 1234,
                "created_at": "2026-05-08T21:00:00Z",
                "canonical": True,
            }
        ]
    )
    httpserver.expect_request("/observatory/v2/coworlds/upload", method="POST").respond_with_json(
        {
            "id": coworld_id,
            "name": "unit-test-game",
            "version": "0.2.0",
            "manifest": manifest,
            "manifest_hash": "sha256:new-manifest-hash",
            "size_bytes": 1250,
            "canonical": True,
        }
    )

    result = CliRunner().invoke(
        app,
        [
            "upload-coworld",
            "--from-coworld",
            coworld_id,
            "--version",
            "0.2.0",
            "--patch",
            str(patch_path),
            "--server",
            httpserver.url_for(""),
            "--no-wait-hosted-smoke",
        ],
    )

    assert result.exit_code == 0, result.output
    upload_req = next(req for req, _ in httpserver.log if req.path == "/observatory/v2/coworlds/upload")
    uploaded_manifest = upload_req.get_json()["manifest"]
    assert uploaded_manifest["game"]["version"] == "0.2.0"
    assert uploaded_manifest["game"]["owner"] == "new-owner@softmax.com"
    assert uploaded_manifest["game"]["runnable"]["image"] == existing_image_id
    assert uploaded_manifest["player"][0]["image"] == existing_image_id


def test_upload_coworld_from_existing_manifest_updates_one_role_image(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coworld_id = "cow_00000000-0000-0000-0000-000000000014"
    existing_image_id = "img_00000000-0000-0000-0000-000000000099"
    commissioner_image_id = "img_00000000-0000-0000-0000-000000000100"
    manifest = _manifest_with_image(existing_image_id)
    manifest["commissioner"] = [
        {
            "id": "round-robin",
            "name": "Round Robin Commissioner",
            "description": "Default commissioner.",
            "type": "commissioner",
            "image": existing_image_id,
        }
    ]
    hashed_images: list[str] = []

    def fake_hash(image: str) -> str:
        hashed_images.append(image)
        return "sha256:commissioner-hash"

    monkeypatch.setattr("coworld.upload.certify_coworld", lambda *_args, **_kwargs: pytest.fail("certified manifest"))
    monkeypatch.setattr("coworld.upload.assert_docker_image_reachable", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("coworld.upload._local_image_client_hash", fake_hash)
    monkeypatch.setattr("coworld.upload._push_container_image", lambda source_image, push_info: None)
    httpserver.expect_request(
        "/observatory/v2/coworlds",
        method="GET",
        query_string="limit=200&offset=0",
    ).respond_with_json(
        [
            {
                "id": coworld_id,
                "name": "unit-test-game",
                "version": "0.1.0",
                "manifest": manifest,
                "manifest_hash": "sha256:old-manifest-hash",
                "size_bytes": 1234,
                "created_at": "2026-05-08T21:00:00Z",
                "canonical": True,
            }
        ]
    )
    httpserver.expect_request(
        "/observatory/v2/container_images/upload",
        method="POST",
        json={"name": "unit-test-commissioner", "client_hash": "sha256:commissioner-hash"},
    ).respond_with_json(
        {
            "image": {
                "id": commissioner_image_id,
                "name": "unit-test-commissioner",
                "version": 1,
                "client_hash": "sha256:commissioner-hash",
                "status": "ready",
                "image_uri": (
                    "123456789012.dkr.ecr.us-east-1.amazonaws.com/coworld/user/unit-test-commissioner@sha256:digest"
                ),
                "image_digest": "sha256:digest",
            },
            "pre_signed_info": None,
        }
    )
    httpserver.expect_request("/observatory/v2/coworlds/upload", method="POST").respond_with_json(
        {
            "id": coworld_id,
            "name": "unit-test-game",
            "version": "0.2.0",
            "manifest": manifest,
            "manifest_hash": "sha256:new-manifest-hash",
            "size_bytes": 1250,
            "canonical": True,
        }
    )

    result = CliRunner().invoke(
        app,
        [
            "upload-coworld",
            "--from-coworld",
            coworld_id,
            "--version",
            "0.2.0",
            "--image",
            "commissioner.round-robin=unit-test-commissioner:latest",
            "--server",
            httpserver.url_for(""),
            "--no-wait-hosted-smoke",
        ],
    )

    assert result.exit_code == 0, result.output
    assert hashed_images == ["unit-test-commissioner:latest"]
    upload_req = next(req for req, _ in httpserver.log if req.path == "/observatory/v2/coworlds/upload")
    uploaded_manifest = upload_req.get_json()["manifest"]
    assert uploaded_manifest["game"]["runnable"]["image"] == existing_image_id
    assert uploaded_manifest["commissioner"][0]["image"] == commissioner_image_id


def test_patch_commissioner_command_uploads_image_and_patches(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coworld_id = "cow_00000000-0000-0000-0000-000000000015"
    commissioner_image_id = "img_00000000-0000-0000-0000-000000000101"
    source_image = "ghcr.io/metta-ai/commissioners-baseline:latest"
    resolved_image = "ghcr.io/metta-ai/commissioners-baseline@sha256:commissionerdigest"
    hashed_images: list[str] = []
    inspected_images: list[str] = []

    def fake_hash(image: str) -> str:
        hashed_images.append(image)
        return "sha256:commissioner-hash"

    def fake_subprocess_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[:3] == ["docker", "image", "inspect"]:
            inspected_images.append(args[3])
            return subprocess.CompletedProcess(args, 0, stdout="")
        raise AssertionError(f"unexpected subprocess.run: {args}")

    monkeypatch.setattr("coworld.upload.resolve_registry_image_ref", lambda image: resolved_image)
    monkeypatch.setattr("coworld.upload.subprocess.run", fake_subprocess_run)
    monkeypatch.setattr("coworld.upload.assert_docker_image_reachable", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("coworld.upload._local_image_client_hash", fake_hash)
    monkeypatch.setattr("coworld.upload._push_container_image", lambda source_image, push_info: None)
    httpserver.expect_request(
        "/observatory/v2/container_images/upload",
        method="POST",
        json={"name": "commissioners-baseline", "client_hash": "sha256:commissioner-hash"},
    ).respond_with_json(
        {
            "image": {
                "id": commissioner_image_id,
                "name": "commissioners-baseline",
                "version": 1,
                "client_hash": "sha256:commissioner-hash",
                "status": "ready",
                "image_uri": (
                    "123456789012.dkr.ecr.us-east-1.amazonaws.com/coworld/user/commissioners-baseline@sha256:digest"
                ),
                "image_digest": "sha256:digest",
            },
            "pre_signed_info": None,
        }
    )
    httpserver.expect_request(
        "/observatory/v2/coworlds/patch-commissioner",
        method="POST",
        json={
            "coworld_name": "crewrift",
            "container_image_id": commissioner_image_id,
            "runnable_id": "crewrift-commissioner",
        },
    ).respond_with_json(
        {
            **_coworld_entry(coworld_id, _manifest(), name="crewrift", version="0.1.23", canonical=True),
            "created_at": "2026-05-08T21:00:00Z",
        }
    )

    result = CliRunner().invoke(
        app,
        [
            "patch-commissioner",
            "crewrift",
            source_image,
            "--runnable-id",
            "crewrift-commissioner",
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code == 0, result.output
    assert inspected_images == [resolved_image]
    assert hashed_images == [resolved_image]
    assert f"Resolved image: {resolved_image}" in result.output
    assert "Patched commissioner: crewrift:0.1.23" in result.output
    assert f"Commissioner image: {commissioner_image_id}" in result.output
    assert "Canonical: yes" in result.output


def test_manifest_with_softmax_image_ids_keeps_existing_image_ids() -> None:
    manifest = _manifest_with_image("img_00000000-0000-0000-0000-000000000099")
    uploaded = _manifest_with_softmax_image_ids(cast(CoworldUploadClient, object()), manifest)

    assert uploaded["game"]["runnable"]["image"] == "img_00000000-0000-0000-0000-000000000099"


def test_manifest_with_softmax_image_ids_uploads_local_img_prefixed_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _manifest_with_image("img_game:latest")
    uploaded_ids: list[str] = []

    def fake_upload(_client: CoworldUploadClient, image: str) -> ContainerImageResponse:
        uploaded_ids.append(image)
        return ContainerImageResponse(
            id="img_00000000-0000-0000-0000-000000000099",
            name="img_game",
            version=1,
            status="ready",
        )

    monkeypatch.setattr("coworld.upload._upload_container_image", fake_upload)

    uploaded = _manifest_with_softmax_image_ids(cast(CoworldUploadClient, object()), manifest)

    assert uploaded_ids == ["img_game:latest"]
    assert uploaded["game"]["runnable"]["image"] == "img_00000000-0000-0000-0000-000000000099"


def test_upload_coworld_surfaces_server_error_detail(
    tmp_path: Path,
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _write_manifest(tmp_path)
    image_id = "img_00000000-0000-0000-0000-000000000040"
    softmax_image_uri = "123456789012.dkr.ecr.us-east-1.amazonaws.com/coworld/user/unit-test-runtime@sha256:digest"

    monkeypatch.setattr("coworld.upload._load_current_token", lambda *, server_url: "token")
    monkeypatch.setattr("coworld.upload.certify_coworld", lambda manifest_path, *, timeout_seconds: None)
    monkeypatch.setattr("coworld.upload.assert_docker_image_reachable", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("coworld.upload._local_image_client_hash", lambda image: "sha256:client-hash")
    monkeypatch.setattr("coworld.upload._push_container_image", lambda source_image, push_info: None)
    httpserver.expect_request("/observatory/v2/container_images/upload", method="POST").respond_with_json(
        {
            "image": {
                "id": image_id,
                "name": "unit-test-runtime",
                "version": 1,
                "client_hash": "sha256:client-hash",
                "status": "ready",
                "image_uri": softmax_image_uri,
                "image_digest": "sha256:digest",
            },
            "pre_signed_info": None,
        }
    )
    httpserver.expect_request("/observatory/v2/coworlds/upload", method="POST").respond_with_json(
        {"detail": "variant 'default' references unknown image"},
        status=422,
    )

    with pytest.raises(RuntimeError) as excinfo:
        upload_coworld(manifest_path, server=httpserver.url_for(""))

    message = str(excinfo.value)
    assert "422" in message
    assert "variant 'default' references unknown image" in message


def test_upload_policy_command_creates_docker_image_policy(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    softmax_image_uri = "123456789012.dkr.ecr.us-east-1.amazonaws.com/coworld/user/unit-test-policy@sha256:digest"

    monkeypatch.setattr("softmax.auth.load_current_token", lambda *, server: "player-token")
    monkeypatch.setattr("softmax.auth.load_user_token", lambda *, server: pytest.fail("used user token"))
    monkeypatch.setattr("coworld.upload.assert_docker_image_reachable", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("coworld.upload._local_image_client_hash", lambda image: "sha256:client-hash")
    monkeypatch.setattr("coworld.upload._push_container_image", lambda source_image, push_info: None)
    httpserver.expect_request(
        "/observatory/v2/container_images/upload",
        method="POST",
        headers={"Authorization": "Bearer player-token"},
        json={"name": "unit-test-policy", "client_hash": "sha256:client-hash"},
    ).respond_with_json(
        {
            "image": {
                "id": "img_00000000-0000-0000-0000-000000000030",
                "name": "unit-test-policy",
                "version": 1,
                "client_hash": "sha256:client-hash",
                "status": "ready",
                "image_uri": softmax_image_uri,
                "image_digest": "sha256:digest",
            },
            "pre_signed_info": None,
        }
    )
    httpserver.expect_request(
        "/observatory/stats/policies/docker-img/complete",
        method="POST",
        headers={"Authorization": "Bearer player-token"},
        json={
            "name": "paintbot",
            "container_image_id": "img_00000000-0000-0000-0000-000000000030",
        },
    ).respond_with_json(
        {
            "id": "00000000-0000-0000-0000-000000000031",
            "name": "paintbot",
            "version": 1,
        }
    )

    result = CliRunner().invoke(
        app,
        [
            "upload-policy",
            "unit-test-policy:latest",
            "--name",
            "paintbot",
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Upload complete: paintbot:v1" in result.output


def test_upload_policy_command_sends_policy_secrets(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    softmax_image_uri = "123456789012.dkr.ecr.us-east-1.amazonaws.com/coworld/user/unit-test-policy@sha256:digest"

    monkeypatch.setattr("coworld.upload.assert_docker_image_reachable", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("coworld.upload._local_image_client_hash", lambda image: "sha256:client-hash")
    monkeypatch.setattr("coworld.upload._push_container_image", lambda source_image, push_info: None)
    httpserver.expect_request(
        "/observatory/v2/container_images/upload",
        method="POST",
        headers={"Authorization": "Bearer token"},
        json={"name": "unit-test-policy", "client_hash": "sha256:client-hash"},
    ).respond_with_json(
        {
            "image": {
                "id": "img_00000000-0000-0000-0000-000000000030",
                "name": "unit-test-policy",
                "version": 1,
                "client_hash": "sha256:client-hash",
                "status": "ready",
                "image_uri": softmax_image_uri,
                "image_digest": "sha256:digest",
            },
            "pre_signed_info": None,
        }
    )
    # New flow: secret_env is uploaded first to /stats/policy-secret-envs.
    httpserver.expect_request(
        "/observatory/stats/policy-secret-envs",
        method="POST",
        headers={"Authorization": "Bearer token"},
        json={
            "policy_secret_env": {
                "USE_BEDROCK": "true",
                "BEDROCK_MODEL": "us.amazon.nova-micro-v1:0",
                "ANTHROPIC_API_KEY": "sk-ant-test",
            },
        },
    ).respond_with_json({"id": "00000000-0000-0000-0000-000000000040"})
    # Then docker-img/complete carries policy_secret_env_id, NOT policy_secret_env.
    httpserver.expect_request(
        "/observatory/stats/policies/docker-img/complete",
        method="POST",
        headers={"Authorization": "Bearer token"},
        json={
            "name": "paintbot",
            "container_image_id": "img_00000000-0000-0000-0000-000000000030",
            "policy_secret_env_id": "00000000-0000-0000-0000-000000000040",
        },
    ).respond_with_json(
        {
            "id": "00000000-0000-0000-0000-000000000031",
            "name": "paintbot",
            "version": 1,
        }
    )

    result = CliRunner().invoke(
        app,
        [
            "upload-policy",
            "unit-test-policy:latest",
            "--name",
            "paintbot",
            "--server",
            httpserver.url_for(""),
            "--use-bedrock",
            "--bedrock-model",
            "us.amazon.nova-micro-v1:0",
            "--secret-env",
            "ANTHROPIC_API_KEY=sk-ant-test",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Upload complete: paintbot:v1" in result.output


def test_upload_policy_command_sends_tags(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    softmax_image_uri = "123456789012.dkr.ecr.us-east-1.amazonaws.com/coworld/user/unit-test-policy@sha256:digest"

    monkeypatch.setattr("coworld.upload.assert_docker_image_reachable", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("coworld.upload._local_image_client_hash", lambda image: "sha256:client-hash")
    monkeypatch.setattr("coworld.upload._push_container_image", lambda source_image, push_info: None)
    httpserver.expect_request(
        "/observatory/v2/container_images/upload",
        method="POST",
        headers={"Authorization": "Bearer token"},
        json={"name": "unit-test-policy", "client_hash": "sha256:client-hash"},
    ).respond_with_json(
        {
            "image": {
                "id": "img_00000000-0000-0000-0000-000000000030",
                "name": "unit-test-policy",
                "version": 1,
                "client_hash": "sha256:client-hash",
                "status": "ready",
                "image_uri": softmax_image_uri,
                "image_digest": "sha256:digest",
            },
            "pre_signed_info": None,
        }
    )
    httpserver.expect_request(
        "/observatory/stats/policies/docker-img/complete",
        method="POST",
        headers={"Authorization": "Bearer token"},
        json={
            "name": "paintbot",
            "container_image_id": "img_00000000-0000-0000-0000-000000000030",
            "tags": {"purpose": "test", "experiment": "lr-sweep"},
        },
    ).respond_with_json(
        {
            "id": "00000000-0000-0000-0000-000000000031",
            "name": "paintbot",
            "version": 1,
        }
    )

    result = CliRunner().invoke(
        app,
        [
            "upload-policy",
            "unit-test-policy:latest",
            "--name",
            "paintbot",
            "--server",
            httpserver.url_for(""),
            "--tag",
            "purpose=test",
            "--tag",
            "experiment=lr-sweep",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Upload complete: paintbot:v1" in result.output


def test_upload_policy_command_requires_bedrock_for_bedrock_model() -> None:
    result = CliRunner().invoke(
        app,
        [
            "upload-policy",
            "unit-test-policy:latest",
            "--name",
            "paintbot",
            "--bedrock-model",
            "us.amazon.nova-micro-v1:0",
        ],
    )

    assert result.exit_code != 0
    assert "--bedrock-model requires --use-bedrock" in unstyle(result.output)


def test_upload_policy_command_rejects_run_as_single_quoted_string() -> None:
    result = CliRunner().invoke(
        app,
        [
            "upload-policy",
            "unit-test-policy:latest",
            "--name",
            "paintbot",
            "--run",
            "node dist-server/foo.js",
        ],
    )

    assert result.exit_code != 0
    # Rich renders the error inside a bordered box and wraps long lines; flatten the borders and
    # whitespace before asserting on the suggested per-token form.
    flattened = " ".join(re.sub(r"[│╭╮╰╯─]", " ", unstyle(result.output)).split())
    assert "--run node --run dist-server/foo.js" in flattened


def test_coworld_list_command_prints_json(httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch) -> None:
    httpserver.expect_request(
        "/observatory/v2/coworlds",
        method="GET",
        headers={"Authorization": "Bearer token"},
        query_string="limit=50&offset=0",
    ).respond_with_json(
        [
            {
                "id": "cow_00000000-0000-0000-0000-000000000001",
                "name": "unit-test-game",
                "version": "0.1.0",
                "manifest": _manifest_with_image("img_00000000-0000-0000-0000-000000000010"),
                "manifest_hash": "sha256:manifest-hash",
                "size_bytes": 1234,
                "created_at": "2026-05-08T21:00:00Z",
                "canonical": True,
            }
        ]
    )
    result = CliRunner().invoke(
        app,
        [
            "list",
            "--server",
            httpserver.url_for(""),
            "--limit",
            "50",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)[0]["id"] == "cow_00000000-0000-0000-0000-000000000001"


def test_hosted_game_create_posts_play_session(httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch) -> None:
    coworld_id = "cow_00000000-0000-0000-0000-000000000001"
    httpserver.expect_request(
        "/observatory/v2/coworlds/play/session",
        method="POST",
        headers={"Authorization": "Bearer token"},
        json={
            "coworld_id": coworld_id,
            "variant_id": "default",
            "allow_spectators": True,
        },
    ).respond_with_json(
        {
            "session_id": "ps_00000000-0000-0000-0000-000000000011",
            "join_url": "/observatory/v2/coworld-play/ps_00000000-0000-0000-0000-000000000011/join",
            "lobby_url": "/observatory/v2/coworld-play/ps_00000000-0000-0000-0000-000000000011",
            "player_count": 3,
            "global_url": "https://api.example.com/v2/coworlds/play/session/ps_00000000/proxy/client/global",
        }
    )

    result = CliRunner().invoke(
        app,
        [
            "hosted-game",
            "create",
            coworld_id,
            "--variant",
            "default",
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Hosted game: ps_00000000-0000-0000-0000-000000000011" in result.output
    assert "Player slots: 3" in result.output
    assert (
        "Player command: uv run coworld hosted-game join ps_00000000-0000-0000-0000-000000000011 --server "
        in result.output
    )
    assert "Player URL: /observatory/v2/coworld-play/ps_00000000-0000-0000-0000-000000000011/join" in result.output
    assert "Spectator URL: /observatory/v2/coworld-play/ps_00000000-0000-0000-0000-000000000011" in result.output


def test_hosted_game_join_posts_join_session(httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch) -> None:
    session_id = "ps_00000000-0000-0000-0000-000000000011"
    httpserver.expect_request(
        f"/observatory/v2/coworlds/play/session/{session_id}/join",
        method="POST",
        headers={"Authorization": "Bearer token"},
    ).respond_with_json(
        {
            "player_url": "https://api.example.com/v2/coworlds/play/session/ps_00000000/proxy/client/player",
            "slot": 1,
            "player": {"slot": 1, "label": "Player 2"},
        }
    )

    result = CliRunner().invoke(
        app,
        [
            "hosted-game",
            "join",
            session_id,
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Slot: 1" in result.output
    assert "Player: Player 2" in result.output
    assert "URL: https://api.example.com" in result.output


def test_coworld_show_command_prints_json(httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch) -> None:
    coworld_id = "cow_00000000-0000-0000-0000-000000000001"
    httpserver.expect_request(
        "/observatory/v2/coworlds",
        method="GET",
        headers={"Authorization": "Bearer token"},
        query_string="limit=200&offset=0",
    ).respond_with_json(
        [
            {
                "id": coworld_id,
                "name": "unit-test-game",
                "version": "0.1.0",
                "manifest": _manifest_with_image("img_00000000-0000-0000-0000-000000000010"),
                "manifest_hash": "sha256:manifest-hash",
                "size_bytes": 1234,
                "created_at": "2026-05-08T21:00:00Z",
                "canonical": True,
            }
        ]
    )
    result = CliRunner().invoke(
        app,
        [
            "show",
            coworld_id,
            "--server",
            httpserver.url_for(""),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["name"] == "unit-test-game"


def test_coworld_show_command_pages_until_uploaded_world(
    httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    coworld_id = "cow_00000000-0000-0000-0000-000000000001"
    httpserver.expect_request(
        "/observatory/v2/coworlds",
        method="GET",
        headers={"Authorization": "Bearer token"},
        query_string="limit=200&offset=0",
    ).respond_with_json(
        [
            {
                "id": f"cow_10000000-0000-0000-0000-00000000{i:04d}",
                "name": f"other-game-{i}",
                "version": "0.1.0",
                "manifest": _manifest_with_image("img_00000000-0000-0000-0000-000000000010"),
                "manifest_hash": f"sha256:manifest-hash-{i}",
                "size_bytes": 1234,
                "created_at": "2026-05-08T21:00:00Z",
                "canonical": False,
            }
            for i in range(200)
        ]
    )
    httpserver.expect_request(
        "/observatory/v2/coworlds",
        method="GET",
        headers={"Authorization": "Bearer token"},
        query_string="limit=200&offset=200",
    ).respond_with_json(
        [
            {
                "id": coworld_id,
                "name": "unit-test-game",
                "version": "0.1.0",
                "manifest": _manifest_with_image("img_00000000-0000-0000-0000-000000000010"),
                "manifest_hash": "sha256:manifest-hash",
                "size_bytes": 1234,
                "created_at": "2026-05-08T21:00:00Z",
                "canonical": True,
            }
        ]
    )
    result = CliRunner().invoke(
        app,
        [
            "show",
            coworld_id,
            "--server",
            httpserver.url_for(""),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["name"] == "unit-test-game"


def test_coworld_images_command_lists_uploaded_images(httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch) -> None:
    httpserver.expect_request(
        "/observatory/v2/container_images",
        method="GET",
        headers={"Authorization": "Bearer token"},
        query_string="limit=25&offset=0",
    ).respond_with_json(
        [
            {
                "id": "img_00000000-0000-0000-0000-000000000010",
                "name": "unit-test-runtime",
                "version": 1,
                "client_hash": "sha256:client-hash",
                "status": "ready",
                "public_image_uri": "public.ecr.aws/softmax/unit-test-runtime@sha256:public",
            }
        ]
    )

    result = CliRunner().invoke(
        app,
        [
            "images",
            "--server",
            httpserver.url_for(""),
            "--limit",
            "25",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)[0]["id"] == "img_00000000-0000-0000-0000-000000000010"


def test_coworld_images_command_shows_uploaded_image(httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch) -> None:
    image_id = "img_00000000-0000-0000-0000-000000000010"
    httpserver.expect_request(
        f"/observatory/v2/container_images/{image_id}",
        method="GET",
        headers={"Authorization": "Bearer token"},
    ).respond_with_json(
        {
            "id": image_id,
            "name": "unit-test-runtime",
            "version": 1,
            "client_hash": "sha256:client-hash",
            "status": "ready",
            "public_image_uri": "public.ecr.aws/softmax/unit-test-runtime@sha256:public",
        }
    )

    result = CliRunner().invoke(
        app,
        [
            "images",
            image_id,
            "--server",
            httpserver.url_for(""),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["name"] == "unit-test-runtime"


def test_download_coworld_command_writes_local_package(
    tmp_path: Path,
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coworld_id = "cow_00000000-0000-0000-0000-000000000040"
    public_image_uri = "public.ecr.aws/softmax/coworld@sha256:public-digest"
    output_dir = tmp_path / "downloaded"
    docker_calls: list[list[str]] = []
    docker_envs: list[dict[str, str] | None] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        docker_calls.append(command)
        docker_envs.append(cast(dict[str, str] | None, kwargs.get("env")))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("coworld.upload.subprocess.run", fake_run)
    httpserver.expect_request(
        f"/observatory/v2/coworlds/{coworld_id}",
        method="GET",
    ).respond_with_json(
        {
            "id": coworld_id,
            "name": "unit-test-game",
            "version": "0.1.0",
            "manifest": _manifest_with_image(public_image_uri),
            "manifest_hash": "sha256:manifest-hash",
            "size_bytes": 1234,
            "canonical": True,
        }
    )

    result = CliRunner().invoke(
        app,
        [
            "download",
            coworld_id,
            "--output-dir",
            str(output_dir),
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code == 0, result.output
    local_image = "coworld/cow_00000000-0000-0000-0000-000000000040/unit-test-game-0.1.0-0:downloaded"
    assert docker_calls == [
        ["docker", "pull", public_image_uri],
        ["docker", "tag", public_image_uri, local_image],
    ]
    assert docker_envs[0] is not None
    assert docker_envs[0]["DOCKER_CONFIG"] != os.environ.get("DOCKER_CONFIG")
    assert "coworld-docker-config-" in Path(docker_envs[0]["DOCKER_CONFIG"]).name
    assert docker_envs[1] is None
    manifest = json.loads((output_dir / coworld_id / "coworld_manifest.json").read_text())
    assert manifest["game"]["runnable"]["image"] == local_image
    assert manifest["player"][0]["image"] == local_image
    image_map = json.loads((output_dir / coworld_id / "coworld_images.json").read_text())
    assert image_map["images"] == [{"public_image_uri": public_image_uri, "local_image": local_image}]
    agents_path = output_dir / coworld_id / "AGENTS.md"
    assert "Champion means your nominated policy version" in agents_path.read_text(encoding="utf-8")
    assert "Downloaded Coworld: unit-test-game:0.1.0" in result.output
    assert f"Agent guide: {agents_path}" in result.output
    assert f"Play: uv run coworld play {coworld_id}" in result.output


def test_download_coworld_command_resolves_canonical_name(
    tmp_path: Path,
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coworld_id = "cow_00000000-0000-0000-0000-000000000040"
    public_image_uri = "public.ecr.aws/softmax/coworld@sha256:public-digest"
    output_dir = tmp_path / "downloaded"
    docker_calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        docker_calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("coworld.upload.subprocess.run", fake_run)
    httpserver.expect_request(
        "/observatory/v2/coworlds",
        method="GET",
        headers={"Authorization": "Bearer token"},
        query_string="limit=200&offset=0",
    ).respond_with_json(
        [
            {
                "id": coworld_id,
                "name": "unit-test-game",
                "version": "0.1.0",
                "manifest": _manifest_with_image(public_image_uri),
                "manifest_hash": "sha256:manifest-hash",
                "size_bytes": 1234,
                "created_at": "2026-05-12T00:00:00Z",
                "canonical": True,
            }
        ]
    )
    httpserver.expect_request(
        f"/observatory/v2/coworlds/{coworld_id}",
        method="GET",
    ).respond_with_json(
        {
            "id": coworld_id,
            "name": "unit-test-game",
            "version": "0.1.0",
            "manifest": _manifest_with_image(public_image_uri),
            "manifest_hash": "sha256:manifest-hash",
            "size_bytes": 1234,
            "canonical": True,
        }
    )

    result = CliRunner().invoke(
        app,
        [
            "download",
            "unit_test_game",
            "--output-dir",
            str(output_dir),
            "--server",
            httpserver.url_for(""),
        ],
    )

    assert result.exit_code == 0, result.output
    local_image = "coworld/cow_00000000-0000-0000-0000-000000000040/unit-test-game-0.1.0-0:downloaded"
    assert docker_calls == [
        ["docker", "pull", public_image_uri],
        ["docker", "tag", public_image_uri, local_image],
    ]
    manifest = json.loads((output_dir / coworld_id / "coworld_manifest.json").read_text())
    assert manifest["game"]["runnable"]["image"] == local_image


def test_download_coworld_command_skips_cached_coworld_by_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coworld_id = "cow_00000000-0000-0000-0000-000000000040"
    output_dir = tmp_path / "downloaded"
    cached_dir = output_dir / coworld_id
    cached_dir.mkdir(parents=True)
    (cached_dir / "coworld_manifest.json").write_text('{"cached": true}\n', encoding="utf-8")
    (cached_dir / "coworld_images.json").write_text('{"cached": true}\n', encoding="utf-8")
    docker_calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        docker_calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("coworld.upload.subprocess.run", fake_run)

    result = CliRunner().invoke(app, ["download", coworld_id, "--output-dir", str(output_dir)])

    assert result.exit_code == 0, result.output
    assert docker_calls == []
    assert "Champion means your nominated policy version" in (cached_dir / "AGENTS.md").read_text(encoding="utf-8")
    assert f"Coworld already downloaded: {coworld_id}" in result.output
    assert f"Manifest: {cached_dir / 'coworld_manifest.json'}" in result.output
    assert f"Agent guide: {cached_dir / 'AGENTS.md'}" in result.output
    assert f"Play: uv run coworld play {coworld_id}" in result.output


def test_download_coworld_command_refreshes_cached_coworld(
    tmp_path: Path,
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coworld_id = "cow_00000000-0000-0000-0000-000000000040"
    public_image_uri = "public.ecr.aws/softmax/coworld@sha256:public-digest"
    output_dir = tmp_path / "downloaded"
    cached_dir = output_dir / coworld_id
    cached_dir.mkdir(parents=True)
    (cached_dir / "coworld_manifest.json").write_text('{"cached": true}\n', encoding="utf-8")
    (cached_dir / "coworld_images.json").write_text('{"cached": true}\n', encoding="utf-8")
    docker_calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        docker_calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("coworld.upload.subprocess.run", fake_run)
    httpserver.expect_request(
        f"/observatory/v2/coworlds/{coworld_id}",
        method="GET",
    ).respond_with_json(
        {
            "id": coworld_id,
            "name": "unit-test-game",
            "version": "0.1.0",
            "manifest": _manifest_with_image(public_image_uri),
            "manifest_hash": "sha256:manifest-hash",
            "size_bytes": 1234,
            "canonical": True,
        }
    )

    result = CliRunner().invoke(
        app,
        [
            "download",
            coworld_id,
            "--output-dir",
            str(output_dir),
            "--server",
            httpserver.url_for(""),
            "--refresh",
        ],
    )

    assert result.exit_code == 0, result.output
    local_image = "coworld/cow_00000000-0000-0000-0000-000000000040/unit-test-game-0.1.0-0:downloaded"
    assert docker_calls == [
        ["docker", "pull", public_image_uri],
        ["docker", "tag", public_image_uri, local_image],
    ]
    manifest = json.loads((cached_dir / "coworld_manifest.json").read_text())
    assert manifest["game"]["runnable"]["image"] == local_image
    assert "Champion means your nominated policy version" in (cached_dir / "AGENTS.md").read_text(encoding="utf-8")


def test_downloaded_image_tags_include_coworld_id() -> None:
    assert _local_image_tag("cow_00000000-0000-0000-0000-000000000041", "unit-test-game", "0.1.0", 0) == (
        "coworld/cow_00000000-0000-0000-0000-000000000041/unit-test-game-0.1.0-0:downloaded"
    )
    assert _local_image_tag("cow_00000000-0000-0000-0000-000000000042", "unit-test-game", "0.1.0", 0) == (
        "coworld/cow_00000000-0000-0000-0000-000000000042/unit-test-game-0.1.0-0:downloaded"
    )


def test_local_image_client_hash_uses_docker_archive_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    config = b'{"architecture":"amd64","cmd":["python","game.py"],"os":"linux"}'
    archive = _docker_archive(config=config, layers=[b"layer-one", b"layer-two"])
    save_calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, stdout="sha256:unit-image-id\n")
        assert command == ["docker", "image", "save", "unit-test-runtime:latest"]
        save_calls.append(command)
        stdout = cast(BinaryIO, kwargs["stdout"])
        stdout.write(archive)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("coworld.upload.subprocess.run", fake_run)

    expected = _expected_archive_hash(config, [b"layer-one", b"layer-two"])
    assert _local_image_client_hash("unit-test-runtime:latest") == expected
    assert _local_image_client_hash("unit-test-runtime:latest") == expected
    assert len(save_calls) == 1


def test_local_image_client_hash_ignores_malformed_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    cache_path = tmp_path / "coworld" / "image_client_hashes.json"
    cache_path.parent.mkdir()
    cache_path.write_text("{not-json", encoding="utf-8")
    config = b'{"architecture":"amd64","os":"linux"}'
    archive = _docker_archive(config=config, layers=[b"layer-one"])

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, stdout="sha256:unit-image-id\n")
        assert command == ["docker", "image", "save", "unit-test-runtime:latest"]
        stdout = cast(BinaryIO, kwargs["stdout"])
        stdout.write(archive)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("coworld.upload.subprocess.run", fake_run)

    expected = _expected_archive_hash(config, [b"layer-one"])
    assert _local_image_client_hash("unit-test-runtime:latest") == expected
    assert json.loads(cache_path.read_text(encoding="utf-8")) == {"sha256:unit-image-id": expected}


def test_docker_archive_client_hash_matches_config_and_layer_digests() -> None:
    config = b'{"architecture":"amd64","env":["A=B"],"os":"linux"}'
    archive = io.BytesIO(_docker_archive(config=config, layers=[b"layer-one"]))

    assert _docker_archive_client_hash(archive) == _expected_archive_hash(config, [b"layer-one"])


def test_local_image_client_hash_rejects_non_amd64_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    archive = _docker_archive(config=b'{"architecture":"arm64","os":"linux"}', layers=[b"layer-one"])

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[:3] == ["docker", "image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, stdout="sha256:unit-image-id\n")
        assert command == ["docker", "image", "save", "unit-test-runtime:latest"]
        stdout = cast(BinaryIO, kwargs["stdout"])
        stdout.write(archive)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("coworld.upload.subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="linux/arm64"):
        _local_image_client_hash("unit-test-runtime:latest")


def test_push_archive_to_registry_uploads_layers_config_and_manifest(httpserver: HTTPServer) -> None:
    config = b'{"architecture":"amd64","os":"linux"}'
    layer_data = b"fake-layer-content"
    archive_bytes = _docker_archive(config=config, layers=[layer_data])

    layer_digest = _sha256_digest(layer_data)
    config_digest = _sha256_digest(config)

    # Layer blob upload: POST to initiate, PUT to finalize
    httpserver.expect_request("/v2/repo/test/blobs/uploads/", method="POST").respond_with_data(
        "", status=202, headers={"Location": httpserver.url_for("/v2/repo/test/blobs/upload-session-layer")}
    )
    httpserver.expect_request("/v2/repo/test/blobs/upload-session-layer", method="PUT").respond_with_data(
        "", status=201
    )

    # Config blob upload: POST to initiate, PUT to finalize
    httpserver.expect_request("/v2/repo/test/blobs/uploads/", method="POST").respond_with_data(
        "", status=202, headers={"Location": httpserver.url_for("/v2/repo/test/blobs/upload-session-config")}
    )
    httpserver.expect_request("/v2/repo/test/blobs/upload-session-config", method="PUT").respond_with_data(
        "", status=201
    )

    # Manifest PUT
    httpserver.expect_request("/v2/repo/test/manifests/v1", method="PUT").respond_with_data("", status=201)

    base_url = httpserver.url_for("/v2/repo/test")
    archive_file = io.BytesIO(archive_bytes)
    _push_archive_to_registry(archive_file, base_url, "v1", "dGVzdDp0ZXN0")

    manifest_req = next(req for req, _ in httpserver.log if "/manifests/" in req.path)
    manifest_body = json.loads(manifest_req.data)
    assert manifest_body["schemaVersion"] == 2
    assert manifest_body["config"]["digest"] == config_digest
    assert len(manifest_body["layers"]) == 1
    assert manifest_body["layers"][0]["digest"] == layer_digest


def test_registry_upload_timeout_allows_slow_large_layer_writes() -> None:
    assert _REGISTRY_UPLOAD_TIMEOUT.connect == 600.0
    assert _REGISTRY_UPLOAD_TIMEOUT.read == 600.0
    assert _REGISTRY_UPLOAD_TIMEOUT.write == 3600.0
    assert _REGISTRY_UPLOAD_TIMEOUT.pool == 600.0


def test_manifest_image_helpers_substitute_role_images() -> None:
    manifest: dict[str, object] = {
        "game": {
            "name": "unit-test-game",
            "runnable": {"type": "game", "image": "unit-test-runtime:latest"},
        },
        "player": [
            {
                "id": "unit-test-player",
                "type": "player",
                "image": "player-img:latest",
                "run": ["python", "-m", "unit_test.player"],
            }
        ],
        "reporter": [
            {
                "id": "unit-test-reporter",
                "type": "reporter",
                "image": "reporter-img:latest",
                "run": ["python", "/app/reporter.py"],
            }
        ],
        "grader": [
            {
                "id": "unit-test-grader",
                "type": "grader",
                "image": "grader-img:latest",
            }
        ],
    }

    discovered = {field["image"] for field in _manifest_image_fields(manifest)}
    assert discovered == {"unit-test-runtime:latest", "player-img:latest", "reporter-img:latest", "grader-img:latest"}

    image_tags = {
        "unit-test-runtime:latest": "img_game",
        "player-img:latest": "img_player",
        "reporter-img:latest": "img_reporter",
        "grader-img:latest": "img_grader",
    }
    substituted = _manifest_with_local_images(manifest, image_tags)

    game = substituted["game"]
    assert isinstance(game, dict)
    runnable = game["runnable"]
    assert isinstance(runnable, dict)
    assert runnable["image"] == "img_game"

    players = substituted["player"]
    assert isinstance(players, list)
    assert players[0]["image"] == "img_player"

    reporters = substituted["reporter"]
    assert isinstance(reporters, list)
    assert reporters[0]["image"] == "img_reporter"

    graders = substituted["grader"]
    assert isinstance(graders, list)
    assert graders[0]["image"] == "img_grader"


def _docker_archive(*, config: bytes, layers: list[bytes]) -> bytes:
    archive = io.BytesIO()
    layer_names = [f"{index}/layer.tar" for index in range(len(layers))]
    with tarfile.open(fileobj=archive, mode="w") as tar:
        _add_tar_file(tar, "manifest.json", json.dumps([{"Config": "config.json", "Layers": layer_names}]).encode())
        _add_tar_file(tar, "config.json", config)
        for name, content in zip(layer_names, layers, strict=True):
            _add_tar_file(tar, name, content)
    return archive.getvalue()


def _add_tar_file(tar: tarfile.TarFile, name: str, content: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    tar.addfile(info, io.BytesIO(content))


def _expected_archive_hash(config: bytes, layers: list[bytes]) -> str:
    content = {
        "config": _sha256_digest(config),
        "layers": [_sha256_digest(layer) for layer in layers],
    }
    return _sha256_digest(json.dumps(content, sort_keys=True, separators=(",", ":")).encode())


def _sha256_digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


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
        "manifest": manifest,
        "manifest_hash": "sha256:manifest-hash",
        "size_bytes": 1234,
        "created_at": "2026-05-08T21:00:00Z",
        "canonical": canonical,
    }


def _episode_request(
    episode_request_id: str,
    coworld_id: str,
    status: str,
    *,
    error: str | None = None,
) -> dict[str, object]:
    return {
        "id": episode_request_id,
        "coworld_id": coworld_id,
        "coworld_name": "unit-test-game",
        "coworld_version": "0.2.0",
        "status": status,
        "error": error,
    }


def _manifest() -> dict[str, object]:
    return {
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
        "reporter": [
            {
                "id": "unit-test-reporter",
                "name": "Unit Test Reporter",
                "description": "Reporter stub; reuses unit-test-runtime so upload dedupe doesn't request a 2nd image.",
                "type": "reporter",
                "image": "unit-test-runtime:latest",
            }
        ],
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
    reporters = manifest["reporter"]
    assert isinstance(reporters, list)
    reporter = reporters[0]
    assert isinstance(reporter, dict)
    reporter["image"] = image
    graders = manifest["grader"]
    assert isinstance(graders, list)
    grader = graders[0]
    assert isinstance(grader, dict)
    grader["image"] = image
    return manifest
