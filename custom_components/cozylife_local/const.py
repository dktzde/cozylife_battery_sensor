"""Constants for the CozyLife battery sensor integration."""

from __future__ import annotations

DOMAIN = "cozylife_local"
PLATFORMS = ["sensor"]

# Config entry data keys (kept from the upstream integration so existing
# entries keep working after switching to this fork).
CONF_IP_ADDRESS = "ip_address"
CONF_DEVICE_ID = "device_id"
CONF_PID = "pid"
CONF_DEVICE_TYPE_CODE = "device_type_code"
CONF_DPIDS = "dpids"
# Set when the IP address changed: hold measurements back until the sensor at
# the new address proved its device ID.
CONF_VERIFY_IDENTITY = "verify_identity"

# Entries created by upstream releases with UDP discovery. This fork removes them.
CONF_ENTRY_TYPE = "entry_type"
DISCOVERY_CONTROLLER_ENTRY_TYPE = "discovery_controller"

# A sensor added while it sleeps gets this placeholder ID until its first
# report proves its real device ID.
PLACEHOLDER_DEVICE_ID_PREFIX = "sleeping_sensor_"

# Sensor data point IDs (DPIDs).
SENSOR_HUMIDITY = "4"  # raw value = %
SENSOR_TEMPERATURE = "8"  # raw value / 10 = °C
SENSOR_BATTERY = "9"  # raw value / 10 = %
SENSOR_TYPE_CODE = "03"

# Wi-Fi temperature and humidity sensors from the CozyLife app catalogue
# (category 03, network type 02). Only Z4tRml is tested with this fork.
SENSOR_MODELS: dict[str, str] = {
    "Z4tRml": "temperature and humidity sensor",
    "s1AxFq": "Temperature and humidity sensor",
    "nrQdBz": "temperature and humidity sensor",
    "JTFMlo": "temperature and humidity sensor",
    "1iTgTJ": "temperature and humidity sensor",
    "2EKExY": "Temperature and humidity sensor",
    "suUl7T": "Temperature and humidity sensor",
}
DEFAULT_PID = "Z4tRml"
# Z4tRml expects bare JSON commands; other firmware expects CRLF-terminated lines.
BARE_JSON_PIDS = frozenset({"Z4tRml"})

# Options.
OPTION_ENABLE_DEBUG = "enable_debug"
OPTION_FILTER_OUTLIERS = "filter_outliers"
OPTION_TEMPERATURE_RADIUS = "temperature_radius"
OPTION_HUMIDITY_RADIUS = "humidity_radius"

DEFAULT_TEMPERATURE_RADIUS = 2.0
DEFAULT_HUMIDITY_RADIUS = 10.0

# Wake window: probe only shortly before the learned wake-up.
OPTION_WAKE_WINDOW = "sensor_wake_window"
OPTION_WAKE_LEAD = "wake_lead_seconds"
OPTION_WAKE_TAIL = "wake_tail_seconds"
DEFAULT_WAKE_WINDOW = True
# Start probing this long before the expected wake-up ... Measured on a Z4tRml
# over two days: the learned period predicts the wake-up within -1.9 to +2.9 s,
# so 7 s starts probing about 5 to 10 s before the sensor wakes up.
DEFAULT_WAKE_LEAD_SECONDS = 7.0
# ... and give up this long after it (only matters when the sensor is late or
# does not wake up; a report ends the window at once).
DEFAULT_WAKE_TAIL_SECONDS = 30.0
# After a missed or too tight window, the next window is at least this wide.
FALLBACK_WAKE_LEAD_SECONDS = 20.0
FALLBACK_WAKE_TAIL_SECONDS = 60.0
