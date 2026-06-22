"""Config and options flow for Presence Simulator (UI entity selection)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CONTROLLED,
    CONF_JITTER_MINUTES,
    CONF_MAX_CONCURRENT_FRACTION,
    CONF_MIN_DWELL_MINUTES,
    CONF_MONITORED,
    CONF_POWER_THRESHOLD,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_RANDOMNESS,
    CONF_SLOT_MINUTES,
    DEFAULT_JITTER_MINUTES,
    DEFAULT_MAX_CONCURRENT_FRACTION,
    DEFAULT_MIN_DWELL_MINUTES,
    DEFAULT_POWER_THRESHOLD,
    DEFAULT_QUIET_END,
    DEFAULT_QUIET_START,
    DEFAULT_RANDOMNESS,
    DEFAULT_SLOT_MINUTES,
    DOMAIN,
)

# Domains worth monitoring (state/energy signals).
MONITOR_DOMAINS = [
    "light",
    "switch",
    "binary_sensor",
    "sensor",
    "media_player",
    "fan",
    "climate",
    "cover",
    "input_boolean",
]
# Domains we can actuate in away mode.
CONTROL_DOMAINS = [
    "light",
    "switch",
    "fan",
    "media_player",
    "input_boolean",
    "climate",
    "humidifier",
    "cover",
]


def _entities_selector(domains: list[str]) -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=domains, multiple=True)
    )


def _base_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_MONITORED, default=defaults.get(CONF_MONITORED, [])
            ): _entities_selector(MONITOR_DOMAINS),
            vol.Required(
                CONF_CONTROLLED, default=defaults.get(CONF_CONTROLLED, [])
            ): _entities_selector(CONTROL_DOMAINS),
        }
    )


def _tuning_schema(defaults: dict[str, Any]) -> dict:
    return {
        vol.Optional(
            CONF_SLOT_MINUTES,
            default=defaults.get(CONF_SLOT_MINUTES, DEFAULT_SLOT_MINUTES),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=10, max=120, step=5, unit_of_measurement="min",
                mode=selector.NumberSelectorMode.SLIDER,
            )
        ),
        vol.Optional(
            CONF_RANDOMNESS,
            default=defaults.get(CONF_RANDOMNESS, DEFAULT_RANDOMNESS),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=0.6, step=0.05, mode=selector.NumberSelectorMode.SLIDER,
            )
        ),
        vol.Optional(
            CONF_MIN_DWELL_MINUTES,
            default=defaults.get(CONF_MIN_DWELL_MINUTES, DEFAULT_MIN_DWELL_MINUTES),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=120, step=5, unit_of_measurement="min",
                mode=selector.NumberSelectorMode.SLIDER,
            )
        ),
        vol.Optional(
            CONF_JITTER_MINUTES,
            default=defaults.get(CONF_JITTER_MINUTES, DEFAULT_JITTER_MINUTES),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=30, step=1, unit_of_measurement="min",
                mode=selector.NumberSelectorMode.SLIDER,
            )
        ),
        vol.Optional(
            CONF_MAX_CONCURRENT_FRACTION,
            default=defaults.get(
                CONF_MAX_CONCURRENT_FRACTION, DEFAULT_MAX_CONCURRENT_FRACTION
            ),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0.1, max=1.0, step=0.05, mode=selector.NumberSelectorMode.SLIDER,
            )
        ),
        vol.Optional(
            CONF_POWER_THRESHOLD,
            default=defaults.get(CONF_POWER_THRESHOLD, DEFAULT_POWER_THRESHOLD),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=500, step=1, unit_of_measurement="W",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Optional(
            CONF_QUIET_START,
            default=defaults.get(CONF_QUIET_START, DEFAULT_QUIET_START),
        ): selector.TimeSelector(),
        vol.Optional(
            CONF_QUIET_END,
            default=defaults.get(CONF_QUIET_END, DEFAULT_QUIET_END),
        ): selector.TimeSelector(),
    }


class PresenceSimulatorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial setup flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_tuning()
        return self.async_show_form(
            step_id="user",
            data_schema=_base_schema({}),
        )

    async def async_step_tuning(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(
                title="Presence Simulator", data=self._data
            )
        return self.async_show_form(
            step_id="tuning",
            data_schema=vol.Schema(_tuning_schema({})),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "PresenceSimulatorOptionsFlow":
        return PresenceSimulatorOptionsFlow(config_entry)


class PresenceSimulatorOptionsFlow(OptionsFlow):
    """Edit entities and tuning after setup."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry
        self._data: dict[str, Any] = {}

    def _current(self) -> dict[str, Any]:
        merged = dict(self._entry.data)
        merged.update(self._entry.options)
        return merged

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_tuning()
        return self.async_show_form(
            step_id="init",
            data_schema=_base_schema(self._current()),
        )

    async def async_step_tuning(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title="", data=self._data)
        return self.async_show_form(
            step_id="tuning",
            data_schema=vol.Schema(_tuning_schema(self._current())),
        )
