from __future__ import annotations

import shutil
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

STATIC_REPLAY_BUNDLE_CSP = (
    "default-src 'none'; script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; "
    "font-src 'self' data:; connect-src 'self' https: http:; media-src 'self' blob:; "
    "worker-src 'self' blob:; frame-src 'self'"
)
LOCAL_REPLAY_PATH = "/_coworld/replay"


def source_replay_viewer_bundle(package_root: Path, bundle: str) -> Path:
    if bundle.startswith("sha256:"):
        raise ValueError(
            "A content-addressed replay viewer bundle is not present in the local Coworld package. "
            "Use `coworld replay-open <episode-request-id> --hosted` for an uploaded Coworld."
        )

    root = package_root.resolve()
    bundle_dir = (root / bundle).resolve()
    if not bundle_dir.is_relative_to(root):
        raise ValueError(f"Replay viewer bundle escapes the Coworld package: {bundle_dir}")
    if not bundle_dir.is_dir():
        raise ValueError(f"Replay viewer bundle is not a directory: {bundle_dir}")
    if not (bundle_dir / "index.html").is_file():
        raise ValueError(f"Replay viewer bundle has no index.html: {bundle_dir}")
    if any(path.is_symlink() for path in bundle_dir.rglob("*")):
        raise ValueError(f"Replay viewer bundle cannot contain symlinks: {bundle_dir}")
    return bundle_dir


class _LocalReplayRequestHandler(SimpleHTTPRequestHandler):
    server: LocalReplayViewerServer

    def do_GET(self) -> None:
        if urlsplit(self.path).path == LOCAL_REPLAY_PATH:
            self._serve_replay(head_only=False)
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        if urlsplit(self.path).path == LOCAL_REPLAY_PATH:
            self._serve_replay(head_only=True)
            return
        super().do_HEAD()

    def _serve_replay(self, *, head_only: bool) -> None:
        size = self.server.replay_path.stat().st_size
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head_only:
            with self.server.replay_path.open("rb") as replay:
                shutil.copyfileobj(replay, self.wfile)

    def end_headers(self) -> None:
        self.send_header("Content-Security-Policy", STATIC_REPLAY_BUNDLE_CSP)
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def log_message(self, _format: str, *_args: Any) -> None:
        pass


class LocalReplayViewerServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, bundle_dir: Path, replay_path: Path, *, port: int) -> None:
        self.bundle_dir = bundle_dir
        self.replay_path = replay_path
        super().__init__(("127.0.0.1", port), _LocalReplayRequestHandler)

    def finish_request(self, request: Any, client_address: Any) -> None:
        _LocalReplayRequestHandler(request, client_address, self, directory=str(self.bundle_dir))

    @property
    def viewer_url(self) -> str:
        replay_url = f"http://127.0.0.1:{self.server_port}{LOCAL_REPLAY_PATH}"
        return f"http://127.0.0.1:{self.server_port}/index.html#{urlencode({'replay': replay_url})}"
