import asyncio

import pytest

from coworld.runner import game_egress_proxy


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

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.close_events.append(f"{self.name}.close")

    async def wait_closed(self) -> None:
        self.close_events.append(f"{self.name}.wait_closed")
        if self.wait_error is not None:
            raise self.wait_error


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
