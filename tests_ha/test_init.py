"""Setup, entities, storage and cleanup inside Home Assistant."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cozylife_local.const import DOMAIN
from custom_components.cozylife_local.diagnostics import (
    async_get_config_entry_diagnostics,
)

DEVICE_ID = "0123456789abcdef0123"
ENTRY_DATA = {
    "ip_address": "192.0.2.10",
    "device_id": DEVICE_ID,
    "pid": "Z4tRml",
    "device_type_code": "02",
    "dpids": ["4", "8", "9"],
}


def _entry(**data: Any) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={**ENTRY_DATA, **data},
        unique_id=data.get("device_id", DEVICE_ID),
        options={"sensor_wake_window": True},
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_entities_keep_the_upstream_unique_ids(
    hass: HomeAssistant, sleeping_sensor: dict[str, AsyncMock]
) -> None:
    entry = _entry()
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED

    registry = er.async_get(hass)
    unique_ids = {
        e.unique_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    assert unique_ids == {
        f"{DEVICE_ID}_temperature",
        f"{DEVICE_ID}_humidity",
        f"{DEVICE_ID}_battery",
        f"{DEVICE_ID}_ip_address",
    }
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, DEVICE_ID), entry.entry_id
    )
    assert device is not None
    assert device.model == "Z4tRml"

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_existing_entity_ids_survive(
    hass: HomeAssistant, sleeping_sensor: dict[str, AsyncMock]
) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor",
        DOMAIN,
        f"{DEVICE_ID}_temperature",
        config_entry=entry,
        suggested_object_id="my_reference_temperature",
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.my_reference_temperature") is not None


async def test_report_updates_the_sensors(
    hass: HomeAssistant, sleeping_sensor: dict[str, AsyncMock]
) -> None:
    entry = _entry()
    await _setup(hass, entry)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator._async_handle_frame(
        {"cmd": 10, "res": 0, "msg": {"data": {"4": 55, "8": 213, "9": 600, "14": 3600}}}
    )
    await hass.async_block_till_done()
    registry = er.async_get(hass)

    def state(key: str) -> str:
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{DEVICE_ID}_{key}")
        assert entity_id is not None
        return hass.states.get(entity_id).state

    assert state("temperature") == "21.3"
    assert state("humidity") == "55.0"
    assert state("battery") == "60.0"
    assert state("ip_address") == "192.0.2.10"

    # a frame without measurements does not touch the values
    await coordinator._async_handle_frame(
        {"cmd": 10, "res": 0, "msg": {"data": {"12": 1, "13": 0}}}
    )
    # an invalid humidity keeps the previous value
    await coordinator._async_handle_frame(
        {"cmd": 10, "res": 0, "msg": {"data": {"4": 255, "8": 214}}}
    )
    await hass.async_block_till_done()
    assert state("temperature") == "21.4"
    assert state("humidity") == "55.0"


async def test_learned_schedule_is_restored(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    sleeping_sensor: dict[str, AsyncMock],
) -> None:
    entry = _entry()
    hass_storage[f"{DOMAIN}_wake_{entry.entry_id}"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"{DOMAIN}_wake_{entry.entry_id}",
        "data": {"last": time.time() - 100, "period": 3525.0, "intervals": [3525.0]},
    }
    await _setup(hass, entry)
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.schedule.locked
    assert coordinator.prober.state == "waiting"
    # waiting for the window: nothing is sent to the sensor
    assert sleeping_sensor["send"].await_count == 0

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["entry"]["ip_address"] == "**REDACTED**"
    assert diagnostics["wake_schedule"]["period_seconds"] == 3525.0

    assert await hass.config_entries.async_unload(entry.entry_id)
    saved = hass_storage[f"{DOMAIN}_wake_{entry.entry_id}"]["data"]
    assert saved["period"] == 3525.0


async def test_discovery_controller_entry_is_removed(
    hass: HomeAssistant, sleeping_sensor: dict[str, AsyncMock]
) -> None:
    hass.set_state(CoreState.not_running)
    controller = MockConfigEntry(
        domain=DOMAIN,
        data={"entry_type": "discovery_controller"},
        unique_id="cozylife_local_discovery_controller",
    )
    controller.add_to_hass(hass)
    sensor = _entry()
    sensor.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert controller.state is ConfigEntryState.LOADED

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    assert hass.config_entries.async_get_entry(controller.entry_id) is None
    assert sensor.state is ConfigEntryState.LOADED


async def test_empty_device_can_be_removed(
    hass: HomeAssistant, sleeping_sensor: dict[str, AsyncMock]
) -> None:
    entry = _entry()
    await _setup(hass, entry)
    device_registry = dr.async_get(hass)
    stale = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "sleeping_sensor_192.0.2.10")},
    )
    live = device_registry.async_get_device_by_identifier(
        (DOMAIN, DEVICE_ID), entry.entry_id
    )
    component = hass.data["integrations"][DOMAIN].get_component()
    assert await component.async_remove_config_entry_device(hass, entry, stale)
    assert not await component.async_remove_config_entry_device(hass, entry, live)


async def test_placeholder_identity_is_replaced(
    hass: HomeAssistant, sleeping_sensor: dict[str, AsyncMock]
) -> None:
    placeholder = "sleeping_sensor_192.0.2.10"
    entry = _entry(device_id=placeholder)
    await _setup(hass, entry)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{placeholder}_temperature")
    assert entity_id is not None

    sleeping_sensor["identity"].return_value = {
        "did": DEVICE_ID,
        "pid": "Z4tRml",
        "dtp": "02",
    }
    coordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator._async_after_report()
    await hass.async_block_till_done()

    assert entry.data["device_id"] == DEVICE_ID
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{DEVICE_ID}_temperature") == entity_id
    device_registry = dr.async_get(hass)
    assert (
        device_registry.async_get_device_by_identifier((DOMAIN, DEVICE_ID), entry.entry_id)
        is not None
    )
    assert (
        device_registry.async_get_device_by_identifier((DOMAIN, placeholder), entry.entry_id)
        is None
    )
    assert entry.state is ConfigEntryState.LOADED
