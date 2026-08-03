"""Activity model: learns per-entity on/off patterns by time-of-week.

The week is divided into fixed time slots (e.g. 30 min). For each monitored
entity and each slot we accumulate how often it was observed "active". The
resulting on-probability per slot is what the simulator replays during away
mode, with added randomness so the pattern never repeats identically.
"""

from __future__ import annotations

import random as _random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .const import (
    ACTIVE_STATES,
    PRIOR_ON,
    PRIOR_TOTAL,
    PROB_DEADBAND_HIGH,
    PROB_DEADBAND_LOW,
)


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


def apply_variation(p: float, variation: float, rng=_random) -> float:
    """Perturb a learned probability so the replay is never identical.

    The jitter is *multiplicative* — ``p`` is scaled by a factor drawn from
    ``[1 - variation, 1 + variation]`` — which keeps 0 at 0, cannot exceed 1 and
    preserves the ordering of buckets. That matters: this replaces an earlier
    scheme that flipped the on/off *outcome* with probability ``variation``,
    which forced every device into a flat ``[variation, 1 - variation]`` band
    and discarded the learned pattern entirely.
    """
    if variation <= 0.0:
        return p
    return min(1.0, max(0.0, p * (1.0 + rng.uniform(-variation, variation))))


def next_state(
    currently_on: bool,
    p: float,
    persistence: float,
    low: float = PROB_DEADBAND_LOW,
    high: float = PROB_DEADBAND_HIGH,
    rng=_random,
) -> bool:
    """Advance one slot of a sticky two-state chain.

    Real households switch a light on and leave it on for a while. Drawing
    independently against ``p`` every slot instead produces a blink pattern with
    no runs, so this uses transition probabilities

        P(off -> on) = p / persistence
        P(on -> off) = (1 - p) / persistence

    whose stationary on-probability is exactly ``p`` while the mean run length
    in *either* state is at least ``persistence`` slots.

    Outside the deadband the answer is unconditional: below ``low`` the device
    stays off and above ``high`` it stays on, so the residual smoothing prior
    can't leak into a device that is genuinely never (or always) used.
    """
    if p <= low:
        return False
    if p >= high:
        return True
    k = max(1.0, persistence)
    if currently_on:
        return rng.random() >= (1.0 - p) / k
    return rng.random() < p / k


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

    def fallback_buckets(self, entity_id: str) -> int:
        """How many week-buckets this entity has no observations of its own for.

        ``entity_probability`` silently substitutes the household aggregate for
        those buckets, so an entity with a high count here is being replayed
        from someone else's pattern rather than its own.
        """
        em = self.entities.get(entity_id)
        if em is None:
            return self.n_slots
        covered = sum(1 for t in em.total[: self.n_slots] if t > 0)
        return self.n_slots - covered

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
