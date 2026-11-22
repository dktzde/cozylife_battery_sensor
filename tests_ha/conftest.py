"""Fixtures for the Home Assistant tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the integration from custom_components/."""


@pytest.fixture
def sleeping_sensor() -> Generator[dict[str, AsyncMock]]:
    """A sensor that never answers (it sleeps)."""
    client = "custom_components.cozylife_local.cozylife_api.CozyLifeSensorClient"
    with (
        patch(f"{client}.async_send_status", AsyncMock(return_value=False)) as send,
        patch(f"{client}.async_read_identity", AsyncMock(return_value=None)) as identity,
        patch(f"{client}.async_close", AsyncMock()) as close,
    ):
        yield {"send": send, "identity": identity, "close": close}
