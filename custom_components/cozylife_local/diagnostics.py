"""Diagnostics: configuration, transport and the learned wake-up schedule."""

from __future__ import annotations

import time
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_DEVICE_ID, CONF_IP_ADDRESS, DOMAIN
from .coordinator import CozyLifeCoordinator

TO_REDACT = {CONF_IP_ADDRESS, CONF_DEVICE_ID}


def _age(timestamp: float | None, now: float) -> float | None:
    return None if timestamp is None else round(now - timestamp, 1)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return redacted settings plus the probe state; times are seconds ago."""
    now = time.time()
    diagnostics: dict[str, Any] = {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
    }
    coordinator: CozyLifeCoordinator | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )
    if coordinator is None:
        return diagnostics

    client = coordinator.client
    schedule = coordinator.schedule
    prober = coordinator.prober
    window = prober.current_window
    diagnostics["transport"] = {
        "connected": client.is_connected,
        "last_frame_seconds_ago": _age(client.last_frame_received_at, now),
        "last_error": client.last_transport_error,
    }
    diagnostics["wake_schedule"] = {
        "wake_window_enabled": prober.wake_window,
        "locked": schedule.locked,
        "period_seconds": schedule.period,
        "spread_seconds": schedule.spread,
        "intervals_seconds": schedule.intervals,
        "last_wake_seconds_ago": _age(schedule.last_wake, now),
        "missed_windows_in_a_row": schedule.missed_windows,
        "state": prober.state,
        "current_window": None
        if window is None
        else {
            "starts_in_seconds": round(window.start - now, 1),
            "expected_in_seconds": round(window.expected - now, 1),
            "ends_in_seconds": round(window.end - now, 1),
            "widened": window.widened,
        },
        "recent_probes": [
            {**result.as_dict(), "finished_seconds_ago": _age(result.finished_at, now)}
            for result in prober.history
        ],
    }
    return diagnostics
