"""Config flow: add the sensor by its IP address, tune it in the options."""

from __future__ import annotations

import ipaddress
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_DEVICE_ID,
    CONF_DEVICE_TYPE_CODE,
    CONF_DPIDS,
    CONF_IP_ADDRESS,
    CONF_PID,
    DEFAULT_HUMIDITY_RADIUS,
    DEFAULT_PID,
    DEFAULT_TEMPERATURE_RADIUS,
    DEFAULT_WAKE_LEAD_SECONDS,
    DEFAULT_WAKE_TAIL_SECONDS,
    DEFAULT_WAKE_WINDOW,
    DOMAIN,
    OPTION_ENABLE_DEBUG,
    OPTION_FILTER_OUTLIERS,
    OPTION_HUMIDITY_RADIUS,
    OPTION_TEMPERATURE_RADIUS,
    OPTION_WAKE_LEAD,
    OPTION_WAKE_TAIL,
    OPTION_WAKE_WINDOW,
    PLACEHOLDER_DEVICE_ID_PREFIX,
    SENSOR_BATTERY,
    SENSOR_HUMIDITY,
    SENSOR_MODELS,
    SENSOR_TEMPERATURE,
    SENSOR_TYPE_CODE,
)
from .cozylife_api import CozyLifeSensorClient

# How long the config flow waits for an awake sensor to answer.
IDENTITY_PROBE_SECONDS = 2.0


def _valid_ipv4(value: str) -> bool:
    try:
        ipaddress.IPv4Address(value)
    except ValueError:
        return False
    return True


async def _async_read_identity(ip_address: str, pid: str) -> dict[str, Any] | None:
    """Ask the sensor for its identity; None while it sleeps."""
    client = CozyLifeSensorClient(ip_address, pid)
    try:
        return await client.async_read_identity(IDENTITY_PROBE_SECONDS)
    finally:
        await client.async_close()


def _model_selector() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(
                    value=pid,
                    label=f"{pid}{' (tested)' if pid == DEFAULT_PID else ''}",
                )
                for pid in SENSOR_MODELS
            ],
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


class CozyLifeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add one sensor by its (fixed) IP address."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the IP address and the model."""
        errors: dict[str, str] = {}
        if user_input is not None:
            ip_address = user_input[CONF_IP_ADDRESS].strip()
            pid = user_input[CONF_PID]
            if not _valid_ipv4(ip_address):
                errors[CONF_IP_ADDRESS] = "invalid_ip"
            else:
                self._async_abort_entries_match({CONF_IP_ADDRESS: ip_address})
                identity = await _async_read_identity(ip_address, pid)
                if identity is not None and identity["pid"] != pid:
                    errors[CONF_PID] = "wrong_model"
                else:
                    device_id = (
                        identity["did"]
                        if identity is not None
                        else f"{PLACEHOLDER_DEVICE_ID_PREFIX}{ip_address}"
                    )
                    await self.async_set_unique_id(device_id)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"CozyLife sensor {ip_address}",
                        data={
                            CONF_IP_ADDRESS: ip_address,
                            CONF_DEVICE_ID: device_id,
                            CONF_PID: pid,
                            CONF_DEVICE_TYPE_CODE: (
                                identity["dtp"] if identity else SENSOR_TYPE_CODE
                            ),
                            CONF_DPIDS: [
                                SENSOR_HUMIDITY,
                                SENSOR_TEMPERATURE,
                                SENSOR_BATTERY,
                            ],
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_IP_ADDRESS): str,
                        vol.Required(CONF_PID, default=DEFAULT_PID): _model_selector(),
                    }
                ),
                user_input,
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return CozyLifeOptionsFlow()


def _seconds_selector(minimum: float, maximum: float) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=0.5,
            unit_of_measurement="s",
            mode=NumberSelectorMode.BOX,
        )
    )


class CozyLifeOptionsFlow(OptionsFlow):
    """Wake window, outlier filter and debug logging."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and save the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    OPTION_WAKE_WINDOW,
                    default=options.get(OPTION_WAKE_WINDOW, DEFAULT_WAKE_WINDOW),
                ): bool,
                vol.Optional(
                    OPTION_WAKE_LEAD,
                    default=options.get(OPTION_WAKE_LEAD, DEFAULT_WAKE_LEAD_SECONDS),
                ): _seconds_selector(1, 600),
                vol.Optional(
                    OPTION_WAKE_TAIL,
                    default=options.get(OPTION_WAKE_TAIL, DEFAULT_WAKE_TAIL_SECONDS),
                ): _seconds_selector(5, 600),
                vol.Optional(
                    OPTION_FILTER_OUTLIERS,
                    default=options.get(OPTION_FILTER_OUTLIERS, False),
                ): bool,
                vol.Optional(
                    OPTION_TEMPERATURE_RADIUS,
                    default=options.get(
                        OPTION_TEMPERATURE_RADIUS, DEFAULT_TEMPERATURE_RADIUS
                    ),
                ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=120)),
                vol.Optional(
                    OPTION_HUMIDITY_RADIUS,
                    default=options.get(OPTION_HUMIDITY_RADIUS, DEFAULT_HUMIDITY_RADIUS),
                ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=100)),
                vol.Optional(
                    OPTION_ENABLE_DEBUG,
                    default=options.get(OPTION_ENABLE_DEBUG, False),
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
