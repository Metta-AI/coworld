from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import tarfile
import tempfile
from base64 import b64encode
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Self

import httpx
import typer
from pydantic import BaseModel

from coworld.certifier import certify_coworld, load_coworld_package
from coworld.config import DEFAULT_LOGIN_SERVER, DEFAULT_SUBMIT_SERVER

_LOCAL_TAG_SEPARATOR_RE = re.compile(r"[^a-z0-9._-]+")


class CoworldUploadResponse(BaseModel):
    id: str
    name: str
    version: str
    manifest: dict[str, Any]
    manifest_hash: str
    size_bytes: int


class PolicyVersionResponse(BaseModel):
    id: str
    name: str
    version: int
    pools: list[str] | None = None
    submit_error: str | None = None


class AwsCredentials(BaseModel):
    access_key_id: str
    secret_access_key: str
    session_token: str


class EcrPushInfo(BaseModel):
    kind: str = "ecr"
    region: str
    registry: str
    repository: str
    tag: str
    image_uri: str
    endpoint_url: str | None = None
    credentials: AwsCredentials


class ContainerImageResponse(BaseModel):
    id: str
    name: str
    version: int
    client_hash: str | None = None
    status: str
    image_uri: str | None = None
    image_digest: str | None = None
    public_image_uri: str | None = None


class CoworldListEntry(BaseModel):
    id: str
    name: str
    version: str
    manifest: dict[str, Any]
    manifest_hash: str
    size_bytes: int
    created_at: datetime


class ImageUploadResponse(BaseModel):
    image: ContainerImageResponse
    pre_signed_info: EcrPushInfo | None = None


@dataclass(frozen=True)
class CoworldUploadResult:
    id: str
    name: str
    version: str
    manifest_hash: str
    size_bytes: int


class CoworldUploadClient:
    def __init__(self, server_url: str, token: str):
        self._http_client = httpx.Client(base_url=server_url, timeout=30.0)
        self._token = token

    @classmethod
    def from_login(cls, *, server_url: str, login_server: str) -> Self:
        token = _load_current_cogames_token(login_server=login_server)
        if token is None:
            raise RuntimeError("Not authenticated. Run: uv run softmax login")
        return cls(server_url=server_url, token=token)

    def close(self) -> None:
        self._http_client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        return {"X-Auth-Token": self._token}

    def upload_manifest(self, manifest: dict[str, object]) -> CoworldUploadResponse:
        response = self._http_client.post(
            "/v2/coworlds/upload",
            headers=self._headers(),
            json={"manifest": manifest},
            timeout=120.0,
        )
        response.raise_for_status()
        return CoworldUploadResponse.model_validate(response.json())

    def list_coworlds(self, *, limit: int = 200, offset: int = 0) -> list[CoworldListEntry]:
        response = self._http_client.get(
            "/v2/coworlds",
            headers=self._headers(),
            params={"limit": limit, "offset": offset},
            timeout=60.0,
        )
        response.raise_for_status()
        return [CoworldListEntry.model_validate(item) for item in response.json()]

    def find_coworld(self, coworld_id: str) -> CoworldListEntry | None:
        limit = 200
        offset = 0
        while True:
            coworlds = self.list_coworlds(limit=limit, offset=offset)
            for coworld in coworlds:
                if coworld.id == coworld_id:
                    return coworld
            if len(coworlds) < limit:
                return None
            offset += limit

    def list_images(self, *, limit: int = 200, offset: int = 0) -> list[ContainerImageResponse]:
        response = self._http_client.get(
            "/v2/container_images",
            headers=self._headers(),
            params={"limit": limit, "offset": offset},
            timeout=60.0,
        )
        response.raise_for_status()
        return [ContainerImageResponse.model_validate(item) for item in response.json()]

    def get_image(self, image_id: str) -> ContainerImageResponse:
        response = self._http_client.get(
            f"/v2/container_images/{image_id}",
            headers=self._headers(),
            timeout=60.0,
        )
        response.raise_for_status()
        return ContainerImageResponse.model_validate(response.json())

    def request_image_upload(self, *, name: str, client_hash: str) -> ImageUploadResponse:
        response = self._http_client.post(
            "/v2/container_images/upload",
            headers=self._headers(),
            json={"name": name, "client_hash": client_hash},
            timeout=60.0,
        )
        response.raise_for_status()
        return ImageUploadResponse.model_validate(response.json())

    def complete_image_upload(self, image_id: str) -> ContainerImageResponse:
        response = self._http_client.post(
            "/v2/container_images/upload/complete",
            headers=self._headers(),
            json={"id": image_id},
            timeout=120.0,
        )
        response.raise_for_status()
        return ContainerImageResponse.model_validate(response.json())

    def complete_docker_image_policy(
        self,
        *,
        name: str,
        container_image_id: str,
        run: list[str] | None,
    ) -> PolicyVersionResponse:
        payload: dict[str, Any] = {"name": name, "container_image_id": container_image_id}
        if run:
            payload["run"] = run
        response = self._http_client.post(
            "/stats/policies/docker-img/complete",
            headers=self._headers(),
            json=payload,
            timeout=120.0,
        )
        response.raise_for_status()
        return PolicyVersionResponse.model_validate(response.json())


def upload_coworld(
    manifest_path: Path,
    *,
    server: str = DEFAULT_SUBMIT_SERVER,
    login_server: str = DEFAULT_LOGIN_SERVER,
    timeout_seconds: float = 60.0,
) -> CoworldUploadResult:
    package = load_coworld_package(manifest_path)
    certify_coworld(package.manifest_path, timeout_seconds=timeout_seconds)

    with CoworldUploadClient.from_login(server_url=server, login_server=login_server) as client:
        upload_manifest = _manifest_with_softmax_image_ids(
            client,
            package.manifest.model_dump(by_alias=True, exclude_none=True),
        )
        response = client.upload_manifest(upload_manifest)

    return CoworldUploadResult(
        id=response.id,
        name=response.name,
        version=response.version,
        manifest_hash=response.manifest_hash,
        size_bytes=response.size_bytes,
    )


def _load_current_cogames_token(*, login_server: str) -> str | None:
    from softmax.auth import load_current_cogames_token  # noqa: PLC0415

    return load_current_cogames_token(login_server=login_server)


def upload_coworld_cmd(
    manifest_path: Path,
    server: str = DEFAULT_SUBMIT_SERVER,
    login_server: str = DEFAULT_LOGIN_SERVER,
    timeout_seconds: float = 60.0,
) -> None:
    result = upload_coworld(
        manifest_path,
        server=server,
        login_server=login_server,
        timeout_seconds=timeout_seconds,
    )
    typer.echo(f"Upload complete: {result.name}:{result.version}")
    typer.echo(f"Coworld: {result.id}")
    typer.echo(f"Manifest hash: {result.manifest_hash}")
    typer.echo(f"Size: {result.size_bytes} bytes")


def upload_policy_cmd(
    image: str,
    name: str,
    *,
    run: list[str] | None = None,
    server: str = DEFAULT_SUBMIT_SERVER,
    login_server: str = DEFAULT_LOGIN_SERVER,
) -> None:
    with CoworldUploadClient.from_login(server_url=server, login_server=login_server) as client:
        uploaded_image = _upload_container_image(client, image)
        result = client.complete_docker_image_policy(
            name=name,
            container_image_id=uploaded_image.id,
            run=run,
        )
    typer.echo(f"Upload complete: {result.name}:v{result.version}")


def download_coworld(
    coworld_id: str,
    *,
    server: str = DEFAULT_SUBMIT_SERVER,
) -> CoworldUploadResponse:
    with httpx.Client(base_url=server, timeout=30.0) as http_client:
        response = http_client.get(f"/v2/coworlds/{coworld_id}", timeout=120.0)
    response.raise_for_status()
    return CoworldUploadResponse.model_validate(response.json())


def download_coworld_cmd(
    coworld_id: str,
    output_dir: Path,
    *,
    server: str = DEFAULT_SUBMIT_SERVER,
) -> None:
    coworld = download_coworld(coworld_id, server=server)

    image_tags = _local_image_tags(coworld)
    for public_image_uri, local_tag in image_tags.items():
        subprocess.run(["docker", "pull", public_image_uri], check=True)
        subprocess.run(["docker", "tag", public_image_uri, local_tag], check=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = _manifest_with_local_images(coworld.manifest, image_tags)
    manifest_path = output_dir / "coworld_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    image_map_path = output_dir / "coworld_images.json"
    image_map_path.write_text(
        json.dumps(
            {
                "coworld_id": coworld.id,
                "name": coworld.name,
                "version": coworld.version,
                "images": [
                    {
                        "public_image_uri": public_image_uri,
                        "local_image": local_tag,
                    }
                    for public_image_uri, local_tag in image_tags.items()
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    typer.echo(f"Downloaded Coworld: {coworld.name}:{coworld.version}")
    typer.echo(f"Manifest: {manifest_path}")
    typer.echo(f"Images: {image_map_path}")


def _manifest_with_softmax_image_ids(client: CoworldUploadClient, manifest: dict[str, object]) -> dict[str, object]:
    upload_manifest = copy.deepcopy(manifest)
    replacements = {
        image: _upload_container_image(client, image).id
        for image in sorted({runnable["image"] for runnable in _manifest_image_fields(upload_manifest)})
    }
    for runnable in _manifest_image_fields(upload_manifest):
        runnable["image"] = replacements[runnable["image"]]
    return upload_manifest


def _manifest_image_fields(value: object) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            fields.extend(_manifest_image_fields(item))
    if isinstance(value, dict):
        image = value.get("image")
        if image is not None:
            if not isinstance(image, str):
                raise TypeError("Coworld runnable image must be a string")
            fields.append(value)
        for item in value.values():
            fields.extend(_manifest_image_fields(item))
    return fields


def _local_image_tags(coworld: CoworldUploadResponse) -> dict[str, str]:
    images = sorted({runnable["image"] for runnable in _manifest_image_fields(coworld.manifest)})
    return {
        image: _local_image_tag(coworld.id, coworld.name, coworld.version, index) for index, image in enumerate(images)
    }


def _local_image_tag(coworld_id: str, coworld_name: str, coworld_version: str, index: int) -> str:
    coworld = _slug_for_local_image(coworld_id, "coworld")
    name = _slug_for_local_image(coworld_name, "coworld")
    version = _slug_for_local_image(coworld_version, "version")
    return f"coworld/{coworld}/{name}-{version}-{index}:downloaded"


def _slug_for_local_image(value: str, fallback: str) -> str:
    slug = _LOCAL_TAG_SEPARATOR_RE.sub("-", value.lower()).strip("._-")
    return slug or fallback


def _manifest_with_local_images(
    manifest: dict[str, Any],
    image_tags: dict[str, str],
) -> dict[str, Any]:
    local_manifest = copy.deepcopy(manifest)
    for runnable in _manifest_image_fields(local_manifest):
        image = runnable["image"]
        runnable["image"] = image_tags[image]
    return local_manifest


def _upload_container_image(client: CoworldUploadClient, image: str) -> ContainerImageResponse:
    client_hash = _local_image_client_hash(image)
    response = client.request_image_upload(name=_image_upload_name(image), client_hash=client_hash)

    if response.pre_signed_info is not None:
        _push_container_image(image, response.pre_signed_info)
        completed = client.complete_image_upload(response.image.id)
    else:
        completed = response.image

    return completed


def _local_image_client_hash(image: str) -> str:
    with tempfile.TemporaryFile() as archive:
        subprocess.run(["docker", "image", "save", image], check=True, stdout=archive)
        archive.seek(0)
        return _docker_archive_client_hash(archive)


def _docker_archive_client_hash(archive: Any) -> str:
    with tarfile.open(fileobj=archive, mode="r:*") as tar:
        manifest_json = _read_tar_member(tar, "manifest.json")
        manifest = json.loads(manifest_json)
        if not isinstance(manifest, list) or len(manifest) != 1:
            raise RuntimeError("Docker image archive must contain exactly one image manifest")
        image_manifest = manifest[0]
        if not isinstance(image_manifest, dict):
            raise RuntimeError("Docker image archive manifest entry must be an object")

        config_name = image_manifest["Config"]
        layers = image_manifest["Layers"]
        if not isinstance(config_name, str) or not isinstance(layers, list):
            raise RuntimeError("Docker image archive manifest has invalid config or layers")

        layer_hashes = []
        for layer in layers:
            if not isinstance(layer, str):
                raise RuntimeError("Docker image archive manifest layers must be strings")
            layer_hashes.append(_sha256_digest(_read_tar_member(tar, layer)))

        content = {
            "config": _sha256_digest(_read_tar_member(tar, config_name)),
            "layers": layer_hashes,
        }
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    return _sha256_digest(encoded)


def _read_tar_member(tar: tarfile.TarFile, name: str) -> bytes:
    member = tar.extractfile(name)
    if member is None:
        raise RuntimeError(f"Docker image archive is missing {name}")
    return member.read()


def _sha256_digest(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _push_container_image(source_image: str, push_info: EcrPushInfo) -> None:
    aws_env = os.environ | {
        "AWS_ACCESS_KEY_ID": push_info.credentials.access_key_id,
        "AWS_SECRET_ACCESS_KEY": push_info.credentials.secret_access_key,
        "AWS_SESSION_TOKEN": push_info.credentials.session_token,
    }
    aws_env.pop("AWS_PROFILE", None)
    login_command = ["aws", "ecr", "get-login-password", "--region", push_info.region]
    if push_info.endpoint_url is not None:
        login_command.extend(["--endpoint-url", push_info.endpoint_url])
    password = subprocess.run(
        login_command,
        env=aws_env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    with tempfile.TemporaryDirectory(prefix="coworld-docker-config-") as docker_config_dir:
        auth = b64encode(f"AWS:{password.strip()}".encode()).decode()
        (Path(docker_config_dir) / "config.json").write_text(
            json.dumps({"auths": {push_info.registry: {"auth": auth}}}) + "\n"
        )
        docker_env = os.environ | {"DOCKER_CONFIG": docker_config_dir}
        subprocess.run(["docker", "tag", source_image, push_info.image_uri], check=True)
        subprocess.run(["docker", "push", push_info.image_uri], env=docker_env, check=True)


def _image_upload_name(image: str) -> str:
    name = image.rsplit("/", 1)[-1].split("@", 1)[0].split(":", 1)[0]
    return name or "coworld-image"
