"""Pod-local CDN proxy for games that cannot hold the shared relay client key."""

from __future__ import annotations

import asyncio
import os
import ssl
from urllib.parse import urlsplit

from coworld.runner.bedrock_sidecar_wiring import (
    EGRESS_RELAY_CA_FILE,
    EGRESS_RELAY_CLIENT_CERT_FILE,
    EGRESS_RELAY_CLIENT_KEY_FILE,
    GAME_EGRESS_PROXY_PORT,
)
from coworld.runner.relay_client import egress_relay_ssl_context


async def _pump(source: asyncio.StreamReader, destination: asyncio.StreamWriter) -> None:
    while data := await source.read(65536):
        destination.write(data)
        await destination.drain()


async def _handle(
    game_reader: asyncio.StreamReader,
    game_writer: asyncio.StreamWriter,
    *,
    relay_host: str,
    relay_port: int,
    allowed_targets: frozenset[str],
    tls_context: ssl.SSLContext,
    connection_limit: asyncio.Semaphore,
) -> None:
    async with connection_limit:
        relay_writer: asyncio.StreamWriter | None = None
        try:
            request = await asyncio.wait_for(game_reader.readuntil(b"\r\n\r\n"), timeout=5)
            line = request.split(b"\r\n", 1)[0]
            method, separator, rest = line.partition(b" ")
            target, separator2, version = rest.partition(b" ")
            if (
                method != b"CONNECT"
                or not separator
                or not separator2
                or version != b"HTTP/1.1"
                or target.decode("ascii") not in allowed_targets
            ):
                game_writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                await game_writer.drain()
                return
            relay_reader, relay_writer = await asyncio.open_connection(
                relay_host, relay_port, ssl=tls_context, server_hostname=relay_host
            )
            relay_writer.write(b"CONNECT " + target + b" HTTP/1.1\r\nHost: " + target + b"\r\n\r\n")
            await relay_writer.drain()
            response = await asyncio.wait_for(relay_reader.readuntil(b"\r\n\r\n"), timeout=10)
            if not response.startswith(b"HTTP/1.1 200 "):
                game_writer.write(response)
                await game_writer.drain()
                return
            game_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await game_writer.drain()
            tasks = [
                asyncio.create_task(_pump(game_reader, relay_writer)),
                asyncio.create_task(_pump(relay_reader, game_writer)),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.result()
        finally:
            game_writer.close()
            if relay_writer is not None:
                relay_writer.close()
            try:
                await game_writer.wait_closed()
            finally:
                if relay_writer is not None:
                    await relay_writer.wait_closed()


async def _main() -> None:
    relay_url = urlsplit(os.environ["COWORLD_GAME_EGRESS_UPSTREAM_RELAY_URL"])
    if relay_url.scheme != "https" or relay_url.hostname is None or relay_url.port is None:
        raise ValueError("game egress upstream relay must be an https URL with host and port")
    allowed_targets = frozenset(os.environ["COWORLD_GAME_EGRESS_ALLOWED_UPSTREAMS"].split(","))
    if not allowed_targets or any(not target.endswith(":443") for target in allowed_targets):
        raise ValueError("game egress upstreams must be exact host:443 targets")
    tls_context = egress_relay_ssl_context(
        ca_file=EGRESS_RELAY_CA_FILE,
        cert_file=EGRESS_RELAY_CLIENT_CERT_FILE,
        key_file=EGRESS_RELAY_CLIENT_KEY_FILE,
    )
    connection_limit = asyncio.Semaphore(4)
    server = await asyncio.start_server(
        lambda reader, writer: _handle(
            reader,
            writer,
            relay_host=relay_url.hostname,
            relay_port=relay_url.port,
            allowed_targets=allowed_targets,
            tls_context=tls_context,
            connection_limit=connection_limit,
        ),
        host="127.0.0.1",
        port=GAME_EGRESS_PROXY_PORT,
    )
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(_main())
