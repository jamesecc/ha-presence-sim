"""Logbook descriptions for Presence Simulator on/off actions.

Renders each ``EVENT_ACTION`` fired by the coordinator as a readable line on
the native Logbook timeline (and on the affected entity's history), giving a
timestamped record of what the simulator switched and when.
"""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.logbook import (
    LOGBOOK_ENTRY_ENTITY_ID,
    LOGBOOK_ENTRY_MESSAGE,
    LOGBOOK_ENTRY_NAME,
)
from homeassistant.core import Event, HomeAssistant, callback

from .const import DOMAIN, EVENT_ACTION


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict]], None],
) -> None:
    """Describe presence_simulator action events for the Logbook."""

    @callback
    def _describe(event: Event) -> dict:
        data = event.data
        action = data.get("action", "changed")
        entity_id = data.get("entity_id")
        return {
            LOGBOOK_ENTRY_NAME: "Presence Simulator",
            LOGBOOK_ENTRY_MESSAGE: f"turned {action} {entity_id}",
            LOGBOOK_ENTRY_ENTITY_ID: entity_id,
        }

    async_describe_event(DOMAIN, EVENT_ACTION, _describe)
