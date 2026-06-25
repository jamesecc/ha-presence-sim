"""The Presence Simulator integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONF_SLOT_MINUTES,
    DATA_COORDINATOR,
    DEFAULT_SLOT_MINUTES,
    DOMAIN,
    PLATFORMS,
    SERVICE_EXPORT_MODEL,
    SERVICE_RESET_MODEL,
    SERVICE_RUN_STEP,
    SIGNAL_MODEL_UPDATED,
)
from .coordinator import PresenceCoordinator

_LOGGER = logging.getLogger(__name__)

_TARGET_SCHEMA = vol.Schema({vol.Optional("entry_id"): cv.string})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Presence Simulator from a config entry."""
    coordinator = PresenceCoordinator(hass, entry)
    await coordinator.async_load()
    await coordinator.async_start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        DATA_COORDINATOR: coordinator
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if data:
        coordinator: PresenceCoordinator = data[DATA_COORDINATOR]
        await coordinator.async_stop()

    if not hass.data.get(DOMAIN):
        for service in (SERVICE_RESET_MODEL, SERVICE_RUN_STEP, SERVICE_EXPORT_MODEL):
            if hass.services.has_service(DOMAIN, service):
                hass.services.async_remove(DOMAIN, service)

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply option changes.

    Only a slot-size change needs a reload (it rebuilds the bucket layout and
    swaps the active learned model). Everything else — entity lists, power
    threshold, and all live tuning knobs — is read live by the coordinator, so
    we just nudge the entities to re-render. This keeps editing a knob from
    disrupting active learning or simulation.
    """
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not data:
        return
    coordinator: PresenceCoordinator = data[DATA_COORDINATOR]
    new_slot = int(
        entry.options.get(
            CONF_SLOT_MINUTES, entry.data.get(CONF_SLOT_MINUTES, DEFAULT_SLOT_MINUTES)
        )
    )
    if new_slot != coordinator.model.slot_minutes:
        await hass.config_entries.async_reload(entry.entry_id)
        return
    async_dispatcher_send(hass, SIGNAL_MODEL_UPDATED.format(entry_id=entry.entry_id))


def _async_register_services(hass: HomeAssistant) -> None:
    """Register integration-level services (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_RESET_MODEL):
        return

    def _coordinators(call: ServiceCall) -> list[PresenceCoordinator]:
        entry_id = call.data.get("entry_id")
        entries = hass.data.get(DOMAIN, {})
        if entry_id:
            data = entries.get(entry_id)
            return [data[DATA_COORDINATOR]] if data else []
        return [d[DATA_COORDINATOR] for d in entries.values()]

    async def _reset(call: ServiceCall) -> None:
        for coordinator in _coordinators(call):
            await coordinator.async_reset_model()

    async def _run_step(call: ServiceCall) -> None:
        for coordinator in _coordinators(call):
            await coordinator.async_run_step_now()

    async def _export(call: ServiceCall) -> dict:
        result = {}
        for coordinator in _coordinators(call):
            result[coordinator.entry.entry_id] = {
                "observations": coordinator.model.total_observations(),
                "coverage": coordinator.model.coverage(),
                "entities": list(coordinator.model.entities),
            }
        return {"models": result}

    hass.services.async_register(DOMAIN, SERVICE_RESET_MODEL, _reset, schema=_TARGET_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_RUN_STEP, _run_step, schema=_TARGET_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT_MODEL,
        _export,
        schema=_TARGET_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
