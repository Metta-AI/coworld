"""Serve the real game protocol and declare a configured terminal interruption."""

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from websockets.http11 import Request, Response
from websockets.sync.server import ServerConnection, serve

config = json.loads(Path(urlparse(os.environ["COGAME_CONFIG_URI"]).path).read_text())


def http_response(connection: ServerConnection, request: Request) -> Response | None:
    if request.path == "/global":
        return None
    return connection.respond(200, "failure declaration fixture")


def viewer(connection: ServerConnection) -> None:
    connection.send("ready")
    declaration = {"message": "fixture interruption", "failed_policy_index": 0}
    if config["kind"] != "legacy":
        declaration["kind"] = config["kind"]
    destination = Path(urlparse(os.environ["COGAME_PLAYER_FAILURE_URI"]).path)
    staged = destination.with_suffix(".tmp")
    staged.write_text(json.dumps(declaration))
    staged.replace(destination)
    for _ in connection:
        pass


with serve(viewer, "0.0.0.0", 8080, process_request=http_response) as server:
    server.serve_forever()
