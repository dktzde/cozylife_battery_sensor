"""Probe a sleeping sensor so that Home Assistant catches it while it is awake.

Pure asyncio without Home Assistant, so it can be tested on its own.

Without a learned schedule (or with the wake window turned off) the prober
asks for the sensor's state every ``attempt_interval`` seconds until a report
arrives, like the upstream integration. With a learned schedule it stays
silent until shortly before the expected wake-up and probes only inside that
window.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
import time
from typing import Any, Protocol

from .wake_schedule import WakeSchedule, WakeWindow

# One status request (and connection attempt) per this many seconds.
ATTEMPT_INTERVAL_SECONDS = 0.25
# A window does not end while a connection opened inside it waits for its
# report; give the report this much extra time.
CONNECTED_GRACE_SECONDS = 5.0
# After the first report, stop asking and keep the connection this long so
# the rest of the burst (and an identity check) can arrive, then close it.
SETTLE_SECONDS = 2.0
# Without a window, pause this long after a report before searching again, so
# the same wake-up is not caught twice.
REST_AFTER_REPORT_SECONDS = 30.0
# How many recent probe results the diagnostics keep.
HISTORY_LENGTH = 24


class SensorTransport(Protocol):
    """What the prober needs from the TCP client."""

    connected_at: float | None

    @property
    def is_connected(self) -> bool: ...  # noqa: D102

    async def async_send_status(self) -> bool: ...  # noqa: D102

    async def async_close(self) -> None: ...  # noqa: D102


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of one search for a wake-up."""

    # Wall-clock time the search ended (report received or window over).
    finished_at: float
    # Time of the connection that delivered the report; None when missed.
    wake_at: float | None
    # False when the sensor was already awake when probing began.
    exact: bool
    # Seconds between the start of probing and the connection.
    lead: float | None
    attempts: int
    window: WakeWindow | None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly summary for diagnostics."""
        return {
            "finished_at": round(self.finished_at, 3),
            "caught": self.wake_at is not None,
            "exact": self.exact,
            "lead_seconds": None if self.lead is None else round(self.lead, 2),
            "attempts": self.attempts,
            "window": None
            if self.window is None
            else {
                "start": round(self.window.start, 3),
                "expected": round(self.window.expected, 3),
                "end": round(self.window.end, 3),
                "widened": self.window.widened,
            },
        }


class WakeProber:
    """Run the probe loop for one sensor."""

    def __init__(
        self,
        transport: SensorTransport,
        schedule: WakeSchedule,
        *,
        wake_window: bool,
        logger: logging.Logger,
        on_change: Callable[[], None] | None = None,
        after_report: Callable[[], Awaitable[None]] | None = None,
        attempt_interval: float = ATTEMPT_INTERVAL_SECONDS,
        settle_seconds: float = SETTLE_SECONDS,
        rest_after_report: float = REST_AFTER_REPORT_SECONDS,
        connected_grace: float = CONNECTED_GRACE_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Prepare the loop; ``async_run`` starts it."""
        self._transport = transport
        self.schedule = schedule
        self.wake_window = wake_window
        self._logger = logger
        self._on_change = on_change
        self._after_report = after_report
        self._attempt_interval = attempt_interval
        self._settle_seconds = settle_seconds
        self._rest_after_report = rest_after_report
        self._connected_grace = connected_grace
        self._clock = clock
        self._report = asyncio.Event()
        self.history: deque[ProbeResult] = deque(maxlen=HISTORY_LENGTH)
        self.current_window: WakeWindow | None = None
        self.state = "idle"

    def report_received(self) -> None:
        """Tell the prober that a valid report arrived."""
        self._report.set()

    async def async_run(self) -> None:
        """Probe forever; cancel the task to stop."""
        while True:
            await self.async_run_once()

    async def async_run_once(self) -> ProbeResult:
        """Wait for the next window (if any), probe it and learn from it."""
        window = (
            self.schedule.next_window(self._clock()) if self.wake_window else None
        )
        self.current_window = window
        if window is not None:
            delay = window.start - self._clock()
            if delay > 0:
                self.state = "waiting"
                await asyncio.sleep(delay)
        self.state = "probing" if window is not None else "searching"
        try:
            result = await self._async_probe(window)
        finally:
            self.state = "idle"
        self.history.append(result)

        if result.wake_at is None:
            await self._transport.async_close()
            self.schedule.record_missed_window()
            self._logger.info(
                "Sensor did not wake up in its window (%s missed in a row)",
                self.schedule.missed_windows or self.schedule.max_missed,
            )
            if not self.schedule.locked:
                self._logger.warning(
                    "Sensor missed %s windows in a row; searching continuously again",
                    self.schedule.max_missed,
                )
            self._changed()
            return result

        self.schedule.record_wake(result.wake_at, exact=result.exact)
        period = self.schedule.period
        self._logger.debug(
            "Caught wake-up after %.2f s of probing (%s attempts, %s, window %s); period %s",
            result.lead if result.lead is not None else -1.0,
            result.attempts,
            "exact" if result.exact else "sensor was already awake",
            "widened"
            if window is not None and window.widened
            else ("normal" if window is not None else "none"),
            f"{period:.1f} s" if period is not None else "not learned yet",
        )
        self._changed()
        await self._async_settle()
        if window is None:
            await asyncio.sleep(self._rest_after_report)
        return result

    async def _async_probe(self, window: WakeWindow | None) -> ProbeResult:
        """Ask for the state until a report arrives or the window ends."""
        loop = asyncio.get_running_loop()
        self._report.clear()
        started_at = self._clock()
        attempts = 0
        connected_on_attempt: int | None = None
        while True:
            now = self._clock()
            if window is not None and now >= window.end and not (
                self._transport.is_connected
                and now < window.end + self._connected_grace
            ):
                return ProbeResult(now, None, False, None, attempts, window)

            attempt_started = loop.time()
            was_connected = self._transport.is_connected
            await self._transport.async_send_status()
            attempts += 1
            if not was_connected and self._transport.is_connected:
                connected_on_attempt = attempts
            remaining = self._attempt_interval - (loop.time() - attempt_started)
            try:
                await asyncio.wait_for(self._report.wait(), max(remaining, 0.01))
            except TimeoutError:
                continue

            finished_at = self._clock()
            wake_at = self._transport.connected_at or finished_at
            # Connected on the very first attempt: the sensor was already
            # awake, so the real wake-up was earlier than ``wake_at``.
            exact = connected_on_attempt is not None and connected_on_attempt > 1
            return ProbeResult(
                finished_at, wake_at, exact, wake_at - started_at, attempts, window
            )

    async def _async_settle(self) -> None:
        """Let the burst finish, run the follow-up hook, then close."""
        try:
            if self._after_report is not None:
                try:
                    await self._after_report()
                except Exception:  # noqa: BLE001 - never stop the probe loop
                    self._logger.exception("Error after a sensor report")
            await asyncio.sleep(self._settle_seconds)
        finally:
            await self._transport.async_close()

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change()
