"""Quiet-hours time controls for Presence Simulator (Configuration block).

Editable live from the device page; persisted into entry.options as
"HH:MM:SS" strings, read live by the coordinator without a reload.
"""

from __future__ import annotations

from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN, SIGNAL_MODEL_UPDATED, TIME_TUNABLES
from .coordinator import PresenceCoordinator, _parse_time


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PresenceCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities(TuningTime(coordinator, *spec) for spec in TIME_TUNABLES)


class TuningTime(TimeEntity):
    """A quiet-hours boundary, editable live from the device page."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: PresenceCoordinator,
        key: str,
        default: str,
        icon: str,
    ) -> None:
        self._coordinator = coordinator
        self._key = key
        self._default = default
        self._attr_translation_key = key
        self._attr_icon = icon
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": coordinator.entry.title,
            "manufacturer": "Presence Simulator",
            "entry_type": "service",
        }

    @property
    def native_value(self) -> dt_time:
        return _parse_time(self._coordinator._opt(self._key, self._default), self._default)

    async def async_set_value(self, value: dt_time) -> None:
        self._coordinator.update_option(self._key, value.strftime("%H:%M:%S"))
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_MODEL_UPDATED.format(entry_id=self._coordinator.entry.entry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
