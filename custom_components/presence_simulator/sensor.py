"""Diagnostic sensors for Presence Simulator (learning progress)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DATA_COORDINATOR,
    DOMAIN,
    SIGNAL_ACTION,
    SIGNAL_AWAY_STATE,
    SIGNAL_MODEL_UPDATED,
)
from .coordinator import PresenceCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: PresenceCoordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities(
        [
            LearningCoverageSensor(coordinator),
            ObservationsSensor(coordinator),
            LastActionSensor(coordinator),
        ]
    )


class _BaseSensor(SensorEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PresenceCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.entry.entry_id)},
            "name": coordinator.entry.title,
            "manufacturer": "Presence Simulator",
            "entry_type": "service",
        }

    async def async_added_to_hass(self) -> None:
        entry_id = self._coordinator.entry.entry_id
        for signal in (
            SIGNAL_MODEL_UPDATED.format(entry_id=entry_id),
            SIGNAL_AWAY_STATE.format(entry_id=entry_id),
            SIGNAL_ACTION.format(entry_id=entry_id),
        ):
            self.async_on_remove(
                async_dispatcher_connect(self.hass, signal, self._handle_update)
            )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()


class LearningCoverageSensor(_BaseSensor):
    """Fraction of the weekly schedule that has been observed at least once."""

    _attr_name = "Learning coverage"
    _attr_icon = "mdi:chart-timeline-variant"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: PresenceCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_coverage"

    @property
    def native_value(self) -> float:
        return round(self._coordinator.model.coverage() * 100, 1)


class ObservationsSensor(_BaseSensor):
    """Total number of samples collected into the model."""

    _attr_name = "Observations"
    _attr_icon = "mdi:counter"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: PresenceCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_observations"

    @property
    def native_value(self) -> int:
        return int(self._coordinator.model.total_observations())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "monitored_entities": self._coordinator.monitored,
            "learned_entities": list(self._coordinator.model.entities),
            "last_sample": self._coordinator.last_sample,
            "slot_minutes": self._coordinator.slot_minutes,
        }


class LastActionSensor(_BaseSensor):
    """Most recent on/off action the simulator applied, with recent history."""

    _attr_name = "Last action"
    _attr_icon = "mdi:history"

    def __init__(self, coordinator: PresenceCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_last_action"

    @property
    def native_value(self) -> str | None:
        history = self._coordinator.history
        if not history:
            return None
        latest = history[0]
        return f"{latest['entity_id']} → {latest['action']}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        history = self._coordinator.history
        return {
            "recent": history,
            "action_count": len(history),
            "last_action_time": history[0]["time"] if history else None,
        }
