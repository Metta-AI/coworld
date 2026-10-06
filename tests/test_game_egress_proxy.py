import asyncio
import signal
import ssl
from unittest.mock import MagicMock

import pytest

from coworld.runner import game_egress_proxy


@pytest.mark.asyncio
@pytest.mark.parametrize("drain_completes", [True, False])
async def test_signal_stops_accepting_and_drains_connections(monkeypatch, drain_completes):
    handlers = {}
    listening = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    server = MagicMock()

    class Server:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def close(self):
            server.close()

        async def wait_closed(self):
            await finished.wait()

    async def tunnel(*args, **kwargs):
        try:
            await release.wait()
        finally:
            finished.set()

    async def start_server(connected, **kwargs):
        connected(None, None)
        listening.set()
        return Server()

    monkeypatch.setenv("COWORLD_GAME_EGRESS_UPSTREAM_RELAY_URL", "https://relay.test:443")
    monkeypatch.setenv("COWORLD_GAME_EGRESS_ALLOWED_UPSTREAMS", "cdn.test:443")
    monkeypatch.setattr(game_egress_proxy, "egress_relay_ssl_context", lambda **kwargs: None)
    monkeypatch.setattr(game_egress_proxy, "_handle", tunnel)
    monkeypatch.setattr(game_egress_proxy, "_DRAIN_SECONDS", 0.05)
    monkeypatch.setattr(game_egress_proxy.asyncio, "start_server", start_server)
    monkeypatch.setattr(
        asyncio.get_running_loop(), "add_signal_handler", lambda signum, fn: handlers.update({signum: fn})
    )
    task = asyncio.create_task(game_egress_proxy._main())
    await listening.wait()
    handlers[signal.SIGTERM]()
    await asyncio.sleep(0)
    server.close.assert_called_once()
    assert not task.done()
    if drain_completes:
        release.set()
    await asyncio.wait_for(task, 1)
    assert finished.is_set()


class _Reader:
    def __init__(self, header: bytes, *, read_error: Exception | None = None) -> None:
        self.header = header
        self.read_error = read_error
        self.header_read = False

    async def readuntil(self, separator: bytes) -> bytes:
        assert separator == b"\r\n\r\n"
        self.header_read = True
        return self.header

    async def read(self, size: int) -> bytes:
        if size == 1:
            self.header_read = True
            first_byte, self.header = self.header[:1], self.header[1:]
            return first_byte
        assert size == 65536
        if self.read_error is not None:
            raise self.read_error
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class _Writer:
    def __init__(self, name: str, close_events: list[str], *, wait_error: Exception | None = None) -> None:
        self.name = name
        self.close_events = close_events
        self.wait_error = wait_error
        self.writes: list[bytes] = []
        self.transport = self

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.close_events.append(f"{self.name}.close")

    def abort(self) -> None:
        self.close_events.append(f"{self.name}.abort")

    async def wait_closed(self) -> None:
        self.close_events.append(f"{self.name}.wait_closed")
        if self.wait_error is not None:
            raise self.wait_error


@pytest.mark.asyncio
async def test_empty_readiness_connection_closes_without_opening_relay() -> None:
    reader = asyncio.StreamReader()
    reader.feed_eof()
    writer = MagicMock(spec=asyncio.StreamWriter)
    await game_egress_proxy._handle(
        reader,
        writer,
        relay_host="relay.test",
        relay_port=443,
        allowed_targets=frozenset({"cdn.test:443"}),
        tls_context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        connection_limit=asyncio.Semaphore(1),
    )
    writer.write.assert_not_called()
    writer.close.assert_called_once()
    writer.wait_closed.assert_awaited_once()


@pytest.mark.asyncio
async def test_connection_limit_is_acquired_before_reading_request() -> None:
    reader = _Reader(b"GET / HTTP/1.1\r\n\r\n")
    writer = _Writer("game", [])
    connection_limit = asyncio.Semaphore(0)

    task = asyncio.create_task(
        game_egress_proxy._handle(
            reader,  # type: ignore[arg-type]
            writer,  # type: ignore[arg-type]
            relay_host="relay.test",
            relay_port=443,
            allowed_targets=frozenset({"cdn.test:443"}),
            tls_context=None,  # type: ignore[arg-type]
            connection_limit=connection_limit,
        )
    )
    await asyncio.sleep(0)

    assert not reader.header_read

    connection_limit.release()
    await task


@pytest.mark.asyncio
async def test_proxy_admits_twelve_concurrent_long_lived_tunnels(monkeypatch: pytest.MonkeyPatch) -> None:
    relay_connections = 0
    all_connected = asyncio.Event()

    async def open_connection(*args: object, **kwargs: object) -> tuple[_Reader, _Writer]:
        nonlocal relay_connections
        relay_connections += 1
        if relay_connections == 12:
            all_connected.set()
        return _Reader(b"HTTP/1.1 200 Connection Established\r\n\r\n"), _Writer("relay", [])

    monkeypatch.setattr(game_egress_proxy.asyncio, "open_connection", open_connection)
    connection_limit = asyncio.Semaphore(game_egress_proxy._MAX_CONCURRENT_TUNNELS)
    game_writers = [_Writer("game", []) for _ in range(12)]
    tasks = [
        asyncio.create_task(
            game_egress_proxy._handle(
                _Reader(b"CONNECT cdn.test:443 HTTP/1.1\r\n\r\n"),  # type: ignore[arg-type]
                game_writer,  # type: ignore[arg-type]
                relay_host="relay.test",
                relay_port=443,
                allowed_targets=frozenset({"cdn.test:443"}),
                tls_context=None,  # type: ignore[arg-type]
                connection_limit=connection_limit,
            )
        )
        for game_writer in game_writers
    ]
    try:
        await asyncio.wait_for(all_connected.wait(), timeout=1)
        assert all(writer.writes == [b"HTTP/1.1 200 Connection Established\r\n\r\n"] for writer in game_writers)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_client_reset_closes_relay_before_awaiting_client_close(monkeypatch: pytest.MonkeyPatch) -> None:
    close_events: list[str] = []
    game_reader = _Reader(b"CONNECT cdn.test:443 HTTP/1.1\r\n\r\n", read_error=ConnectionResetError())
    game_writer = _Writer("game", close_events)
    relay_reader = _Reader(b"HTTP/1.1 200 Connection Established\r\n\r\n")
    relay_writer = _Writer("relay", close_events)

    async def open_connection(*args: object, **kwargs: object) -> tuple[_Reader, _Writer]:
        return relay_reader, relay_writer

    monkeypatch.setattr(game_egress_proxy.asyncio, "open_connection", open_connection)

    with pytest.raises(ConnectionResetError):
        await game_egress_proxy._handle(
            game_reader,  # type: ignore[arg-type]
            game_writer,  # type: ignore[arg-type]
            relay_host="relay.test",
            relay_port=443,
            allowed_targets=frozenset({"cdn.test:443"}),
            tls_context=None,  # type: ignore[arg-type]
            connection_limit=asyncio.Semaphore(4),
        )

    assert close_events == ["game.close", "relay.close", "game.wait_closed", "relay.wait_closed"]


@pytest.mark.asyncio
async def test_game_close_reset_still_awaits_relay_close(monkeypatch: pytest.MonkeyPatch) -> None:
    close_events: list[str] = []
    game_reader = _Reader(b"CONNECT cdn.test:443 HTTP/1.1\r\n\r\n", read_error=ConnectionResetError())
    game_writer = _Writer("game", close_events, wait_error=ConnectionResetError())
    relay_reader = _Reader(b"HTTP/1.1 200 Connection Established\r\n\r\n")
    relay_writer = _Writer("relay", close_events)

    async def open_connection(*args: object, **kwargs: object) -> tuple[_Reader, _Writer]:
        return relay_reader, relay_writer

    monkeypatch.setattr(game_egress_proxy.asyncio, "open_connection", open_connection)

    with pytest.raises(ConnectionResetError):
        await game_egress_proxy._handle(
            game_reader,  # type: ignore[arg-type]
            game_writer,  # type: ignore[arg-type]
            relay_host="relay.test",
            relay_port=443,
            allowed_targets=frozenset({"cdn.test:443"}),
            tls_context=None,  # type: ignore[arg-type]
            connection_limit=asyncio.Semaphore(4),
        )

    assert close_events == ["game.close", "relay.close", "game.wait_closed", "relay.wait_closed"]


@pytest.mark.asyncio
async def test_drain_cancellation_aborts_a_transport_already_closing():
    closing = asyncio.Event()

    class ClosingWriter(_Writer):
        async def wait_closed(self):
            closing.set()
            await asyncio.Event().wait()

    writer = ClosingWriter("game", [])
    task = asyncio.create_task(
        game_egress_proxy._handle(
            _Reader(b"GET / HTTP/1.1\r\n\r\n"),  # type: ignore[arg-type]
            writer,  # type: ignore[arg-type]
            relay_host="relay.test",
            relay_port=443,
            allowed_targets=frozenset({"cdn.test:443"}),
            tls_context=None,  # type: ignore[arg-type]
            connection_limit=asyncio.Semaphore(1),
        )
    )
    await asyncio.wait_for(closing.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert writer.close_events == ["game.close", "game.abort"]
