"""Fixtures for the Home Assistant tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
import pytest

from custom_components.cozylife_local.const import DOMAIN

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the integration from custom_components/."""


@pytest.fixture
async def sleeping_sensor(hass: HomeAssistant) -> AsyncGenerator[dict[str, AsyncMock]]:
    """A sensor that never answers (it sleeps).

    Unloads the entries before the patches end, so no probe loop reaches the
    real network during teardown.
    """
    client = "custom_components.cozylife_local.cozylife_api.CozyLifeSensorClient"
    with (
        patch(f"{client}.async_send_status", AsyncMock(return_value=False)) as send,
        patch(f"{client}.async_read_identity", AsyncMock(return_value=None)) as identity,
        patch(f"{client}.async_close", AsyncMock()) as close,
    ):
        yield {"send": send, "identity": identity, "close": close}
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.state is ConfigEntryState.LOADED:
                await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
