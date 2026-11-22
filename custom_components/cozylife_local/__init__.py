"""CozyLife battery sensor: one sleeping Wi-Fi temperature and humidity sensor, locally."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_ENTRY_TYPE,
    CONF_IP_ADDRESS,
    CONF_PID,
    DEFAULT_PID,
    DISCOVERY_CONTROLLER_ENTRY_TYPE,
    DOMAIN,
    OPTION_ENABLE_DEBUG,
    PLATFORMS,
)
from .coordinator import CozyLifeCoordinator
from .cozylife_api import CozyLifeSensorClient

_LOGGER = logging.getLogger(__name__)
_DEBUG_ENTRY_IDS = "debug_entry_ids"

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


def _is_discovery_controller(entry: ConfigEntry) -> bool:
    return entry.data.get(CONF_ENTRY_TYPE) == DISCOVERY_CONTROLLER_ENTRY_TYPE


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Remove the UDP discovery entry that upstream releases created."""
    hass.data.setdefault(DOMAIN, {})

    @callback
    def _async_remove_discovery_controllers(_hass: HomeAssistant) -> None:
        for entry in hass.config_entries.async_entries(DOMAIN):
            if _is_discovery_controller(entry):
                _LOGGER.info("Removing the UDP discovery entry; this fork does not use discovery")
                hass.async_create_task(
                    hass.config_entries.async_remove(entry.entry_id),
                    "cozylife remove discovery entry",
                )

    async_at_started(hass, _async_remove_discovery_controllers)
    return True


@callback
def _async_update_debug_logging(hass: HomeAssistant, entry_id: str, enabled: bool) -> None:
    """Keep the package logger at debug while any entry asks for it."""
    debug_entry_ids: set[str] = hass.data[DOMAIN].setdefault(_DEBUG_ENTRY_IDS, set())
    if enabled:
        debug_entry_ids.add(entry_id)
    else:
        debug_entry_ids.discard(entry_id)
    logging.getLogger(__package__).setLevel(
        logging.DEBUG if debug_entry_ids else logging.NOTSET
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the sensor of one config entry."""
    hass.data.setdefault(DOMAIN, {})
    if _is_discovery_controller(entry):
        # Removed by async_setup once Home Assistant has started.
        return True

    _async_update_debug_logging(
        hass, entry.entry_id, entry.options.get(OPTION_ENABLE_DEBUG, False)
    )
    client = CozyLifeSensorClient(
        entry.data[CONF_IP_ADDRESS], entry.data.get(CONF_PID, DEFAULT_PID)
    )
    coordinator = CozyLifeCoordinator(hass, entry, client)
    hass.data[DOMAIN][entry.entry_id] = coordinator
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        await coordinator.async_start()
    except BaseException:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        await coordinator.async_stop()
        _async_update_debug_logging(hass, entry.entry_id, False)
        raise
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply changed options, a new address or a verified device ID."""
    coordinator: CozyLifeCoordinator | None = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator is not None and not coordinator.needs_reload():
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Stop probing and remove the entities."""
    if _is_discovery_controller(entry):
        return True
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: CozyLifeCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_stop()
        _async_update_debug_logging(hass, entry.entry_id, False)
    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Allow removing a device of this entry once it has no entities left.

    An identity change (placeholder ID to verified device ID) or an upstream
    release can leave an empty device behind.
    """
    return not er.async_entries_for_device(
        er.async_get(hass), device_entry.id, include_disabled_entities=True
    )
