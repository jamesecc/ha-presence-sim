"""Pure-Python tests for model.py.

Home Assistant is not a dependency of this repo, so ``presence_simulator`` can't
be imported normally — ``__init__.py`` pulls in ``homeassistant``. The loader
below mounts the HA-free modules under a synthetic package that skips
``__init__.py``, the same trick documented in CLAUDE.md.

Run from the repo root:  python3 -m unittest discover tests
"""

from __future__ import annotations

import importlib.util
import os
import random
import sys
import types
import unittest

_COMPONENT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "custom_components",
    "presence_simulator",
)


def _load_pure_modules():
    pkg = types.ModuleType("ps")
    pkg.__path__ = [_COMPONENT]
    sys.modules["ps"] = pkg

    def load(name):
        spec = importlib.util.spec_from_file_location(
            f"ps.{name}", os.path.join(_COMPONENT, f"{name}.py")
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"ps.{name}"] = mod
        spec.loader.exec_module(mod)
        return mod

    return load("const"), load("model")


const, model = _load_pure_modules()


class TestDeadband(unittest.TestCase):
    """Outside the deadband the answer must not depend on chance at all."""

    def test_below_low_is_always_off(self):
        # A never-used device still reads ~0.05-0.06 after weeks of smoothing.
        for p in (0.0, 0.053, 0.062, const.PROB_DEADBAND_LOW):
            for currently_on in (False, True):
                for seed in range(50):
                    rng = random.Random(seed)
                    self.assertFalse(
                        model.next_state(currently_on, p, 3.0, rng=rng),
                        f"p={p} currently_on={currently_on} seed={seed}",
                    )

    def test_above_high_is_always_on(self):
        for p in (const.PROB_DEADBAND_HIGH, 0.95, 1.0):
            for currently_on in (False, True):
                for seed in range(50):
                    rng = random.Random(seed)
                    self.assertTrue(
                        model.next_state(currently_on, p, 3.0, rng=rng),
                        f"p={p} currently_on={currently_on} seed={seed}",
                    )


class TestChainStatistics(unittest.TestCase):
    """The chain must reproduce the learned duty cycle and produce runs."""

    STEPS = 20000

    def _simulate(self, p, persistence, seed=1234):
        rng = random.Random(seed)
        on = False
        on_steps = 0
        changes = 0
        for _ in range(self.STEPS):
            nxt = model.next_state(on, p, persistence, rng=rng)
            if nxt != on:
                changes += 1
            on = nxt
            on_steps += on
        return on_steps / self.STEPS, changes

    def test_duty_cycle_matches_learned_probability(self):
        for p in (0.25, 0.5, 0.842):
            duty, _ = self._simulate(p, 3.0)
            self.assertAlmostEqual(
                duty, p, delta=0.03, msg=f"p={p} produced duty={duty:.3f}"
            )

    def test_mean_run_length_respects_persistence(self):
        persistence = 3.0
        for p in (0.25, 0.5, 0.842):
            _, changes = self._simulate(p, persistence)
            mean_run = self.STEPS / max(1, changes)
            self.assertGreaterEqual(
                mean_run,
                persistence,
                msg=f"p={p} gave mean run {mean_run:.2f} < {persistence}",
            )

    def test_higher_persistence_means_fewer_changes(self):
        _, few = self._simulate(0.5, 2.0)
        _, fewer = self._simulate(0.5, 8.0)
        self.assertLess(fewer, few)

    def test_persistence_below_one_is_clamped(self):
        # Guards against a division blow-up if slot_minutes exceeds min_dwell.
        duty, _ = self._simulate(0.5, 0.0)
        self.assertAlmostEqual(duty, 0.5, delta=0.03)


class TestApplyVariation(unittest.TestCase):
    """Variation must perturb the probability without creating a floor.

    This is the property the previous outcome-flipping scheme violated: it
    forced every device into a flat [r, 1-r] band regardless of what was
    learned, which is what made the overnight replay look random.
    """

    def test_zero_stays_zero(self):
        for variation in (0.0, 0.15, 0.5, 0.6):
            for seed in range(50):
                rng = random.Random(seed)
                self.assertEqual(model.apply_variation(0.0, variation, rng=rng), 0.0)

    def test_never_exceeds_one(self):
        for variation in (0.15, 0.5, 0.6):
            for seed in range(100):
                rng = random.Random(seed)
                self.assertLessEqual(model.apply_variation(1.0, variation, rng=rng), 1.0)

    def test_no_variation_is_identity(self):
        for p in (0.0, 0.062, 0.5, 0.842, 1.0):
            self.assertEqual(model.apply_variation(p, 0.0), p)

    def test_stays_within_multiplicative_band(self):
        variation = 0.15
        for seed in range(200):
            rng = random.Random(seed)
            out = model.apply_variation(0.5, variation, rng=rng)
            self.assertGreaterEqual(out, 0.5 * (1 - variation) - 1e-9)
            self.assertLessEqual(out, 0.5 * (1 + variation) + 1e-9)

    def test_never_lifts_a_dead_device_over_the_deadband(self):
        # A light never once on reads ~0.062; variation must not wake it up.
        for seed in range(500):
            rng = random.Random(seed)
            self.assertLess(
                model.apply_variation(0.062, 0.15, rng=rng),
                const.PROB_DEADBAND_LOW,
            )


class TestBucketing(unittest.TestCase):
    """bucket_for / slot_label are inverses."""

    def test_round_trip(self):
        from datetime import datetime

        for slot_minutes in (15, 30, 60):
            spd = model.slots_per_day(slot_minutes)
            for weekday in range(7):
                # 2024-01-01 was a Monday.
                for hour, minute in ((0, 0), (6, 30), (13, 45), (23, 59)):
                    when = datetime(2024, 1, 1 + weekday, hour, minute)
                    bucket = model.bucket_for(when, slot_minutes)
                    self.assertEqual(bucket // spd, weekday)
                    day, label = model.slot_label(bucket, slot_minutes)
                    self.assertEqual(day, weekday)
                    hh, mm = (int(x) for x in label.split(":"))
                    self.assertLessEqual(hh * 60 + mm, hour * 60 + minute)
                    self.assertLess(
                        hour * 60 + minute - (hh * 60 + mm), slot_minutes
                    )

    def test_total_slots(self):
        self.assertEqual(model.total_slots(30), 336)
        self.assertEqual(model.total_slots(15), 672)


class TestFallbackBuckets(unittest.TestCase):
    def test_unknown_entity_is_entirely_fallback(self):
        am = model.ActivityModel(30)
        self.assertEqual(am.fallback_buckets("light.nope"), am.n_slots)

    def test_observations_reduce_the_count(self):
        am = model.ActivityModel(30)
        am.observe("light.a", 0, True)
        am.observe("light.a", 5, False)
        self.assertEqual(am.fallback_buckets("light.a"), am.n_slots - 2)


class TestIsActive(unittest.TestCase):
    def test_unavailable_is_off_only_for_controllables(self):
        self.assertIsNone(model.is_active("unavailable", None, 5.0))
        self.assertFalse(
            model.is_active("unavailable", None, 5.0, unavailable_is_off=True)
        )

    def test_numeric_uses_power_threshold(self):
        self.assertTrue(model.is_active("12.5", None, 5.0))
        self.assertFalse(model.is_active("1.2", None, 5.0))


if __name__ == "__main__":
    unittest.main()
