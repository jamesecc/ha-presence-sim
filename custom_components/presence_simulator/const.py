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

# Runtime data key in hass.data[DOMAIN][entry_id]
DATA_COORDINATOR = "coordinator"

PLATFORMS = ["switch", "sensor"]

# Services
SERVICE_RESET_MODEL = "reset_model"
SERVICE_RUN_STEP = "run_step"
SERVICE_EXPORT_MODEL = "export_model"

# Signals
SIGNAL_AWAY_STATE = f"{DOMAIN}_away_state_{{entry_id}}"
SIGNAL_MODEL_UPDATED = f"{DOMAIN}_model_updated_{{entry_id}}"
