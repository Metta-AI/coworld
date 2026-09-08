import json
import subprocess
from pathlib import Path

PAINTARENA_ROOT = Path(__file__).parents[1] / "src" / "coworld" / "examples" / "paintarena"


def test_paintarena_builds_static_replay_viewer(tmp_path: Path) -> None:
    manifest = json.loads((PAINTARENA_ROOT / "coworld_manifest_template.json").read_text())
    assert manifest["game"]["replay_viewer"] == {
        "bundle": "build/static-replay-viewer",
        "replay_compression": "gzip",
    }

    output = tmp_path / "viewer"
    output.mkdir()
    (output / "sentinel").touch()
    subprocess.run([PAINTARENA_ROOT / "tools" / "build_replay_viewer.sh", output], check=True)

    assert sorted(path.name for path in output.iterdir()) == ["index.html"]
    html = (output / "index.html").read_text()
    assert 'location.hash.slice(1)).get("replay")' in html
    assert "new DecompressionStream(compression)" in html
    assert "message = await receiveContainerReplay()" in html
    assert "new WebSocket(websocketUrl)" in html
    assert 'type: "ready"' in html
