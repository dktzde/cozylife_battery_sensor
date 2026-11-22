"""Temperature, humidity, battery and IP address entities of the sensor."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    EntityCategory,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_PID,
    DOMAIN,
    SENSOR_BATTERY,
    SENSOR_HUMIDITY,
    SENSOR_MODELS,
    SENSOR_TEMPERATURE,
)
from .coordinator import CozyLifeCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the four entities of the sensor."""
    coordinator: CozyLifeCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            CozyLifeTemperatureSensor(coordinator),
            CozyLifeHumiditySensor(coordinator),
            CozyLifeBatterySensor(coordinator),
            CozyLifeIPAddressSensor(coordinator),
        ]
    )


def _device_info(coordinator: CozyLifeCoordinator) -> DeviceInfo:
    pid = coordinator.config_entry.data.get(CONF_PID)
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.device_id)},
        name=SENSOR_MODELS.get(pid or "", f"CozyLife sensor ({pid})"),
        manufacturer="CozyLife",
        model=pid,
    )


class CozyLifeIPAddressSensor(CoordinatorEntity[CozyLifeCoordinator], SensorEntity):
    """Configured IP address of the sensor (diagnostic)."""

    _attr_has_entity_name = True
    _attr_name = "IP address"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:ip-network"

    def __init__(self, coordinator: CozyLifeCoordinator) -> None:
        """Create the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_ip_address"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> str:
        """Return the configured address."""
        return self.coordinator.client.ip_address


class CozyLifeMeasurementSensor(
    CoordinatorEntity[CozyLifeCoordinator], SensorEntity, RestoreEntity
):
    """A measurement that keeps its last value while the sensor sleeps."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _dpid: str
    _key: str
    _min: float
    _max: float

    def __init__(self, coordinator: CozyLifeCoordinator) -> None:
        """Create the entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_id}_{self._key}"
        self._attr_device_info = _device_info(coordinator)
        self._last_valid: float | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the last value, so a restart does not blank the sensor."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is None:
            return
        if last_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        try:
            value = float(last_state.state)
        except (TypeError, ValueError):
            return
        if self._min <= value <= self._max:
            self._last_valid = value

    def _convert(self, raw: float) -> float:
        raise NotImplementedError

    def _current_value(self) -> float | None:
        raw = (self.coordinator.data or {}).get(self._dpid)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None
        value = self._convert(raw)
        return value if self._min <= value <= self._max else None

    @callback
    def _handle_coordinator_update(self) -> None:
        if (value := self._current_value()) is not None:
            self._last_valid = value
        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        """Return the latest valid value."""
        return self._last_valid


class CozyLifeTemperatureSensor(CozyLifeMeasurementSensor):
    """Temperature in °C."""

    _attr_name = "Temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    # A report with the same value is still a report: keep it in the history.
    _attr_force_update = True
    _dpid = SENSOR_TEMPERATURE
    _key = "temperature"
    _min, _max = -40.0, 80.0

    def _convert(self, raw: float) -> float:
        return round(raw / 10, 1)


class CozyLifeHumiditySensor(CozyLifeMeasurementSensor):
    """Relative humidity in %."""

    _attr_name = "Humidity"
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_force_update = True
    _dpid = SENSOR_HUMIDITY
    _key = "humidity"
    _min, _max = 0.0, 100.0

    def _convert(self, raw: float) -> float:
        return float(raw)


class CozyLifeBatterySensor(CozyLifeMeasurementSensor):
    """Battery level in %."""

    _attr_name = "Battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _dpid = SENSOR_BATTERY
    _key = "battery"
    _min, _max = 0.0, 100.0

    def _convert(self, raw: float) -> float:
        return round(raw / 10, 1)
