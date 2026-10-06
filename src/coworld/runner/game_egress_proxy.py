"""Pod-local CDN proxy for games that cannot hold the shared relay client key."""

from __future__ import annotations

import asyncio
import os
import signal
import ssl
from urllib.parse import urlsplit

from coworld.runner.llm_sidecar_wiring import (
    EGRESS_RELAY_CA_FILE,
    EGRESS_RELAY_CLIENT_CERT_FILE,
    EGRESS_RELAY_CLIENT_KEY_FILE,
    GAME_EGRESS_PROXY_PORT,
)
from coworld.runner.relay_client import egress_relay_ssl_context

_MAX_CONCURRENT_TUNNELS = 32
_DRAIN_SECONDS = 10.0


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
    relay_writer: asyncio.StreamWriter | None = None
    try:
        async with connection_limit:
            async with asyncio.timeout(5):
                first_byte = await game_reader.read(1)
                if not first_byte:
                    return  # TCP readiness probes close without sending a request.
                request = first_byte + await game_reader.readuntil(b"\r\n\r\n")
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
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            for task in done:
                task.result()
    finally:
        game_writer.close()
        if relay_writer is not None:
            relay_writer.close()
        task = asyncio.current_task()
        assert task is not None
        try:
            if not task.cancelling():
                closing = [game_writer.wait_closed()]
                if relay_writer is not None:
                    closing.append(relay_writer.wait_closed())
                await asyncio.gather(*closing)
        finally:
            if task.cancelling():
                game_writer.transport.abort()
                if relay_writer is not None:
                    relay_writer.transport.abort()


async def _main() -> None:
    relay_url = urlsplit(os.environ["COWORLD_GAME_EGRESS_UPSTREAM_RELAY_URL"])
    relay_host, relay_port = relay_url.hostname, relay_url.port
    if relay_url.scheme != "https" or relay_host is None or relay_port is None:
        raise ValueError("game egress upstream relay must be an https URL with host and port")
    allowed_targets = frozenset(os.environ["COWORLD_GAME_EGRESS_ALLOWED_UPSTREAMS"].split(","))
    if not allowed_targets or any(not target.endswith(":443") for target in allowed_targets):
        raise ValueError("game egress upstreams must be exact host:443 targets")
    tls_context = egress_relay_ssl_context(
        ca_file=EGRESS_RELAY_CA_FILE,
        cert_file=EGRESS_RELAY_CLIENT_CERT_FILE,
        key_file=EGRESS_RELAY_CLIENT_KEY_FILE,
    )
    connection_limit = asyncio.Semaphore(_MAX_CONCURRENT_TUNNELS)
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stopped.set)
    connections: set[asyncio.Task[None]] = set()

    def connected(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.create_task(
            _handle(
                reader,
                writer,
                relay_host=relay_host,
                relay_port=relay_port,
                allowed_targets=allowed_targets,
                tls_context=tls_context,
                connection_limit=connection_limit,
            )
        )
        connections.add(task)
        task.add_done_callback(connections.remove)

    server = await asyncio.start_server(
        connected,
        host="127.0.0.1",
        port=GAME_EGRESS_PROXY_PORT,
    )
    async with server:
        await stopped.wait()
        server.close()
        if connections:
            _, pending = await asyncio.wait(connections, timeout=_DRAIN_SECONDS)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(_main())
