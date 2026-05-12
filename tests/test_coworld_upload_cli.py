import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path
from typing import BinaryIO, cast

import pytest
from pytest_httpserver import HTTPServer
from typer.testing import CliRunner

from coworld.cli import app
from coworld.upload import (
    _docker_archive_client_hash,
    _local_image_client_hash,
    _local_image_tag,
    upload_coworld,
)


def test_upload_coworld_posts_standalone_manifest(
    tmp_path: Path,
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = _write_manifest(tmp_path)
    certification_calls: list[tuple[Path, float]] = []
    image_id = "img_00000000-0000-0000-0000-000000000010"
    softmax_image_uri = "123456789012.dkr.ecr.us-east-1.amazonaws.com/cogames/user/unit-test-runtime@sha256:digest"
    pushed_images: list[tuple[str, str]] = []

    monkeypatch.setattr("coworld.upload._load_current_cogames_token", lambda: "token")
    monkeypatch.setattr(
        "coworld.upload.certify_coworld",
        lambda manifest_path, *, timeout_seconds: certification_calls.append((manifest_path, timeout_seconds)),
    )
    monkeypatch.setattr("coworld.upload._local_image_client_hash", lambda image: "sha256:client-hash")
    monkeypatch.setattr(
        "coworld.upload._push_container_image",
        lambda source_image, push_info: pushed_images.append((source_image, push_info.image_uri)),
    )
    httpserver.expect_request(
        "/v2/container_images/upload",
        method="POST",
        headers={"X-Auth-Token": "token"},
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
                "repository": "cogames/user/unit-test-runtime",
                "tag": "v1",
                "image_uri": "123456789012.dkr.ecr.us-east-1.amazonaws.com/cogames/user/unit-test-runtime:v1",
                "expires_at": "2026-05-06T22:00:00Z",
                "credentials": {
                    "access_key_id": "access-key",
                    "secret_access_key": "secret-key",
                    "session_token": "session-token",
                },
            },
        }
    )
    httpserver.expect_request(
        "/v2/container_images/upload/complete",
        method="POST",
        headers={"X-Auth-Token": "token"},
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
        "/v2/coworlds/upload",
        method="POST",
        headers={"X-Auth-Token": "token"},
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
    assert certification_calls == [(manifest_path.resolve(), 60.0)]
    assert pushed_images == [
        ("unit-test-runtime:latest", "123456789012.dkr.ecr.us-east-1.amazonaws.com/cogames/user/unit-test-runtime:v1"),
    ]
    upload_req = next(req for req, _ in httpserver.log if req.path == "/v2/coworlds/upload")
    uploaded_manifest = upload_req.get_json()["manifest"]
    assert uploaded_manifest["game"]["runnable"]["image"] == image_id
    assert uploaded_manifest["player"][0]["image"] == image_id
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
    softmax_image_uri = "123456789012.dkr.ecr.us-east-1.amazonaws.com/cogames/user/unit-test-runtime@sha256:digest"

    monkeypatch.setattr("coworld.upload._load_current_cogames_token", lambda: "token")
    monkeypatch.setattr(
        "coworld.upload.certify_coworld",
        lambda manifest_path, *, timeout_seconds: certification_calls.append((manifest_path, timeout_seconds)),
    )
    monkeypatch.setattr("coworld.upload._local_image_client_hash", lambda image: "sha256:client-hash")
    monkeypatch.setattr("coworld.upload._push_container_image", lambda source_image, push_info: None)
    httpserver.expect_request("/v2/container_images/upload", method="POST").respond_with_json(
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
    httpserver.expect_request("/v2/coworlds/upload", method="POST").respond_with_json(
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
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Upload complete: unit-test-game:0.1.0" in result.output
    assert "Coworld: cow_00000000-0000-0000-0000-000000000002" in result.output
    assert "Manifest hash: sha256:manifest-hash" in result.output
    assert "Canonical: yes" in result.output
    assert certification_calls == [(manifest_path.resolve(), 60.0)]


def test_upload_policy_command_creates_docker_image_policy(
    httpserver: HTTPServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    softmax_image_uri = "123456789012.dkr.ecr.us-east-1.amazonaws.com/cogames/user/unit-test-policy@sha256:digest"

    monkeypatch.setattr("coworld.upload._load_current_cogames_token", lambda: "token")
    monkeypatch.setattr("coworld.upload._local_image_client_hash", lambda image: "sha256:client-hash")
    monkeypatch.setattr("coworld.upload._push_container_image", lambda source_image, push_info: None)
    httpserver.expect_request(
        "/v2/container_images/upload",
        method="POST",
        headers={"X-Auth-Token": "token"},
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
        "/stats/policies/docker-img/complete",
        method="POST",
        headers={"X-Auth-Token": "token"},
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
    softmax_image_uri = "123456789012.dkr.ecr.us-east-1.amazonaws.com/cogames/user/unit-test-policy@sha256:digest"

    monkeypatch.setattr("coworld.upload._load_current_cogames_token", lambda: "token")
    monkeypatch.setattr("coworld.upload._local_image_client_hash", lambda image: "sha256:client-hash")
    monkeypatch.setattr("coworld.upload._push_container_image", lambda source_image, push_info: None)
    httpserver.expect_request(
        "/v2/container_images/upload",
        method="POST",
        headers={"X-Auth-Token": "token"},
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
        "/stats/policies/docker-img/complete",
        method="POST",
        headers={"X-Auth-Token": "token"},
        json={
            "name": "paintbot",
            "container_image_id": "img_00000000-0000-0000-0000-000000000030",
            "policy_secret_env": {
                "USE_BEDROCK": "true",
                "ANTHROPIC_API_KEY": "sk-ant-test",
            },
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
            "--secret-env",
            "ANTHROPIC_API_KEY=sk-ant-test",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Upload complete: paintbot:v1" in result.output


def test_coworld_list_command_prints_json(httpserver: HTTPServer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("coworld.upload._load_current_cogames_token", lambda: "token")
    httpserver.expect_request(
        "/v2/coworlds",
        method="GET",
        headers={"X-Auth-Token": "token"},
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
    monkeypatch.setattr("coworld.upload._load_current_cogames_token", lambda: "token")
    httpserver.expect_request(
        "/v2/coworlds/play/session",
        method="POST",
        headers={"X-Auth-Token": "token"},
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
            "global_url": "https://api.example.com/v2/coworlds/play/session/ps_00000000/proxy/clients/global",
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
    monkeypatch.setattr("coworld.upload._load_current_cogames_token", lambda: "token")
    httpserver.expect_request(
        f"/v2/coworlds/play/session/{session_id}/join",
        method="POST",
        headers={"X-Auth-Token": "token"},
    ).respond_with_json(
        {
            "player_url": "https://api.example.com/v2/coworlds/play/session/ps_00000000/proxy/clients/player",
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
    monkeypatch.setattr("coworld.upload._load_current_cogames_token", lambda: "token")
    httpserver.expect_request(
        "/v2/coworlds",
        method="GET",
        headers={"X-Auth-Token": "token"},
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
    monkeypatch.setattr("coworld.upload._load_current_cogames_token", lambda: "token")
    httpserver.expect_request(
        "/v2/coworlds",
        method="GET",
        headers={"X-Auth-Token": "token"},
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
        "/v2/coworlds",
        method="GET",
        headers={"X-Auth-Token": "token"},
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
    monkeypatch.setattr("coworld.upload._load_current_cogames_token", lambda: "token")
    httpserver.expect_request(
        "/v2/container_images",
        method="GET",
        headers={"X-Auth-Token": "token"},
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
    monkeypatch.setattr("coworld.upload._load_current_cogames_token", lambda: "token")
    httpserver.expect_request(
        f"/v2/container_images/{image_id}",
        method="GET",
        headers={"X-Auth-Token": "token"},
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
    public_image_uri = "public.ecr.aws/softmax/cogames@sha256:public-digest"
    output_dir = tmp_path / "downloaded"
    docker_calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        docker_calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("coworld.upload.subprocess.run", fake_run)
    httpserver.expect_request(
        "/v2/coworlds/cow_00000000-0000-0000-0000-000000000040",
        method="GET",
    ).respond_with_json(
        {
            "id": "cow_00000000-0000-0000-0000-000000000040",
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
            "cow_00000000-0000-0000-0000-000000000040",
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
    manifest = json.loads((output_dir / "coworld_manifest.json").read_text())
    assert manifest["game"]["runnable"]["image"] == local_image
    assert manifest["player"][0]["image"] == local_image
    image_map = json.loads((output_dir / "coworld_images.json").read_text())
    assert image_map["images"] == [{"public_image_uri": public_image_uri, "local_image": local_image}]
    assert "Downloaded Coworld: unit-test-game:0.1.0" in result.output


def test_downloaded_image_tags_include_coworld_id() -> None:
    assert _local_image_tag("cow_00000000-0000-0000-0000-000000000041", "unit-test-game", "0.1.0", 0) == (
        "coworld/cow_00000000-0000-0000-0000-000000000041/unit-test-game-0.1.0-0:downloaded"
    )
    assert _local_image_tag("cow_00000000-0000-0000-0000-000000000042", "unit-test-game", "0.1.0", 0) == (
        "coworld/cow_00000000-0000-0000-0000-000000000042/unit-test-game-0.1.0-0:downloaded"
    )


def test_local_image_client_hash_uses_docker_archive_content(monkeypatch: pytest.MonkeyPatch) -> None:
    archive = _docker_archive(config=b'{"cmd":["python","game.py"]}', layers=[b"layer-one", b"layer-two"])

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command == ["docker", "image", "save", "unit-test-runtime:latest"]
        stdout = cast(BinaryIO, kwargs["stdout"])
        stdout.write(archive)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("coworld.upload.subprocess.run", fake_run)

    assert _local_image_client_hash("unit-test-runtime:latest") == _expected_archive_hash(
        b'{"cmd":["python","game.py"]}',
        [b"layer-one", b"layer-two"],
    )


def test_docker_archive_client_hash_matches_config_and_layer_digests() -> None:
    archive = io.BytesIO(_docker_archive(config=b'{"env":["A=B"]}', layers=[b"layer-one"]))

    assert _docker_archive_client_hash(archive) == _expected_archive_hash(b'{"env":["A=B"]}', [b"layer-one"])


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


def _write_manifest(tmp_path: Path) -> Path:
    world_dir = tmp_path / "world"
    world_dir.mkdir(parents=True)
    manifest_path = world_dir / "coworld_manifest.json"
    manifest_path.write_text(json.dumps(_manifest()))
    return manifest_path


def _manifest() -> dict[str, object]:
    return {
        "game": {
            "name": "unit-test-game",
            "version": "0.1.0",
            "description": "Unit test Cogame manifest.",
            "owner": "cogames@softmax.com",
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
    return manifest
