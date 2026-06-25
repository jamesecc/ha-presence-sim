"""Config and options flow for Presence Simulator (UI entity selection).

Onboarding is a single page: pick entities, set the two learning knobs
(schedule resolution and the power 'active' threshold). The day-to-day
simulation tuning knobs are live entities on the device page, not wizard
fields, so nothing is entered twice and they can be changed without a reload.
"""

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
    CONF_MONITORED,
    CONF_POWER_THRESHOLD,
    CONF_SLOT_MINUTES,
    DEFAULT_POWER_THRESHOLD,
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


# Transient options-form key: a toggle that opens the tuning-controls guide
# instead of saving. Never persisted (popped before save).
VIEW_HELP = "view_tuning_help"


def _entities_selector(domains: list[str]) -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=domains, multiple=True)
    )


def _config_schema(defaults: dict[str, Any]) -> vol.Schema:
    """The single onboarding/options page: entities + the two learning knobs."""
    return vol.Schema(
        {
            vol.Required(
                CONF_CONTROLLED, default=defaults.get(CONF_CONTROLLED, [])
            ): _entities_selector(CONTROL_DOMAINS),
            vol.Optional(
                CONF_MONITORED, default=defaults.get(CONF_MONITORED, [])
            ): _entities_selector(MONITOR_DOMAINS),
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
                CONF_POWER_THRESHOLD,
                default=defaults.get(CONF_POWER_THRESHOLD, DEFAULT_POWER_THRESHOLD),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=500, step=1, unit_of_measurement="W",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        }
    )


class PresenceSimulatorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial setup flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Presence Simulator", data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=_config_schema({}),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "PresenceSimulatorOptionsFlow":
        return PresenceSimulatorOptionsFlow(config_entry)


class PresenceSimulatorOptionsFlow(OptionsFlow):
    """Edit entities/learning, or read what the tuning controls do."""

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
        # Land straight on the entities & learning page (no menu) — the
        # tuning-controls guide is reachable from there via the help toggle.
        return await self.async_step_configure(user_input)

    async def async_step_configure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            view_help = user_input.pop(VIEW_HELP, False)
            self._data = dict(user_input)
            if view_help:
                # Keep the in-progress edits and open the guide; "Back"
                # returns here with these values restored.
                return await self.async_step_help()
            new_slot = int(user_input.get(CONF_SLOT_MINUTES, DEFAULT_SLOT_MINUTES))
            cur_slot = int(self._current().get(CONF_SLOT_MINUTES, DEFAULT_SLOT_MINUTES))
            if new_slot != cur_slot:
                return await self.async_step_slot_confirm()
            return self._save()
        defaults = {**self._current(), **self._data}
        schema = _config_schema(defaults).extend(
            {vol.Optional(VIEW_HELP, default=False): selector.BooleanSelector()}
        )
        return self.async_show_form(step_id="configure", data_schema=schema)

    async def async_step_slot_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self._save()
        return self.async_show_form(
            step_id="slot_confirm",
            data_schema=vol.Schema({}),
        )

    async def async_step_help(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        # Read-only guide page: the single "configure" menu option renders as a
        # Back button that returns to the entities & learning page.
        return self.async_show_menu(step_id="help", menu_options=["configure"])

    def _save(self) -> ConfigFlowResult:
        # Preserve the live tuning knobs that live only in options (set via the
        # number/time entities) so editing entities here doesn't wipe them.
        merged = {**self._entry.options, **self._data}
        return self.async_create_entry(title="", data=merged)
