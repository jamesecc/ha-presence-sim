"""Away-mode switch for Presence Simulator."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN, SIGNAL_AWAY_STATE
from .coordinator import PresenceCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PresenceCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities([AwayModeSwitch(coordinator)])


class AwayModeSwitch(SwitchEntity):
    """Turn this on (e.g. via an automation when nobody is home) to simulate presence."""

    _attr_has_entity_name = True
    _attr_name = "Away simulation"
    _attr_icon = "mdi:home-account"

    def __init__(self, coordinator: PresenceCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.entry.entry_id}_away"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": coordinator.entry.title,
            "manufacturer": "Presence Simulator",
            "entry_type": "service",
        }

    @property
    def is_on(self) -> bool:
        return self._coordinator.away_active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "controlled_entities": self._coordinator.controlled,
            "last_step": self._coordinator.last_step,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._coordinator.async_set_away(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._coordinator.async_set_away(False)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_AWAY_STATE.format(entry_id=self._coordinator.entry.entry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
