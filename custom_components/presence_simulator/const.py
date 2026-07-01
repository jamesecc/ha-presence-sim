"""Constants for the Presence Simulator integration."""

from __future__ import annotations

DOMAIN = "presence_simulator"

# Config / options keys
CONF_MONITORED = "monitored_entities"
CONF_CONTROLLED = "controlled_entities"
CONF_SLOT_MINUTES = "slot_minutes"
CONF_RANDOMNESS = "randomness"
CONF_MIN_DWELL_MINUTES = "min_dwell_minutes"
CONF_JITTER_MINUTES = "jitter_minutes"
CONF_POWER_THRESHOLD = "power_threshold"
CONF_MAX_CONCURRENT_FRACTION = "max_concurrent_fraction"
CONF_QUIET_START = "quiet_start"
CONF_QUIET_END = "quiet_end"

# Defaults
DEFAULT_SLOT_MINUTES = 30
DEFAULT_RANDOMNESS = 0.15
DEFAULT_MIN_DWELL_MINUTES = 20
DEFAULT_JITTER_MINUTES = 7
DEFAULT_POWER_THRESHOLD = 5.0  # watts; numeric monitored entity is "active" above this
DEFAULT_MAX_CONCURRENT_FRACTION = 0.85
DEFAULT_QUIET_START = "00:30:00"
DEFAULT_QUIET_END = "06:00:00"

# How often we sample monitored entities while learning (minutes).
SAMPLE_MINUTES = 5

# Persistence
STORAGE_VERSION = 1
STORAGE_KEY_FMT = f"{DOMAIN}.model.{{entry_id}}"

# Laplace smoothing prior for on-probability estimates.
PRIOR_ON = 1.0
PRIOR_TOTAL = 4.0

# States we treat as "active"/on for non-numeric monitored entities.
ACTIVE_STATES = frozenset(
    {"on", "open", "home", "playing", "active", "heat", "cool", "cleaning"}
)

# Controllable domains: entities we can switch on/off. For these an
# 'unavailable'/'unknown' state means the device is powered off (e.g. a smart
# bulb cut from power), so it is learned as OFF rather than skipped. Sensor-only
# domains keep skipping so genuine data gaps don't pollute the totals.
CONTROLLABLE_DOMAINS = frozenset(
    {
        "light",
        "switch",
        "fan",
        "media_player",
        "input_boolean",
        "climate",
        "humidifier",
        "cover",
    }
)

# Runtime data key in hass.data[DOMAIN][entry_id]
DATA_COORDINATOR = "coordinator"

PLATFORMS = ["switch", "sensor", "number", "time"]

# Live tuning controls exposed as entities (Configuration block of the device).
# Each tuple: (option key, internal default, scale, min, max, step, unit, icon).
# `scale` converts the displayed value to the stored internal value
# (displayed * scale = stored). Fraction knobs are shown as a percentage
# (scale 0.01) so they read naturally; minute knobs store the shown value
# (scale 1).
NUMBER_TUNABLES = (
    (CONF_RANDOMNESS, DEFAULT_RANDOMNESS, 0.01, 0, 60, 5, "%", "mdi:shuffle-variant"),
    (CONF_MIN_DWELL_MINUTES, DEFAULT_MIN_DWELL_MINUTES, 1, 0, 120, 5, "min", "mdi:timer-sand"),
    (CONF_JITTER_MINUTES, DEFAULT_JITTER_MINUTES, 1, 0, 30, 1, "min", "mdi:timer-cog-outline"),
    (CONF_MAX_CONCURRENT_FRACTION, DEFAULT_MAX_CONCURRENT_FRACTION, 0.01, 10, 100, 5, "%", "mdi:lightbulb-group"),
)

# Quiet-hours controls exposed as time entities.
# Each tuple: (option key, default "HH:MM:SS", icon).
TIME_TUNABLES = (
    (CONF_QUIET_START, DEFAULT_QUIET_START, "mdi:weather-night"),
    (CONF_QUIET_END, DEFAULT_QUIET_END, "mdi:weather-sunset-up"),
)

# Services
SERVICE_RESET_MODEL = "reset_model"
SERVICE_RUN_STEP = "run_step"
SERVICE_EXPORT_MODEL = "export_model"
SERVICE_EXPORT_SCHEDULE = "export_schedule"

# Bus event fired for every on/off action the simulator applies (drives Logbook).
EVENT_ACTION = f"{DOMAIN}_action"

# How many recent simulated actions to keep in memory for the "last action" sensor.
HISTORY_MAXLEN = 100

# Signals
SIGNAL_AWAY_STATE = f"{DOMAIN}_away_state_{{entry_id}}"
SIGNAL_MODEL_UPDATED = f"{DOMAIN}_model_updated_{{entry_id}}"
SIGNAL_ACTION = f"{DOMAIN}_action_{{entry_id}}"
