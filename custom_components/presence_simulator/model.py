"""Activity model: learns per-entity on/off patterns by time-of-week.

The week is divided into fixed time slots (e.g. 30 min). For each monitored
entity and each slot we accumulate how often it was observed "active". The
resulting on-probability per slot is what the simulator replays during away
mode, with added randomness so the pattern never repeats identically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .const import ACTIVE_STATES, PRIOR_ON, PRIOR_TOTAL


def slots_per_day(slot_minutes: int) -> int:
    """Number of slots in one day for the given slot size."""
    return max(1, (24 * 60) // slot_minutes)


def total_slots(slot_minutes: int) -> int:
    """Number of slots across a full week."""
    return 7 * slots_per_day(slot_minutes)


def bucket_for(when: datetime, slot_minutes: int) -> int:
    """Return the week-bucket index for a local datetime.

    Bucket = weekday * slots_per_day + (minute_of_day // slot_minutes).
    `when` is expected to be timezone-aware local time.
    """
    spd = slots_per_day(slot_minutes)
    minute_of_day = when.hour * 60 + when.minute
    slot = min(spd - 1, minute_of_day // slot_minutes)
    return when.weekday() * spd + slot


WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def slot_label(bucket: int, slot_minutes: int) -> tuple[int, str]:
    """Inverse of ``bucket_for``: map a week-bucket back to (weekday, "HH:MM").

    weekday is 0=Mon..6=Sun; the time is the start of the slot.
    """
    spd = slots_per_day(slot_minutes)
    weekday = bucket // spd
    slot_of_day = bucket % spd
    minute_of_day = slot_of_day * slot_minutes
    return weekday, f"{minute_of_day // 60:02d}:{minute_of_day % 60:02d}"


def is_active(
    state: str | None,
    attributes: dict | None,
    power_threshold: float,
    unavailable_is_off: bool = False,
) -> bool | None:
    """Decide whether a raw entity state counts as 'active'.

    Returns None when the state is unknown/unavailable so it can be skipped
    (so 'unavailable' periods don't pollute the learned totals). When
    ``unavailable_is_off`` is set — used for controllable devices that lose
    power when off (e.g. a smart bulb reporting 'unavailable') — those states
    are learned as off (False) instead of skipped.
    """
    if state is None:
        return False if unavailable_is_off else None
    state = state.lower()
    if state in ("unknown", "unavailable", "none", ""):
        return False if unavailable_is_off else None
    if state in ACTIVE_STATES:
        return True
    if state in ("off", "closed", "not_home", "away", "idle", "standby", "paused"):
        return False
    # Numeric? Treat as a power/energy-style sensor.
    try:
        value = float(state)
    except (TypeError, ValueError):
        # Unrecognised text state: treat any non-empty, non-off value as active
        # only if it isn't an obvious "off" synonym (already handled above).
        return True
    return value > power_threshold


@dataclass
class EntityModel:
    """Per-entity learned counts across the week."""

    on: list[float] = field(default_factory=list)
    total: list[float] = field(default_factory=list)

    @classmethod
    def empty(cls, n_slots: int) -> "EntityModel":
        return cls(on=[0.0] * n_slots, total=[0.0] * n_slots)

    def ensure_size(self, n_slots: int) -> None:
        if len(self.on) != n_slots:
            self.on = (self.on + [0.0] * n_slots)[:n_slots]
            self.total = (self.total + [0.0] * n_slots)[:n_slots]

    def observe(self, bucket: int, active: bool) -> None:
        self.total[bucket] += 1.0
        if active:
            self.on[bucket] += 1.0

    def probability(self, bucket: int) -> float:
        """Laplace-smoothed on-probability for a bucket."""
        on = self.on[bucket] + PRIOR_ON
        total = self.total[bucket] + PRIOR_TOTAL
        return on / total

    def samples(self, bucket: int) -> float:
        return self.total[bucket]

    def to_dict(self) -> dict[str, Any]:
        return {"on": self.on, "total": self.total}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EntityModel":
        return cls(on=list(data.get("on", [])), total=list(data.get("total", [])))


class ActivityModel:
    """Container for all monitored entities' learned patterns."""

    def __init__(self, slot_minutes: int) -> None:
        self.slot_minutes = slot_minutes
        self.n_slots = total_slots(slot_minutes)
        self.entities: dict[str, EntityModel] = {}
        # Aggregate household activity (mean active-fraction per slot), used as a
        # fallback for controlled entities that were never monitored.
        self._agg = EntityModel.empty(self.n_slots)

    def observe(self, entity_id: str, bucket: int, active: bool) -> None:
        em = self.entities.get(entity_id)
        if em is None:
            em = EntityModel.empty(self.n_slots)
            self.entities[entity_id] = em
        em.ensure_size(self.n_slots)
        em.observe(bucket, active)
        self._agg.observe(bucket, active)

    def entity_probability(self, entity_id: str, bucket: int) -> float:
        em = self.entities.get(entity_id)
        if em is not None and em.samples(bucket) > 0:
            return em.probability(bucket)
        return self.aggregate_probability(bucket)

    def aggregate_probability(self, bucket: int) -> float:
        return self._agg.probability(bucket)

    def schedule(self, entity_ids: list[str]) -> dict[str, list[float]]:
        """Return the learned on-probability per week-bucket.

        Keys are the requested entity ids (each falling back to the household
        aggregate where it has no samples) plus an ``"aggregate"`` row. Values
        are lists of length ``n_slots``; rendering into a weekday/time grid is
        left to the caller so this module stays HA-free.
        """
        buckets = range(self.n_slots)
        result: dict[str, list[float]] = {
            eid: [self.entity_probability(eid, b) for b in buckets]
            for eid in entity_ids
        }
        result["aggregate"] = [self.aggregate_probability(b) for b in buckets]
        return result

    def total_observations(self) -> float:
        return sum(self._agg.total)

    def coverage(self) -> float:
        """Fraction of week-buckets that have at least one observation."""
        if self.n_slots == 0:
            return 0.0
        covered = sum(1 for t in self._agg.total if t > 0)
        return covered / self.n_slots

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_minutes": self.slot_minutes,
            "entities": {eid: em.to_dict() for eid, em in self.entities.items()},
            "aggregate": self._agg.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], slot_minutes: int) -> "ActivityModel":
        model = cls(slot_minutes)
        # If the stored slot size differs from current config, start fresh to
        # avoid mismatched bucket arrays.
        stored_slot = int(data.get("slot_minutes", slot_minutes))
        if stored_slot != slot_minutes:
            return model
        for eid, em_data in data.get("entities", {}).items():
            em = EntityModel.from_dict(em_data)
            em.ensure_size(model.n_slots)
            model.entities[eid] = em
        agg = data.get("aggregate")
        if agg:
            model._agg = EntityModel.from_dict(agg)
            model._agg.ensure_size(model.n_slots)
        return model
