"""Coordinator: sampling/learning loop and away-mode simulation engine."""

from __future__ import annotations

import logging
import random
from collections import deque
from datetime import datetime, time, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

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
    CONTROLLABLE_DOMAINS,
    DEFAULT_JITTER_MINUTES,
    DEFAULT_MAX_CONCURRENT_FRACTION,
    DEFAULT_MIN_DWELL_MINUTES,
    DEFAULT_POWER_THRESHOLD,
    DEFAULT_QUIET_END,
    DEFAULT_QUIET_START,
    DEFAULT_RANDOMNESS,
    DEFAULT_SLOT_MINUTES,
    EVENT_ACTION,
    HISTORY_MAXLEN,
    SAMPLE_MINUTES,
    SIGNAL_ACTION,
    SIGNAL_AWAY_STATE,
    SIGNAL_MODEL_UPDATED,
    STORAGE_KEY_FMT,
    STORAGE_VERSION,
)
from .model import ActivityModel, bucket_for, is_active

_LOGGER = logging.getLogger(__name__)


def _parse_time(value: str | None, default: str) -> time:
    raw = value or default
    try:
        parts = [int(p) for p in raw.split(":")]
        while len(parts) < 3:
            parts.append(0)
        return time(parts[0], parts[1], parts[2])
    except (ValueError, AttributeError):
        h, m, s = (int(p) for p in default.split(":"))
        return time(h, m, s)


class PresenceCoordinator:
    """Owns the learned model, the sampling loop and the simulation loop."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store: Store = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_FMT.format(entry_id=entry.entry_id)
        )
        self.model: ActivityModel = ActivityModel(self.slot_minutes)
        # Learned models parked under other slot sizes, keyed by str(slot).
        # Lets us switch schedule resolution without losing data.
        self._archived: dict[str, dict] = {}
        self.away_active: bool = False

        # Per-entity bookkeeping for the simulation.
        self._desired: dict[str, bool] = {}
        self._last_change: dict[str, datetime] = {}
        self._controlled_by_us: set[str] = set()

        # Recent on/off actions we applied, newest first (in-memory only).
        self._history: deque = deque(maxlen=HISTORY_MAXLEN)

        # Listener cancel handles.
        self._cancel_sample = None
        self._cancel_sim = None
        self._cancel_jitter: list = []

        self.last_sample: datetime | None = None
        self.last_step: datetime | None = None

    # ---- config accessors -------------------------------------------------

    def _opt(self, key: str, default):
        return self.entry.options.get(key, self.entry.data.get(key, default))

    @callback
    def update_option(self, key: str, value) -> None:
        """Persist a single runtime tunable into entry.options.

        Used by the number/time tuning entities. options is the single source of
        truth (read live via _opt), so this takes effect immediately without a
        reload; the update listener only reloads on a slot-size change.
        """
        options = {**self.entry.options, key: value}
        self.hass.config_entries.async_update_entry(self.entry, options=options)

    @property
    def slot_minutes(self) -> int:
        return int(self._opt(CONF_SLOT_MINUTES, DEFAULT_SLOT_MINUTES))

    @property
    def monitored(self) -> list[str]:
        # Controlled entities are always learned from too, so the user never has
        # to list them in both selectors. Union, preserving order.
        base = list(self._opt(CONF_MONITORED, []))
        for entity_id in self._opt(CONF_CONTROLLED, []):
            if entity_id not in base:
                base.append(entity_id)
        return base

    @property
    def controlled(self) -> list[str]:
        return list(self._opt(CONF_CONTROLLED, []))

    @property
    def randomness(self) -> float:
        return float(self._opt(CONF_RANDOMNESS, DEFAULT_RANDOMNESS))

    @property
    def min_dwell(self) -> timedelta:
        return timedelta(minutes=int(self._opt(CONF_MIN_DWELL_MINUTES, DEFAULT_MIN_DWELL_MINUTES)))

    @property
    def jitter_minutes(self) -> int:
        return int(self._opt(CONF_JITTER_MINUTES, DEFAULT_JITTER_MINUTES))

    @property
    def power_threshold(self) -> float:
        return float(self._opt(CONF_POWER_THRESHOLD, DEFAULT_POWER_THRESHOLD))

    @property
    def max_concurrent_fraction(self) -> float:
        return float(self._opt(CONF_MAX_CONCURRENT_FRACTION, DEFAULT_MAX_CONCURRENT_FRACTION))

    @property
    def quiet_window(self) -> tuple[time, time]:
        return (
            _parse_time(self._opt(CONF_QUIET_START, DEFAULT_QUIET_START), DEFAULT_QUIET_START),
            _parse_time(self._opt(CONF_QUIET_END, DEFAULT_QUIET_END), DEFAULT_QUIET_END),
        )

    # ---- lifecycle --------------------------------------------------------

    async def async_load(self) -> None:
        slot = self.slot_minutes
        data = await self._store.async_load()
        if not data:
            self.model = ActivityModel(slot)
            self._archived = {}
            return
        # Models parked under other slot sizes (older versions ignore this key).
        self._archived = dict(data.get("archived_models", {}))
        stored_slot = int(data.get("slot_minutes", slot))
        if stored_slot == slot:
            self.model = ActivityModel.from_dict(data, slot)
            return
        # Slot size changed: park the stored active model under its slot and
        # restore any model we previously learned for the new slot.
        active = {k: v for k, v in data.items() if k != "archived_models"}
        self._archived[str(stored_slot)] = active
        restored = self._archived.pop(str(slot), None)
        self.model = (
            ActivityModel.from_dict(restored, slot)
            if restored
            else ActivityModel(slot)
        )

    async def async_start(self) -> None:
        """Begin the periodic sampling loop (learning runs always)."""
        self._cancel_sample = async_track_time_interval(
            self.hass, self._async_sample, timedelta(minutes=SAMPLE_MINUTES)
        )
        # Take one sample immediately so the model starts filling in.
        # _async_sample is a synchronous @callback, so call it directly.
        self._async_sample(dt_util.now())

    async def async_stop(self) -> None:
        await self.async_set_away(False)
        if self._cancel_sample:
            self._cancel_sample()
            self._cancel_sample = None
        await self._async_save()

    async def _async_save(self) -> None:
        blob = self.model.to_dict()
        if self._archived:
            blob["archived_models"] = self._archived
        await self._store.async_save(blob)

    # ---- learning ---------------------------------------------------------

    @callback
    def _async_sample(self, now: datetime) -> None:
        """Sample monitored entities and accumulate into the model."""
        local = dt_util.as_local(now)
        bucket = bucket_for(local, self.slot_minutes)
        threshold = self.power_threshold
        changed = False
        for entity_id in self.monitored:
            state = self.hass.states.get(entity_id)
            raw = state.state if state else None
            attrs = state.attributes if state else None
            # Controllable devices that lose power when off report 'unavailable';
            # learn that as off rather than skipping (which would fall back to the
            # inflated household aggregate).
            domain = entity_id.split(".", 1)[0]
            active = is_active(
                raw,
                attrs,
                threshold,
                unavailable_is_off=domain in CONTROLLABLE_DOMAINS,
            )
            if active is None:
                continue
            self.model.observe(entity_id, bucket, active)
            changed = True
        self.last_sample = local
        if changed:
            async_dispatcher_send(
                self.hass, SIGNAL_MODEL_UPDATED.format(entry_id=self.entry.entry_id)
            )
            # Persist periodically (sampling is infrequent so saving each time is fine).
            self.hass.async_create_task(self._async_save())

    # ---- away-mode simulation --------------------------------------------

    async def async_set_away(self, active: bool) -> None:
        if active == self.away_active:
            return
        self.away_active = active
        if active:
            await self._start_simulation()
        else:
            await self._stop_simulation()
        async_dispatcher_send(
            self.hass, SIGNAL_AWAY_STATE.format(entry_id=self.entry.entry_id)
        )

    async def _start_simulation(self) -> None:
        _LOGGER.info("Presence Simulator: away mode ON for %s", self.entry.title)
        self._desired = {}
        self._last_change = {}
        self._controlled_by_us = set()
        # Drive one step now, then on each slot boundary.
        self._cancel_sim = async_track_time_interval(
            self.hass, self._async_sim_step, timedelta(minutes=self.slot_minutes)
        )
        await self._run_step(dt_util.now())

    async def _stop_simulation(self) -> None:
        _LOGGER.info("Presence Simulator: away mode OFF for %s", self.entry.title)
        if self._cancel_sim:
            self._cancel_sim()
            self._cancel_sim = None
        for cancel in self._cancel_jitter:
            cancel()
        self._cancel_jitter = []
        # Turn off everything we switched on, so we don't leave lights blazing.
        for entity_id in list(self._controlled_by_us):
            await self._apply(entity_id, False)
        self._controlled_by_us = set()

    @callback
    def _async_sim_step(self, now: datetime) -> None:
        self.hass.async_create_task(self._run_step(now))

    def _in_quiet_window(self, local: datetime) -> bool:
        start, end = self.quiet_window
        t = local.time()
        if start <= end:
            return start <= t < end
        # Window wraps past midnight.
        return t >= start or t < end

    async def _run_step(self, now: datetime) -> None:
        """Decide a target state for each controlled entity for this slot."""
        if not self.away_active:
            return
        local = dt_util.as_local(now)
        bucket = bucket_for(local, self.slot_minutes)
        self.last_step = local
        quiet = self._in_quiet_window(local)
        randomness = self.randomness

        controlled = self.controlled
        decisions: dict[str, bool] = {}
        for entity_id in controlled:
            p = self.model.entity_probability(entity_id, bucket)
            if quiet:
                # Overnight: strongly bias toward off, but allow the rare light.
                p *= 0.15
            # Inject randomness: occasionally flip the natural inclination so
            # the pattern isn't a deterministic replay of history.
            roll = random.random()
            want_on = roll < p
            if random.random() < randomness:
                want_on = not want_on
            decisions[entity_id] = want_on

        # Cap how many controlled entities are on at once for realism.
        max_on = max(1, int(round(len(controlled) * self.max_concurrent_fraction)))
        on_list = [e for e, v in decisions.items() if v]
        if len(on_list) > max_on:
            random.shuffle(on_list)
            for extra in on_list[max_on:]:
                decisions[extra] = False

        # Apply with per-entity dwell time and randomised timing (jitter).
        for entity_id, want_on in decisions.items():
            current = self._desired.get(entity_id)
            if current is not None and current == want_on:
                continue  # no change requested
            last = self._last_change.get(entity_id)
            if (
                current is not None
                and last is not None
                and (local - last) < self.min_dwell
            ):
                continue  # respect minimum dwell to avoid rapid flicker
            self._desired[entity_id] = want_on
            self._last_change[entity_id] = local
            self._schedule_jittered(entity_id, want_on)

    def _schedule_jittered(self, entity_id: str, turn_on: bool) -> None:
        """Apply the change after a random delay within the slot."""
        max_delay = min(self.jitter_minutes, max(1, self.slot_minutes - 1)) * 60
        delay = random.uniform(0, max_delay) if max_delay > 0 else 0

        if delay <= 0:
            self.hass.async_create_task(self._apply(entity_id, turn_on))
            return

        handle_ref: list = []

        async def _do(_now):
            # Drop our own (now-fired) cancel handle so the list doesn't grow.
            if handle_ref:
                try:
                    self._cancel_jitter.remove(handle_ref[0])
                except ValueError:
                    pass
            await self._apply(entity_id, turn_on)

        cancel = async_call_later(self.hass, delay, _do)
        handle_ref.append(cancel)
        self._cancel_jitter.append(cancel)

    async def _apply(self, entity_id: str, turn_on: bool) -> None:
        domain = entity_id.split(".", 1)[0]
        # Only domains that support turn_on/turn_off services.
        if domain not in CONTROLLABLE_DOMAINS:
            domain = "homeassistant"  # generic turn_on/off
        service = SERVICE_TURN_ON if turn_on else SERVICE_TURN_OFF
        try:
            await self.hass.services.async_call(
                domain if domain != "cover" else "cover",
                service if domain != "cover" else ("open_cover" if turn_on else "close_cover"),
                {ATTR_ENTITY_ID: entity_id},
                blocking=False,
            )
        except Exception as err:  # noqa: BLE001 - log and continue, never break the loop
            _LOGGER.warning("Failed to %s %s: %s", service, entity_id, err)
            return
        if turn_on:
            self._controlled_by_us.add(entity_id)
        else:
            self._controlled_by_us.discard(entity_id)
        self._record_action(entity_id, turn_on)

    def _record_action(self, entity_id: str, turn_on: bool) -> None:
        """Record an applied on/off action: history, Logbook event, sensor refresh."""
        action = "on" if turn_on else "off"
        now = dt_util.now()
        self._history.appendleft(
            {"time": now.isoformat(), "entity_id": entity_id, "action": action}
        )
        # Fire an event so the change lands on the native Logbook timeline.
        self.hass.bus.async_fire(
            EVENT_ACTION,
            {
                "entry_id": self.entry.entry_id,
                "entity_id": entity_id,
                "action": action,
            },
        )
        async_dispatcher_send(
            self.hass, SIGNAL_ACTION.format(entry_id=self.entry.entry_id)
        )

    @property
    def history(self) -> list[dict]:
        """Most-recent-first list of on/off actions we applied."""
        return list(self._history)

    # ---- services ---------------------------------------------------------

    async def async_reset_model(self) -> None:
        # A reset discards everything, including models parked under other slots.
        self.model = ActivityModel(self.slot_minutes)
        self._archived = {}
        await self._async_save()
        async_dispatcher_send(
            self.hass, SIGNAL_MODEL_UPDATED.format(entry_id=self.entry.entry_id)
        )

    async def async_run_step_now(self) -> None:
        await self._run_step(dt_util.now())
