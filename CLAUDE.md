# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single Home Assistant **custom integration** (`custom_components/presence_simulator/`) that learns a home's light/energy usage over the week and replays a realistic, randomized version while away so the house looks occupied. There is no app harness here — the code runs inside a Home Assistant install. To use it, the folder is copied into HA's `config/custom_components/` and loaded as an integration.

## Developing without Home Assistant installed

HA is not a dependency in this repo, so most modules can't be imported directly (they pull in `homeassistant` and `voluptuous`). Validate changes with:

```bash
cd custom_components/presence_simulator
python3 -m py_compile *.py            # syntax-check everything
python3 -c "import json; [json.load(open(f)) for f in ['manifest.json','strings.json','translations/en.json']]"
```

`model.py` and `const.py` are **pure Python** (no HA imports) and hold the testable logic. Because `__init__.py` imports HA, you can't `import presence_simulator.model` — load the pure modules under a synthetic package that skips `__init__.py`:

```python
import sys, types, importlib.util, os
pkg = types.ModuleType('ps'); pkg.__path__ = [os.getcwd()]; sys.modules['ps'] = pkg
def load(name):
    spec = importlib.util.spec_from_file_location(f'ps.{name}', f'{name}.py')
    mod = importlib.util.module_from_spec(spec); sys.modules[f'ps.{name}'] = mod
    spec.loader.exec_module(mod); return mod
load('const'); model = load('model')   # now exercise model.ActivityModel, model.bucket_for, ...
```

Behavioral verification beyond pure logic requires running inside a real Home Assistant instance.

## Architecture

The data flow is **learn → store → simulate**, with `coordinator.py` as the hub:

- **`model.py`** — `ActivityModel`: the learning core. The week is split into fixed slots (default 30 min → 336 buckets: `weekday * slots_per_day + slot_of_day`, see `bucket_for`). Per monitored entity it accumulates `on`/`total` counts per bucket and exposes a Laplace-smoothed on-probability. `is_active()` maps raw states to active/inactive (numeric states = power sensors, active above a watt threshold; returns `None` for unknown/unavailable so gaps don't pollute totals). Keeps an aggregate household profile as the fallback for controlled-but-never-monitored entities.
- **`coordinator.py`** — `PresenceCoordinator` owns the model and two loops:
  - *Learning* runs always: samples monitored entities every `SAMPLE_MINUTES` (5) and persists.
  - *Simulation* runs only while away mode is on: each slot it computes a desired on/off per controlled entity from `entity_probability`, then layers randomness — deviation chance, per-entity min-dwell, per-change timing jitter, max-concurrent cap, and quiet-hours suppression. Changes are applied via `homeassistant`/domain `turn_on`/`turn_off` (covers use `open`/`close`). On away-off it turns back off everything it switched on (tracked in `_controlled_by_us`).
- **`__init__.py`** — entry setup/unload, options-update reload listener, and the three services (`reset_model`, `run_step`, `export_model`). Runtime objects live in `hass.data[DOMAIN][entry_id]`.
- **`config_flow.py`** — two-step UI (entities, then tuning) for both initial config and options, using entity `selector`s. `MONITOR_DOMAINS`/`CONTROL_DOMAINS` define which entity domains are offered.
- **`switch.py` / `sensor.py`** — the away-mode switch and learning-coverage/observations diagnostics. They re-render via dispatcher signals (`SIGNAL_AWAY_STATE`, `SIGNAL_MODEL_UPDATED`) emitted by the coordinator.

## Conventions and invariants

- All tunables and keys live in `const.py`; config flow, coordinator, and defaults all reference them — add new options there first.
- The coordinator reads settings via `_opt()`, which checks `entry.options` then `entry.data`, so options-flow edits take effect on reload without touching `data`.
- The learned model is persisted with HA's `Store`. **Changing `slot_minutes` resets the model** (`ActivityModel.from_dict` returns an empty model on slot-size mismatch) because the bucket layout changes — preserve this guard.
- `strings.json` and `translations/en.json` are kept identical; update both when changing UI text, and keep keys in sync with the config-flow steps and `services.yaml`.
