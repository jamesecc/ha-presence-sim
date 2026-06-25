"""Live tuning controls for Presence Simulator (Configuration block).

These edit simulation behaviour on the fly. They persist into entry.options
(the single source of truth the coordinator reads live), so changes take effect
immediately without reloading the entry or touching the learned model.
"""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DATA_COORDINATOR, DOMAIN, NUMBER_TUNABLES, SIGNAL_MODEL_UPDATED
from .coordinator import PresenceCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PresenceCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities(TuningNumber(coordinator, *spec) for spec in NUMBER_TUNABLES)


class TuningNumber(NumberEntity):
    """A single simulation tunable, editable live from the device page."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        coordinator: PresenceCoordinator,
        key: str,
        default: float,
        scale: float,
        vmin: float,
        vmax: float,
        step: float,
        unit: str,
        icon: str,
    ) -> None:
        self._coordinator = coordinator
        self._key = key
        self._default = default
        self._scale = scale
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_native_min_value = vmin
        self._attr_native_max_value = vmax
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": coordinator.entry.title,
            "manufacturer": "Presence Simulator",
            "entry_type": "service",
        }

    @property
    def native_value(self) -> float:
        internal = float(self._coordinator._opt(self._key, self._default))
        return round(internal / self._scale)

    async def async_set_native_value(self, value: float) -> None:
        internal = value * self._scale
        # Minute knobs (scale 1) are stored as ints to match the rest of config.
        if self._scale == 1:
            internal = int(round(internal))
        self._coordinator.update_option(self._key, internal)
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
