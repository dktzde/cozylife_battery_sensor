"""Local TCP client for a sleeping CozyLife temperature and humidity sensor.

The sensor sleeps most of the time and accepts a TCP connection on port 5555
only for a few seconds after it wakes up. While it is awake it answers the
status query ``cmd 2 / attr [1]`` with state frames that carry its
measurements. This client keeps at most one connection open and hands every
received frame to a listener.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import inspect
import json
import logging
import socket
import time
from typing import Any

from .const import BARE_JSON_PIDS
from .debug import summarize_frame

_LOGGER = logging.getLogger(__name__)
_RAW_LOGGER = logging.getLogger(f"{__name__}.raw")

COZYLIFE_PORT = 5555
CMD_INFO = 0
CMD_QUERY = 2
# Bounds one connection attempt. A sleeping sensor does not answer at all, so
# a short timeout keeps the probe cadence.
CONNECT_TIMEOUT_SECONDS = 0.2
# Let Linux expire unacknowledged writes to a sensor that went back to sleep;
# drain() alone could buffer requests for minutes on a stale socket.
TCP_USER_TIMEOUT_MS = 1000
WRITE_TIMEOUT_SECONDS = 1.0

FrameListener = Callable[[dict[str, Any]], Awaitable[None] | None]

_last_sn = 0


def _next_sn() -> str:
    """Return a unique, increasing sequence number for request correlation."""
    global _last_sn  # noqa: PLW0603 - module-wide counter by design
    _last_sn = max(int(time.time() * 1000), _last_sn + 1)
    return str(_last_sn)


class CozyLifeSensorClient:
    """One local TCP connection to a CozyLife sensor, opened on demand."""

    def __init__(
        self,
        ip_address: str,
        pid: str | None,
        *,
        port: int = COZYLIFE_PORT,
        connect_timeout: float = CONNECT_TIMEOUT_SECONDS,
    ) -> None:
        """Prepare the client; nothing is opened before the first request."""
        self._ip_address = ip_address
        self._pid = pid
        self._port = port
        self._connect_timeout = connect_timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._pending: dict[str, asyncio.Future[dict[str, Any] | None]] = {}
        self._listener: FrameListener | None = None
        # Wall-clock time of the current connection's successful connect.
        self.connected_at: float | None = None
        self.last_frame_received_at: float | None = None
        self.last_transport_error: str | None = None

    @property
    def ip_address(self) -> str:
        """Return the configured sensor address."""
        return self._ip_address

    @property
    def pid(self) -> str | None:
        """Return the product ID that selects the command framing."""
        return self._pid

    @pid.setter
    def pid(self, pid: str | None) -> None:
        self._pid = pid

    @property
    def is_connected(self) -> bool:
        """Return whether a connection is currently open."""
        return self._writer is not None and not self._writer.is_closing()

    def set_listener(self, listener: FrameListener | None) -> None:
        """Receive every frame the sensor sends."""
        self._listener = listener

    async def async_send_status(self) -> bool:
        """Ask for the sensor's state; open a connection first if needed.

        Returns True when the request was written. The answer arrives later
        through the listener.
        """
        return await self._async_write(CMD_QUERY, {"attr": [1]}) is not None

    async def async_read_identity(self, timeout: float = 2.0) -> dict[str, Any] | None:
        """Return the sensor's ``did``, ``pid`` and ``dtp``, or None if it does not answer."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any] | None] = loop.create_future()
        sn = await self._async_write(CMD_INFO, {}, future=future)
        if sn is None:
            return None
        try:
            message = await asyncio.wait_for(asyncio.shield(future), timeout)
        except TimeoutError:
            return None
        finally:
            self._pending.pop(sn, None)
            if not future.done():
                future.cancel()
        if not isinstance(message, dict) or not all(
            isinstance(message.get(key), str) and message.get(key)
            for key in ("did", "pid", "dtp")
        ):
            return None
        return message

    async def async_close(self) -> None:
        """Close the connection and stop its reader."""
        reader_task = self._reader_task
        self._reader_task = None
        self._disconnect()
        if reader_task is not None and reader_task is not asyncio.current_task():
            reader_task.cancel()
            try:
                await reader_task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001 - the reader already ended this connection
                _RAW_LOGGER.debug("CozyLife reader had failed", exc_info=True)

    def _encode(self, message: dict[str, Any]) -> bytes:
        encoded = json.dumps(message, separators=(",", ":")).encode("utf8")
        return encoded if self._pid in BARE_JSON_PIDS else encoded + b"\r\n"

    async def _async_write(
        self,
        cmd: int,
        msg: dict[str, Any],
        *,
        future: asyncio.Future[dict[str, Any] | None] | None = None,
    ) -> str | None:
        """Write one command and return its sequence number, or None on failure."""
        async with self._lock:
            writer = None
            sn = _next_sn()
            try:
                writer = await self._async_connect()
                payload = self._encode({"pv": 0, "cmd": cmd, "sn": sn, "msg": msg})
                if future is not None:
                    self._pending[sn] = future
                _RAW_LOGGER.debug("Sending CozyLife frame: %s", summarize_frame(payload))
                writer.write(payload)
                await asyncio.wait_for(writer.drain(), WRITE_TIMEOUT_SECONDS)
            except (TimeoutError, OSError) as err:
                self.last_transport_error = type(err).__name__
                self._pending.pop(sn, None)
                if writer is not None and writer is self._writer:
                    _RAW_LOGGER.debug("CozyLife write failed: %s", type(err).__name__)
                    self._disconnect()
                return None
            return sn

    async def _async_connect(self) -> asyncio.StreamWriter:
        """Return the open writer, connecting first if needed (lock held)."""
        if self._writer is not None and not self._writer.is_closing():
            return self._writer
        self._disconnect()
        _RAW_LOGGER.debug("Opening CozyLife socket")
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._ip_address, self._port),
                self._connect_timeout,
            )
        except (TimeoutError, OSError) as err:
            _RAW_LOGGER.debug("Could not open CozyLife socket: %s", type(err).__name__)
            raise
        sock = writer.get_extra_info("socket")
        option = getattr(socket, "TCP_USER_TIMEOUT", None)
        if sock is not None and option is not None:
            try:
                sock.setsockopt(socket.IPPROTO_TCP, option, TCP_USER_TIMEOUT_MS)
            except OSError:
                _RAW_LOGGER.debug("TCP_USER_TIMEOUT not supported")
        self._reader = reader
        self._writer = writer
        self.connected_at = time.time()
        self.last_transport_error = None
        self._reader_task = asyncio.get_running_loop().create_task(
            self._async_read_frames(reader, writer),
            name="cozylife-sensor-reader",
        )
        _RAW_LOGGER.debug("Connected CozyLife socket")
        return writer

    def _disconnect(self) -> None:
        """Close the socket and release callers waiting for an answer."""
        writer = self._writer
        self._reader = None
        self._writer = None
        self.connected_at = None
        if writer is not None:
            try:
                writer.close()
            except OSError:
                pass
        for future in self._pending.values():
            if not future.done():
                future.set_result(None)
        self._pending.clear()

    async def _async_read_frames(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Dispatch line-framed JSON from one connection until it ends."""
        try:
            while True:
                raw_frame = await reader.readline()
                if not raw_frame:
                    _RAW_LOGGER.debug("CozyLife socket closed by the sensor")
                    return
                if self._writer is not writer:
                    return
                try:
                    frame = json.loads(raw_frame.decode("utf8").strip())
                except (json.JSONDecodeError, UnicodeDecodeError) as err:
                    _LOGGER.debug("Ignoring invalid CozyLife frame: %s", type(err).__name__)
                    continue
                if not isinstance(frame, dict):
                    continue
                _RAW_LOGGER.debug("Received CozyLife frame: %s", summarize_frame(raw_frame))
                self.last_frame_received_at = time.time()

                sn = frame.get("sn")
                if isinstance(sn, (str, int)) and not isinstance(sn, bool):
                    future = self._pending.pop(str(sn), None)
                    if future is not None and not future.done():
                        message = frame.get("msg")
                        future.set_result(
                            message
                            if frame.get("res", 0) == 0 and isinstance(message, dict)
                            else None
                        )

                listener = self._listener
                if listener is not None:
                    try:
                        result = listener(frame)
                        if inspect.isawaitable(result):
                            await result
                    except Exception:  # noqa: BLE001 - keep the reader alive
                        _LOGGER.exception("Error handling a CozyLife frame")
        except (OSError, TimeoutError, ValueError) as err:
            # ValueError: a line longer than the stream limit.
            _RAW_LOGGER.debug("CozyLife connection ended: %s", type(err).__name__)
        finally:
            if self._writer is writer:
                self._disconnect()
