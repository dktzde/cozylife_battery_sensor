"""Config, reconfigure and options flows."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cozylife_local.const import DOMAIN

READ_IDENTITY = "custom_components.cozylife_local.config_flow._async_read_identity"


async def test_sleeping_sensor_gets_a_placeholder_id(
    hass: HomeAssistant, sleeping_sensor: dict[str, AsyncMock]
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    with patch(READ_IDENTITY, AsyncMock(return_value=None)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"ip_address": "192.0.2.20", "pid": "Z4tRml"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["device_id"] == "sleeping_sensor_192.0.2.20"
    assert result["data"]["pid"] == "Z4tRml"


async def test_awake_sensor_uses_its_device_id(
    hass: HomeAssistant, sleeping_sensor: dict[str, AsyncMock]
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    identity = {"did": "feedfacefeedface0001", "pid": "Z4tRml", "dtp": "02"}
    with patch(READ_IDENTITY, AsyncMock(return_value=identity)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"ip_address": "192.0.2.21", "pid": "Z4tRml"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "feedfacefeedface0001"


async def test_invalid_ip_and_wrong_model(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"ip_address": "not-an-ip", "pid": "Z4tRml"}
    )
    assert result["errors"] == {"ip_address": "invalid_ip"}

    identity = {"did": "x1", "pid": "nrQdBz", "dtp": "02"}
    with patch(READ_IDENTITY, AsyncMock(return_value=identity)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"ip_address": "192.0.2.22", "pid": "Z4tRml"}
        )
    assert result["errors"] == {"pid": "wrong_model"}


async def test_same_ip_is_rejected(hass: HomeAssistant) -> None:
    MockConfigEntry(
        domain=DOMAIN, data={"ip_address": "192.0.2.23", "device_id": "a"}
    ).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"ip_address": "192.0.2.23", "pid": "Z4tRml"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_changes_the_ip(
    hass: HomeAssistant, sleeping_sensor: dict[str, AsyncMock]
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"ip_address": "192.0.2.24", "device_id": "abc", "pid": "Z4tRml"},
    )
    entry.add_to_hass(hass)
    MockConfigEntry(
        domain=DOMAIN, data={"ip_address": "192.0.2.29", "device_id": "other"}
    ).add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"ip_address": "192.0.2.29"}
    )
    assert result["errors"] == {"ip_address": "ip_in_use"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"ip_address": "192.0.2.25"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["ip_address"] == "192.0.2.25"
    # measurements wait until the sensor at the new address proves its ID
    assert entry.data["verify_identity"] is True


async def test_options_flow(
    hass: HomeAssistant, sleeping_sensor: dict[str, AsyncMock]
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"ip_address": "192.0.2.26", "device_id": "abc", "pid": "Z4tRml"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "sensor_wake_window": True,
            "wake_lead_seconds": 7.5,
            "wake_tail_seconds": 30,
            "filter_outliers": False,
            "temperature_radius": 2.0,
            "humidity_radius": 10.0,
            "enable_debug": False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["wake_lead_seconds"] == 7.5
    coordinator = hass.data[DOMAIN][entry.entry_id]
    assert coordinator.schedule.lead == 7.5


async def test_known_device_id_of_a_sleeping_sensor(
    hass: HomeAssistant, sleeping_sensor: dict[str, AsyncMock]
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert "device_id" in result["data_schema"].schema
    with patch(READ_IDENTITY, AsyncMock(return_value=None)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"ip_address": "192.0.2.27", "pid": "Z4tRml", "device_id": "bad id!"},
        )
        assert result["errors"] == {"device_id": "invalid_device_id"}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"ip_address": "192.0.2.27", "pid": "Z4tRml", "device_id": "0123abcd"},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["device_id"] == "0123abcd"
    assert result["result"].unique_id == "0123abcd"


async def test_known_device_id_must_match_an_awake_sensor(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    identity = {"did": "feedface", "pid": "Z4tRml", "dtp": "02"}
    with patch(READ_IDENTITY, AsyncMock(return_value=identity)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"ip_address": "192.0.2.28", "pid": "Z4tRml", "device_id": "0123abcd"},
        )
    assert result["errors"] == {"device_id": "device_id_mismatch"}

