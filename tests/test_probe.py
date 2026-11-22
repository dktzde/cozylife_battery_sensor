"""Tests for the probe loop with a simulated sleeping sensor (scaled-down time)."""

from __future__ import annotations

import asyncio
import logging
import time

import pytest

from cozylife_local import wake_schedule
from cozylife_local.probe import WakeProber
from cozylife_local.wake_schedule import WakeSchedule

LOGGER = logging.getLogger("test_probe")


@pytest.fixture(autouse=True)
def _small_time_scale(monkeypatch: pytest.MonkeyPatch) -> None:
    """Allow periods of a second instead of an hour."""
    monkeypatch.setattr(wake_schedule, "MIN_PERIOD_SECONDS", 0.1)
    monkeypatch.setattr(wake_schedule, "SAME_WAKE_SECONDS", 0.2)
    monkeypatch.setattr(wake_schedule, "MIN_SPREAD_SECONDS", 0.0)


class FakeSensor:
    """Accepts a connection only while awake and then reports once."""

    def __init__(self, awake: list[tuple[float, float]], report_delay: float = 0.01) -> None:
        self.awake = awake
        self.report_delay = report_delay
        self.prober: WakeProber | None = None
        self.connected_at: float | None = None
        self.requests = 0
        self.closes = 0
        self._reported = False

    @property
    def is_connected(self) -> bool:
        return self.connected_at is not None

    async def async_send_status(self) -> bool:
        self.requests += 1
        now = time.time()
        if self.connected_at is None:
            if not any(start <= now < end for start, end in self.awake):
                return False
            self.connected_at = now
            self._reported = False
        if not self._reported and self.prober is not None:
            self._reported = True
            asyncio.get_running_loop().call_later(
                self.report_delay, self.prober.report_received
            )
        return True

    async def async_close(self) -> None:
        self.closes += 1
        self.connected_at = None


def _prober(sensor: FakeSensor, schedule: WakeSchedule, **kwargs) -> WakeProber:
    prober = WakeProber(
        sensor,
        schedule,
        wake_window=kwargs.pop("wake_window", True),
        logger=LOGGER,
        attempt_interval=0.02,
        settle_seconds=0.01,
        rest_after_report=0.01,
        connected_grace=0.05,
        **kwargs,
    )
    sensor.prober = prober
    return prober


def _schedule(lead: float, tail: float) -> WakeSchedule:
    return WakeSchedule(lead, tail, fallback_lead=lead * 2, fallback_tail=tail * 2)


def test_searches_continuously_until_the_sensor_wakes() -> None:
    async def run() -> None:
        now = time.time()
        sensor = FakeSensor([(now + 0.15, now + 0.5)])
        prober = _prober(sensor, _schedule(0.1, 0.2))
        result = await prober.async_run_once()
        assert result.window is None
        assert result.exact
        assert result.wake_at == pytest.approx(now + 0.15, abs=0.05)
        assert result.attempts > 3
        assert sensor.closes == 1
        assert prober.schedule.last_wake == result.wake_at

    asyncio.run(run())


def test_sensor_already_awake_is_not_an_exact_wake() -> None:
    async def run() -> None:
        now = time.time()
        sensor = FakeSensor([(now - 1.0, now + 1.0)])
        prober = _prober(sensor, _schedule(0.1, 0.2))
        result = await prober.async_run_once()
        assert result.wake_at is not None
        assert not result.exact
        assert result.attempts == 1

    asyncio.run(run())


def test_waits_for_the_window_and_catches_the_wake() -> None:
    async def run() -> None:
        now = time.time()
        schedule = _schedule(0.1, 0.2)
        # learned period 1.0 s, next wake expected at now + 0.4
        schedule.restore({"last": now - 0.6, "intervals": [1.0]})
        sensor = FakeSensor([(now + 0.4, now + 0.6)])
        prober = _prober(sensor, schedule)
        result = await prober.async_run_once()
        assert result.window is not None
        assert result.window.expected == pytest.approx(now + 0.4)
        assert result.exact
        # probing started about lead seconds before the wake
        assert result.lead == pytest.approx(0.1, abs=0.05)
        # nothing was sent before the window opened
        assert result.attempts == sensor.requests
        assert result.attempts <= 0.1 / 0.02 + 2
        assert schedule.period == pytest.approx(1.0, abs=0.03)

    asyncio.run(run())


def test_missed_window_is_recorded_and_closed() -> None:
    async def run() -> None:
        now = time.time()
        schedule = _schedule(0.05, 0.1)
        schedule.restore({"last": now - 0.8, "intervals": [1.0]})
        sensor = FakeSensor([])
        prober = _prober(sensor, schedule)
        result = await prober.async_run_once()
        assert result.wake_at is None
        assert time.time() >= now + 0.2 + 0.1
        assert schedule.missed_windows == 1
        assert sensor.closes == 1
        nxt = schedule.next_window(time.time())
        assert nxt is not None and nxt.widened

    asyncio.run(run())


def test_late_report_on_open_connection_gets_grace() -> None:
    async def run() -> None:
        now = time.time()
        schedule = _schedule(0.05, 0.1)
        schedule.restore({"last": now - 0.8, "intervals": [1.0]})
        # wakes right at the end of the window; the report takes 0.03 s
        sensor = FakeSensor([(now + 0.29, now + 0.5)], report_delay=0.03)
        prober = _prober(sensor, schedule)
        result = await prober.async_run_once()
        assert result.wake_at is not None

    asyncio.run(run())


def test_after_report_hook_runs_before_the_connection_closes() -> None:
    async def run() -> None:
        now = time.time()
        sensor = FakeSensor([(now + 0.05, now + 0.5)])
        seen: list[bool] = []

        async def after_report() -> None:
            seen.append(sensor.is_connected)

        prober = _prober(sensor, _schedule(0.1, 0.2), after_report=after_report)
        await prober.async_run_once()
        assert seen == [True]
        assert not sensor.is_connected

    asyncio.run(run())


def test_wake_window_off_probes_without_waiting() -> None:
    async def run() -> None:
        now = time.time()
        schedule = _schedule(0.1, 0.2)
        schedule.restore({"last": now - 0.2, "intervals": [1.0]})
        sensor = FakeSensor([(now + 0.1, now + 0.3)])
        prober = _prober(sensor, schedule, wake_window=False)
        result = await prober.async_run_once()
        assert result.window is None
        assert result.wake_at == pytest.approx(now + 0.1, abs=0.05)

    asyncio.run(run())


def test_on_change_is_called_for_wakes_and_misses() -> None:
    async def run() -> None:
        now = time.time()
        changes: list[int] = []
        schedule = _schedule(0.05, 0.1)
        schedule.restore({"last": now - 0.8, "intervals": [1.0]})
        sensor = FakeSensor([])
        prober = _prober(sensor, schedule, on_change=lambda: changes.append(1))
        await prober.async_run_once()
        assert changes == [1]

    asyncio.run(run())
