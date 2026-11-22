"""Learn when a sleeping sensor wakes up and plan short probe windows.

Pure Python without Home Assistant, so it can be tested on its own. All times
are wall-clock seconds (``time.time()``), which keeps the learned state valid
across Home Assistant restarts.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import median
from typing import Any

# Reports closer together than this belong to the same wake-up.
SAME_WAKE_SECONDS = 300.0
# The period is the median of this many recent intervals.
PERIOD_SAMPLES = 5
# After this many missed windows in a row the schedule forgets what it learned
# and the caller searches continuously again.
MAX_MISSED_WINDOWS = 3
# Intervals outside this range are not a report period (clock jumps, glitches).
MIN_PERIOD_SECONDS = 60.0
MAX_PERIOD_SECONDS = 24 * 3600.0
# Never assume a smaller wake-up jitter per period than this.
MIN_SPREAD_SECONDS = 1.0
# Upper bound for the extra margin added when several periods passed without
# a wake-up being seen.
MAX_EXTRA_MARGIN_SECONDS = 300.0


@dataclass(frozen=True)
class WakeWindow:
    """Time span worth probing around one expected wake-up."""

    start: float
    expected: float
    end: float
    # True when the window is wider than configured (after a miss, a too
    # tight window or several periods without a seen wake-up).
    widened: bool


class WakeSchedule:
    """Track the report period of one sleeping sensor.

    The schedule is unlocked until two separate wake-ups have been measured.
    While unlocked, the caller probes continuously.
    """

    def __init__(
        self,
        lead: float,
        tail: float,
        *,
        fallback_lead: float,
        fallback_tail: float,
        max_missed: int = MAX_MISSED_WINDOWS,
    ) -> None:
        """Start without any knowledge of the sensor's wake-ups."""
        if lead < 0 or tail <= 0:
            raise ValueError("lead must not be negative and tail must be positive")
        self.lead = float(lead)
        self.tail = float(tail)
        self.fallback_lead = max(float(fallback_lead), self.lead)
        self.fallback_tail = max(float(fallback_tail), self.tail)
        self.max_missed = max(1, int(max_missed))
        self._last_wake: float | None = None
        # Whether the last wake-up time is exact (the sensor woke while being
        # probed) or only an upper bound (it was already awake).
        self._last_exact = False
        self._intervals: list[float] = []
        self._missed = 0
        self._widen_next = False

    @property
    def period(self) -> float | None:
        """Return the learned report period, if known."""
        return median(self._intervals) if self._intervals else None

    @property
    def spread(self) -> float:
        """Return how far single periods deviated from the learned one."""
        period = self.period
        if period is None:
            return MIN_SPREAD_SECONDS
        return max(
            MIN_SPREAD_SECONDS,
            max(abs(interval - period) for interval in self._intervals),
        )

    @property
    def locked(self) -> bool:
        """Return whether the next wake-up can be predicted."""
        return self.period is not None and self._last_wake is not None

    @property
    def last_wake(self) -> float | None:
        """Return the time of the last seen wake-up."""
        return self._last_wake

    @property
    def missed_windows(self) -> int:
        """Return the number of windows missed in a row."""
        return self._missed

    @property
    def intervals(self) -> list[float]:
        """Return the recent intervals the period is learned from."""
        return list(self._intervals)

    def record_wake(self, at: float, *, exact: bool = True) -> bool:
        """Record a wake-up at ``at``; return False if it belongs to the last one.

        ``exact`` is False when the sensor was already awake when probing
        started. Then ``at`` is only an upper bound: it moves the schedule but
        is not used to learn the period, and the next window is widened.
        """
        last = self._last_wake
        if last is not None and 0 <= at - last < SAME_WAKE_SECONDS:
            return False
        if last is not None and exact and self._last_exact:
            interval = self._interval(at - last)
            if interval is not None:
                self._intervals = [*self._intervals, interval][-PERIOD_SAMPLES:]
        self._last_wake = at
        self._last_exact = exact
        self._missed = 0
        self._widen_next = not exact
        return True

    def record_missed_window(self) -> None:
        """Record a window that ended without a wake-up."""
        self._missed += 1
        self._widen_next = True
        if self._missed >= self.max_missed:
            self.reset()

    def reset(self) -> None:
        """Forget everything learned."""
        self._last_wake = None
        self._last_exact = False
        self._intervals = []
        self._missed = 0
        self._widen_next = False

    def next_window(self, now: float) -> WakeWindow | None:
        """Return the first window that ends after ``now``, or None if unlocked."""
        period = self.period
        last = self._last_wake
        if period is None or last is None:
            return None
        elapsed = now - last
        cycles = max(1, math.floor((elapsed - self.tail) / period) + 1)
        expected = last + cycles * period

        lead, tail = self.lead, self.tail
        widened = self._widen_next
        if widened:
            lead, tail = self.fallback_lead, self.fallback_tail
        # Each period without a seen wake-up adds the observed jitter once.
        extra = min(MAX_EXTRA_MARGIN_SECONDS, (cycles - 1) * self.spread)
        if extra > 0:
            widened = True
            lead += extra
            tail += extra
        return WakeWindow(expected - lead, expected, expected + tail, widened)

    def as_dict(self) -> dict[str, Any]:
        """Return the state for persistent storage."""
        return {
            "last": self._last_wake,
            "last_exact": self._last_exact,
            "period": self.period,
            "intervals": list(self._intervals),
            "missed": self._missed,
            "widen_next": self._widen_next,
        }

    def restore(self, data: Any) -> None:
        """Load state saved by ``as_dict`` (or by the older add-on integration)."""
        self.reset()
        if not isinstance(data, dict):
            return
        intervals = [
            float(value)
            for value in data.get("intervals") or []
            if _is_number(value) and MIN_PERIOD_SECONDS <= value <= MAX_PERIOD_SECONDS
        ][-PERIOD_SAMPLES:]
        period = data.get("period")
        if not intervals and _is_number(period) and (
            MIN_PERIOD_SECONDS <= period <= MAX_PERIOD_SECONDS
        ):
            intervals = [float(period)]
        last = data.get("last")
        self._intervals = intervals
        self._last_wake = float(last) if _is_number(last) else None
        # Older saved states were measured while probing continuously.
        self._last_exact = bool(data.get("last_exact", True))
        missed = data.get("missed", 0)
        self._missed = int(missed) if _is_number(missed) else 0
        self._widen_next = bool(data.get("widen_next", False))

    def _interval(self, gap: float) -> float | None:
        """Return one period from a gap that may span missed wake-ups."""
        period = self.period
        cycles = 1 if period is None else max(1, round(gap / period))
        interval = gap / cycles
        if not MIN_PERIOD_SECONDS <= interval <= MAX_PERIOD_SECONDS:
            return None
        return interval


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
