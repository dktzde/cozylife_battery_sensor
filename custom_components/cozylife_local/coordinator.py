"""Coordinator: receives the sensor's reports and runs the probe loop."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE_CODE,
    CONF_PID,
    DEFAULT_HUMIDITY_RADIUS,
    DEFAULT_TEMPERATURE_RADIUS,
    DEFAULT_WAKE_LEAD_SECONDS,
    DEFAULT_WAKE_TAIL_SECONDS,
    DEFAULT_WAKE_WINDOW,
    DOMAIN,
    FALLBACK_WAKE_LEAD_SECONDS,
    FALLBACK_WAKE_TAIL_SECONDS,
    OPTION_FILTER_OUTLIERS,
    OPTION_HUMIDITY_RADIUS,
    OPTION_TEMPERATURE_RADIUS,
    OPTION_WAKE_LEAD,
    OPTION_WAKE_TAIL,
    OPTION_WAKE_WINDOW,
    PLACEHOLDER_DEVICE_ID_PREFIX,
    SENSOR_HUMIDITY,
    SENSOR_TEMPERATURE,
)
from .cozylife_api import CozyLifeSensorClient
from .debug import summarize_dpids
from .measurement_filter import MeasurementFilter
from .probe import WakeProber
from .wake_schedule import WakeSchedule

_LOGGER = logging.getLogger(__name__)

# Same key and format as before, so a learned schedule survives the switch
# from the upstream integration with the separate wake-window add-on.
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_wake_{{entry_id}}"
SAVE_DELAY_SECONDS = 10
IDENTITY_TIMEOUT_SECONDS = 1.5

ENVIRONMENT_MEASUREMENTS = {
    SENSOR_TEMPERATURE: "temperature",
    SENSOR_HUMIDITY: "humidity",
}


def is_valid_measurement(dpid: str, value: Any) -> bool:
    """Return whether a raw temperature or humidity value looks real."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if dpid == SENSOR_TEMPERATURE:
        return -400 <= value <= 800
    if dpid == SENSOR_HUMIDITY:
        return 0 <= value <= 100
    return True


class CozyLifeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Hold the latest report of one sensor; the sensor pushes, nothing polls."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: CozyLifeSensorClient,
    ) -> None:
        """Set up the probe loop for the configured sensor."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name="CozyLife sensor",
            update_interval=None,
        )
        self.client = client
        options = entry.options
        self._filter = (
            MeasurementFilter() if options.get(OPTION_FILTER_OUTLIERS, False) else None
        )
        self._radii = {
            SENSOR_TEMPERATURE: float(
                options.get(OPTION_TEMPERATURE_RADIUS, DEFAULT_TEMPERATURE_RADIUS)
            )
            * 10,
            SENSOR_HUMIDITY: float(
                options.get(OPTION_HUMIDITY_RADIUS, DEFAULT_HUMIDITY_RADIUS)
            ),
        }
        self.schedule = WakeSchedule(
            float(options.get(OPTION_WAKE_LEAD, DEFAULT_WAKE_LEAD_SECONDS)),
            float(options.get(OPTION_WAKE_TAIL, DEFAULT_WAKE_TAIL_SECONDS)),
            fallback_lead=FALLBACK_WAKE_LEAD_SECONDS,
            fallback_tail=FALLBACK_WAKE_TAIL_SECONDS,
        )
        self.prober = WakeProber(
            client,
            self.schedule,
            wake_window=bool(options.get(OPTION_WAKE_WINDOW, DEFAULT_WAKE_WINDOW)),
            logger=_LOGGER,
            on_change=self._async_schedule_save,
            after_report=self._async_after_report,
        )
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY.format(entry_id=entry.entry_id)
        )
        self._probe_task: asyncio.Task[None] | None = None
        client.set_listener(self._async_handle_frame)

    @property
    def device_id(self) -> str:
        """Return the device ID the entities are registered under."""
        return self.config_entry.data[CONF_DEVICE_ID]

    async def async_start(self) -> None:
        """Load the learned schedule and start probing."""
        try:
            stored = await self._store.async_load()
        except Exception:  # noqa: BLE001 - a broken file only costs re-learning
            _LOGGER.warning("Could not read the learned wake-up schedule; learning again")
            stored = None
        self.schedule.restore(stored)
        if self.schedule.locked:
            _LOGGER.debug(
                "Restored wake-up schedule: period %.1f s", self.schedule.period
            )
        self._probe_task = self.config_entry.async_create_background_task(
            self.hass, self.prober.async_run(), "cozylife sensor probe"
        )

    async def async_stop(self) -> None:
        """Stop probing, close the connection and save the schedule."""
        task, self._probe_task = self._probe_task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self.client.async_close()
        await self._store.async_save(self.schedule.as_dict())

    @callback
    def _async_schedule_save(self) -> None:
        self._store.async_delay_save(self.schedule.as_dict, SAVE_DELAY_SECONDS)

    async def _async_handle_frame(self, frame: dict[str, Any]) -> None:
        """Publish the measurements of one state frame."""
        if frame.get("res", 0) != 0:
            return
        message = frame.get("msg")
        state = message.get("data") if isinstance(message, dict) else None
        if not isinstance(state, dict) or not state:
            return
        received = {str(dpid): value for dpid, value in state.items()}
        received = {
            dpid: value
            for dpid, value in received.items()
            if dpid not in ENVIRONMENT_MEASUREMENTS or is_valid_measurement(dpid, value)
        }
        if not any(dpid in received for dpid in ENVIRONMENT_MEASUREMENTS):
            _LOGGER.debug(
                "Ignoring a frame without valid measurements (DPIDs %s)",
                summarize_dpids(state),
            )
            return
        # The sensor is awake and reported: the probe loop may stop, even if
        # the optional filter below rejects the values.
        self.prober.report_received()
        if self._filter is not None:
            received = self._filter.filter(frame.get("sn"), received, self._radii)
        _LOGGER.debug("Received sensor report with DPIDs %s", summarize_dpids(received))
        # Reports can be partial; keep earlier values of missing DPIDs.
        self.async_set_updated_data({**(self.data or {}), **received})

    async def _async_after_report(self) -> None:
        """Replace a placeholder device ID while the sensor is awake."""
        old_id = self.device_id
        if not old_id.startswith(PLACEHOLDER_DEVICE_ID_PREFIX):
            return
        info = await self.client.async_read_identity(IDENTITY_TIMEOUT_SECONDS)
        if info is None:
            return
        expected_pid = self.config_entry.data.get(CONF_PID)
        if expected_pid and info["pid"] != expected_pid:
            _LOGGER.warning(
                "Sensor reports product ID %s instead of the configured %s; "
                "keeping the placeholder identity",
                info["pid"],
                expected_pid,
            )
            return
        new_id = info["did"]
        self._async_migrate_identity(old_id, new_id)
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={
                **self.config_entry.data,
                CONF_DEVICE_ID: new_id,
                CONF_PID: info["pid"],
                CONF_DEVICE_TYPE_CODE: info["dtp"],
            },
        )
        _LOGGER.info("Verified the sensor's device ID; reloading the entry")
        self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)

    @callback
    def _async_migrate_identity(self, old_id: str, new_id: str) -> None:
        """Move entities and the device to the verified device ID."""
        entity_registry = er.async_get(self.hass)
        prefix = f"{old_id}_"
        for entry in er.async_entries_for_config_entry(
            entity_registry, self.config_entry.entry_id
        ):
            if not entry.unique_id.startswith(prefix):
                continue
            new_unique_id = f"{new_id}_{entry.unique_id.removeprefix(prefix)}"
            if entity_registry.async_get_entity_id(
                entry.domain, entry.platform, new_unique_id
            ):
                _LOGGER.warning(
                    "Keeping %s on its placeholder ID; the verified ID is in use",
                    entry.entity_id,
                )
                continue
            entity_registry.async_update_entity(
                entry.entity_id, new_unique_id=new_unique_id
            )

        device_registry = dr.async_get(self.hass)
        entry_id = self.config_entry.entry_id
        old_device = _device_by_identifier(device_registry, (DOMAIN, old_id), entry_id)
        if old_device is not None and not _device_by_identifier(
            device_registry, (DOMAIN, new_id), entry_id
        ):
            device_registry.async_update_device(
                old_device.id, new_identifiers={(DOMAIN, new_id)}
            )


def _device_by_identifier(
    registry: dr.DeviceRegistry, identifier: tuple[str, str], entry_id: str
) -> dr.DeviceEntry | None:
    """Look a device up by identifier within one config entry.

    Home Assistant 2026.10 replaced ``async_get_device`` with a per-entry lookup;
    keep older releases working.
    """
    if (getter := getattr(registry, "async_get_device_by_identifier", None)) is not None:
        return getter(identifier, entry_id)
    return registry.async_get_device(identifiers={identifier})
