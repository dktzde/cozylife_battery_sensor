"""Tests for the TCP client against a local fake sensor."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from cozylife_local.cozylife_api import CozyLifeSensorClient

STATE_FRAME = {"cmd": 10, "res": 0, "msg": {"attr": [4, 8, 9], "data": {"4": 55, "8": 213, "9": 600}}}


async def _read_command(reader: asyncio.StreamReader, buffer: bytearray) -> dict[str, Any]:
    """Read one JSON command, with or without a line ending."""
    decoder = json.JSONDecoder()
    while True:
        text = buffer.decode("utf8").lstrip()
        if text:
            try:
                command, end = decoder.raw_decode(text)
            except json.JSONDecodeError:
                pass
            else:
                rest = text[end:].encode("utf8")
                buffer[:] = rest
                return command
        chunk = await reader.read(4096)
        if not chunk:
            raise EOFError
        buffer.extend(chunk)


class FakeSensorServer:
    """Answers status queries with a state frame and info queries with an identity."""

    def __init__(self) -> None:
        self.commands: list[dict[str, Any]] = []
        self.server: asyncio.Server | None = None
        self.port = 0

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        assert self.server is not None
        self.server.close()
        await self.server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        buffer = bytearray()
        try:
            while True:
                command = await _read_command(reader, buffer)
                self.commands.append(command)
                if command["cmd"] == 2:
                    reply = STATE_FRAME
                else:
                    reply = {
                        "cmd": 0,
                        "sn": command["sn"],
                        "res": 0,
                        "msg": {"did": "abc123", "pid": "Z4tRml", "dtp": "02"},
                    }
                writer.write(json.dumps(reply).encode() + b"\r\n")
                await writer.drain()
        except (EOFError, ConnectionError):
            pass
        finally:
            writer.close()


def _run(coro_factory) -> None:
    async def run() -> None:
        server = FakeSensorServer()
        await server.start()
        try:
            await coro_factory(server)
        finally:
            await server.stop()

    asyncio.run(run())


def test_status_request_delivers_the_state_frame() -> None:
    async def scenario(server: FakeSensorServer) -> None:
        frames: list[dict[str, Any]] = []
        received = asyncio.Event()

        def listener(frame: dict[str, Any]) -> None:
            frames.append(frame)
            received.set()

        client = CozyLifeSensorClient("127.0.0.1", "Z4tRml", port=server.port)
        client.set_listener(listener)
        assert await client.async_send_status()
        assert client.is_connected
        assert client.connected_at is not None
        await asyncio.wait_for(received.wait(), 2)
        assert frames[0]["msg"]["data"]["8"] == 213
        assert server.commands[0]["cmd"] == 2
        assert server.commands[0]["msg"] == {"attr": [1]}
        await client.async_close()
        assert not client.is_connected
        assert client.connected_at is None

    _run(scenario)


@pytest.mark.parametrize(("pid", "crlf"), [("Z4tRml", False), ("nrQdBz", True)])
def test_command_framing_depends_on_the_model(pid: str, crlf: bool) -> None:
    async def scenario(server: FakeSensorServer) -> None:
        captured: list[bytes] = []
        original = asyncio.StreamWriter.write

        def spy(self: asyncio.StreamWriter, data: bytes) -> None:
            if data.startswith(b'{"pv"'):
                captured.append(bytes(data))
            original(self, data)

        client = CozyLifeSensorClient("127.0.0.1", pid, port=server.port)
        asyncio.StreamWriter.write = spy  # type: ignore[method-assign]
        try:
            assert await client.async_send_status()
        finally:
            asyncio.StreamWriter.write = original  # type: ignore[method-assign]
        await client.async_close()
        assert captured
        assert captured[0].endswith(b"\r\n") is crlf

    _run(scenario)


def test_identity_is_read_by_sequence_number() -> None:
    async def scenario(server: FakeSensorServer) -> None:
        client = CozyLifeSensorClient("127.0.0.1", "Z4tRml", port=server.port)
        identity = await client.async_read_identity(2)
        await client.async_close()
        assert identity == {"did": "abc123", "pid": "Z4tRml", "dtp": "02"}

    _run(scenario)


def test_refused_connection_is_reported() -> None:
    async def run() -> None:
        server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        server.close()
        await server.wait_closed()
        client = CozyLifeSensorClient("127.0.0.1", "Z4tRml", port=port)
        assert await client.async_send_status() is False
        assert client.last_transport_error == "ConnectionRefusedError"
        assert not client.is_connected
        assert await client.async_read_identity(0.2) is None

    asyncio.run(run())


def test_sensor_closing_the_connection_is_noticed() -> None:
    async def run() -> None:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await reader.read(100)
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        client = CozyLifeSensorClient("127.0.0.1", "Z4tRml", port=port)
        try:
            assert await client.async_send_status()
            for _ in range(50):
                if not client.is_connected:
                    break
                await asyncio.sleep(0.02)
            assert not client.is_connected
        finally:
            await client.async_close()
            server.close()
            await server.wait_closed()

    asyncio.run(run())


def test_invalid_frames_do_not_stop_the_reader() -> None:
    async def run() -> None:
        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await reader.read(100)
            writer.write(b"not json\r\n[1, 2]\r\n" + json.dumps(STATE_FRAME).encode() + b"\r\n")
            await writer.drain()
            await asyncio.sleep(0.5)
            writer.close()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        frames: list[dict[str, Any]] = []
        received = asyncio.Event()

        async def listener(frame: dict[str, Any]) -> None:
            frames.append(frame)
            received.set()

        client = CozyLifeSensorClient("127.0.0.1", "Z4tRml", port=port)
        client.set_listener(listener)
        try:
            assert await client.async_send_status()
            await asyncio.wait_for(received.wait(), 2)
            assert frames == [STATE_FRAME]
        finally:
            await client.async_close()
            server.close()
            await server.wait_closed()

    asyncio.run(run())
