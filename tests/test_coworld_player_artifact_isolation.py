import json
import os
from pathlib import Path
from zipfile import ZipFile

import pytest

from coworld.runner.io import RunnerEpisodeError
from coworld.runner.runner import (
    EpisodeArtifacts,
    EpisodeRunSpec,
    PlayerLaunchSpec,
    RunnableLaunchSpec,
    run_episode_containers,
)

# Build the opt-in Docker fixture with:
# printf 'FROM python:3.12-slim\nRUN pip install websockets==15.0.1\n' | docker build -t artifact-test -
# COWORLD_ARTIFACT_TEST_IMAGE=artifact-test pytest -c packages/coworld/pyproject.toml \
#   packages/coworld/tests/test_coworld_player_artifact_isolation.py
_GAME = """
import asyncio
import json
import os
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from websockets.asyncio.server import serve
from websockets.http11 import Response
from websockets.datastructures import Headers

ready = asyncio.Event()
finished = asyncio.Event()
viewer = asyncio.Event()
players = []
reports = []
config = json.loads(Path('/coworld/config.json').read_text())

def request(connection, request):
    parsed = urlparse(request.path)
    if parsed.path == '/healthz' or parsed.path.startswith('/client/'):
        return Response(200, 'OK', Headers(), b'OK')
    if parsed.path == '/player':
        query = parse_qs(parsed.query)
        if query['token'][0] != config['tokens'][int(query['slot'][0])]:
            return connection.respond(HTTPStatus.FORBIDDEN, 'bad token')

async def handle(ws):
    if ws.request.path == '/global':
        await ws.send('snapshot')
        viewer.set()
        await finished.wait()
        return
    await ws.recv()
    players.append(ws)
    if len(players) == 2:
        ready.set()
    await ready.wait()
    await ws.send('probe')
    reports.append(await ws.recv())
    if len(reports) == 2:
        finished.set()
    await finished.wait()
    await ws.send('done')

async def main():
    async with serve(handle, '0.0.0.0', 8080, process_request=request):
        await finished.wait()
        await viewer.wait()

asyncio.run(main())
raise SystemExit(int(os.environ['GAME_EXIT_CODE']))
"""

_PLAYER = """
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zipfile import ZipFile

from websockets.asyncio.client import connect

url = os.environ['COWORLD_PLAYER_WS_URL']
slot = int(parse_qs(urlparse(url).query)['slot'][0])
upload = Path(urlparse(os.environ['COWORLD_PLAYER_ARTIFACT_UPLOAD_URL']).path)

async def main():
    if os.environ.get('PLAYER_UID'):
        os.setgid(int(os.environ['PLAYER_UID']))
        os.setuid(int(os.environ['PLAYER_UID']))
    auxiliary = upload.parent / 'root-owned'
    auxiliary.mkdir(mode=0o700)
    (auxiliary / 'temporary').write_bytes(b'private data')
    (upload.parent / 'unfinished.tmp').write_bytes(b'auxiliary data')
    with ZipFile(upload, 'w') as archive:
        archive.writestr('checkpoint', 'initial')
    async with connect(url) as ws:
        await ws.send('ready')
        await ws.recv()
        names = [f'policy_artifact_{1 - slot}.zip', f'logs/policy_agent_{1 - slot}.log',
                 'config.json', 'results.json', 'replay']
        exposed = []
        for name in names:
            path = upload.parent / name
            if path.is_file():
                path.read_bytes()
                path.write_bytes(b'tampered')
                exposed.append(name)
        # A checkpoint writer may use an adjacent temporary file and atomic replacement.
        temporary = upload.with_suffix('.tmp')
        with ZipFile(temporary, 'w') as archive:
            archive.writestr('checkpoint', 'latest')
            archive.writestr('slot', str(slot))
            archive.writestr('exposed.json', json.dumps(exposed))
        temporary.replace(upload)
        await ws.send('uploaded')
        await ws.recv()

asyncio.run(main())
"""


@pytest.mark.parametrize("player_uid", [0, 12345])
@pytest.mark.parametrize("game_exit_code", [0, 1])
def test_local_player_artifact_isolation(tmp_path: Path, game_exit_code: int, player_uid: int) -> None:
    image = os.environ.get("COWORLD_ARTIFACT_TEST_IMAGE")
    if image is None:
        pytest.skip("Set COWORLD_ARTIFACT_TEST_IMAGE to run the real Docker isolation test")
    artifacts = EpisodeArtifacts.create(tmp_path)
    artifacts.config_path.write_text(json.dumps({"tokens": ["slot-0", "slot-1"]}))
    artifacts.results_path.write_text('{"scores": [1, 2]}')
    artifacts.replay_path.write_bytes(b"game replay")
    spec = EpisodeRunSpec(
        game=RunnableLaunchSpec(image=image, run=("python", "-c", _GAME), env={"GAME_EXIT_CODE": str(game_exit_code)}),
        players=[
            PlayerLaunchSpec(image=image, run=("python", "-c", _PLAYER), env={"PLAYER_UID": str(player_uid)})
            for _ in range(2)
        ],
        tokens=["slot-0", "slot-1"],
        artifacts=artifacts,
        timeout_seconds=30,
        container_prefix="relh-artifact-isolation",
    )
    for _ in range(2):
        if game_exit_code:
            with pytest.raises(RunnerEpisodeError, match="Game container exited with status 1"):
                run_episode_containers(spec, verify_replay=False)
        else:
            run_episode_containers(spec, verify_replay=False)
        assert list(artifacts.workspace.glob("player-*")) == []

    for slot in range(2):
        with ZipFile(artifacts.policy_artifact_path(slot)) as archive:
            assert archive.read("checkpoint") == b"latest"
            assert archive.read("slot") == str(slot).encode()
            assert json.loads(archive.read("exposed.json")) == []
    assert artifacts.results_path.read_text() == '{"scores": [1, 2]}'
    assert artifacts.replay_path.read_bytes() == b"game replay"
    assert json.loads(artifacts.config_path.read_text()) == {"tokens": ["slot-0", "slot-1"]}
    assert all(artifacts.policy_log_path(slot).read_bytes() == b"" for slot in range(2))
