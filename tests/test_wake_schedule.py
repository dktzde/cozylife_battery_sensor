"""Tests for the learned wake-up schedule."""

from __future__ import annotations

import pytest

from cozylife_local import wake_schedule
from cozylife_local.wake_schedule import WakeSchedule

PERIOD = 3525.0


def _schedule(lead: float = 7.0, tail: float = 30.0) -> WakeSchedule:
    return WakeSchedule(lead, tail, fallback_lead=20.0, fallback_tail=60.0)


def _learned(*wakes: float, lead: float = 7.0, tail: float = 30.0) -> WakeSchedule:
    schedule = _schedule(lead, tail)
    for at in wakes:
        schedule.record_wake(at)
    return schedule


def test_unlocked_until_two_wakes() -> None:
    schedule = _schedule()
    assert schedule.next_window(0.0) is None
    schedule.record_wake(1000.0)
    assert not schedule.locked
    assert schedule.next_window(1001.0) is None
    schedule.record_wake(1000.0 + PERIOD)
    assert schedule.locked
    assert schedule.period == PERIOD


def test_window_around_expected_wake() -> None:
    schedule = _learned(0.0, PERIOD)
    window = schedule.next_window(PERIOD + 10.0)
    assert window is not None
    assert window.expected == 2 * PERIOD
    assert window.start == 2 * PERIOD - 7.0
    assert window.end == 2 * PERIOD + 30.0
    assert not window.widened


def test_window_still_open_inside_tail() -> None:
    schedule = _learned(0.0, PERIOD)
    window = schedule.next_window(2 * PERIOD + 29.0)
    assert window is not None
    assert window.expected == 2 * PERIOD
    later = schedule.next_window(2 * PERIOD + 30.0)
    assert later is not None
    assert later.expected == 3 * PERIOD


def test_reports_of_the_same_wake_are_ignored() -> None:
    schedule = _learned(0.0, PERIOD)
    assert schedule.record_wake(PERIOD + 2.0) is False
    assert schedule.intervals == [PERIOD]


def test_period_is_median_of_recent_intervals() -> None:
    schedule = _schedule()
    at = 0.0
    schedule.record_wake(at)
    for interval in (3520.0, 3530.0, 3524.0, 3526.0, 3525.0, 3600.0):
        at += interval
        schedule.record_wake(at)
    assert schedule.intervals == [3530.0, 3524.0, 3526.0, 3525.0, 3600.0]
    assert schedule.period == 3526.0


def test_gap_over_missed_wakes_counts_as_several_periods() -> None:
    schedule = _learned(0.0, PERIOD)
    schedule.record_wake(PERIOD + 2 * 3527.0)
    assert schedule.intervals == [PERIOD, 3527.0]


def test_missed_window_widens_the_next_one() -> None:
    schedule = _learned(0.0, PERIOD)
    schedule.record_missed_window()
    window = schedule.next_window(2 * PERIOD + 30.0)
    assert window is not None
    assert window.widened
    assert window.expected == 3 * PERIOD
    # fallback lead/tail plus one period of jitter (minimum 1 s)
    assert window.start == pytest.approx(3 * PERIOD - 20.0 - 1.0)
    assert window.end == pytest.approx(3 * PERIOD + 60.0 + 1.0)


def test_three_missed_windows_reset_the_schedule() -> None:
    schedule = _learned(0.0, PERIOD)
    for _ in range(3):
        schedule.record_missed_window()
    assert not schedule.locked
    assert schedule.next_window(10 * PERIOD) is None


def test_caught_wake_clears_misses_and_widening() -> None:
    schedule = _learned(0.0, PERIOD)
    schedule.record_missed_window()
    schedule.record_wake(3 * PERIOD)
    assert schedule.missed_windows == 0
    window = schedule.next_window(3 * PERIOD + 31.0)
    assert window is not None and not window.widened


def test_inexact_wake_is_not_learned_and_widens() -> None:
    schedule = _learned(0.0, PERIOD)
    schedule.record_wake(2 * PERIOD - 3.0, exact=False)
    assert schedule.intervals == [PERIOD]
    window = schedule.next_window(2 * PERIOD + 31.0)
    assert window is not None and window.widened
    assert window.start == pytest.approx(3 * PERIOD - 3.0 - 20.0)
    # the interval after an inexact wake is not learned either
    schedule.record_wake(3 * PERIOD - 3.0)
    assert schedule.intervals == [PERIOD]


def test_extra_margin_grows_with_unseen_periods() -> None:
    schedule = _learned(0.0, 3523.0, 3523.0 + 3527.0)
    assert schedule.spread == pytest.approx(2.0)
    last = 3523.0 + 3527.0
    window = schedule.next_window(last + 4 * schedule.period + 31.0)
    assert window is not None and window.widened
    assert window.expected == pytest.approx(last + 5 * schedule.period)
    assert window.start == pytest.approx(window.expected - 7.0 - 4 * 2.0)


def test_extra_margin_is_capped() -> None:
    schedule = _learned(0.0, PERIOD)
    window = schedule.next_window(1000 * PERIOD)
    assert window is not None
    assert window.expected - window.start == pytest.approx(
        7.0 + wake_schedule.MAX_EXTRA_MARGIN_SECONDS
    )


def test_round_trip_through_storage() -> None:
    schedule = _learned(0.0, 3524.0, 3524.0 + 3526.0)
    schedule.record_missed_window()
    restored = _schedule()
    restored.restore(schedule.as_dict())
    assert restored.as_dict() == schedule.as_dict()
    assert restored.next_window(10_000.0) == schedule.next_window(10_000.0)


def test_restores_the_older_add_on_format() -> None:
    restored = _schedule()
    restored.restore(
        {"last": 1000.0, "period": 3525.0, "intervals": [3523.5, 3525.8, 3525.0]}
    )
    assert restored.locked
    assert restored.period == 3525.0
    window = restored.next_window(1001.0)
    assert window is not None and window.expected == pytest.approx(4525.0)
    assert not window.widened


@pytest.mark.parametrize(
    "data",
    [None, [], "x", {"last": "x", "intervals": ["a"]}, {"last": 5.0, "intervals": [1.0]}],
)
def test_broken_storage_leaves_the_schedule_unlocked(data: object) -> None:
    restored = _schedule()
    restored.restore(data)
    assert not restored.locked


def test_implausible_intervals_are_ignored() -> None:
    schedule = _learned(0.0)
    two_days = 2 * 24 * 3600.0
    schedule.record_wake(two_days)
    assert schedule.intervals == []
    schedule.record_wake(two_days + PERIOD)
    assert schedule.intervals == [PERIOD]


def test_invalid_margins_are_rejected() -> None:
    with pytest.raises(ValueError):
        WakeSchedule(-1.0, 30.0, fallback_lead=20.0, fallback_tail=60.0)
    with pytest.raises(ValueError):
        WakeSchedule(7.0, 0.0, fallback_lead=20.0, fallback_tail=60.0)
