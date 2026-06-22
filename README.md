# Presence Simulator

A Home Assistant custom integration that **learns** how your home normally uses
lights and energy over the week, then replays a **realistic, randomized**
version of that activity while you're away — so anyone watching the house can't
tell it's empty.

## What it does

1. **Learns** – every 5 minutes it samples the entities you tell it to *monitor*
   (lights, switches, power/energy sensors, media players, …) and builds a
   per-entity, per-time-of-week probability model (the chance each thing is
   "active" in each 30-minute slot, for each day of the week). Power/energy
   sensors count as "active" above a configurable wattage threshold.
2. **Simulates** – when away mode is on, every time slot it decides which of
   your *controlled* entities (lights, switches, …) to turn on/off, drawn from
   the learned probabilities but with deliberate randomness so the pattern never
   repeats identically day to day:
   - probabilistic on/off per slot (not a fixed replay),
   - a chance to deviate from the learned habit (`randomness`),
   - random timing *jitter* within each slot so changes don't all happen on the
     clock tick,
   - a minimum *dwell* time so lights don't flicker,
   - a cap on how many controlled entities are on at once,
   - quiet overnight hours where almost everything stays off.
   - Controlled entities you never monitored fall back to your home's overall
     activity profile.

   When away mode turns off, anything the simulator switched on is turned back
   off so you don't come home to a lit-up house.

## Install

**Via HACS (recommended):** HACS → ⋮ → *Custom repositories* → add this repo's
URL with category **Integration** → install **Presence Simulator** → restart
Home Assistant.

**Manually:** copy `custom_components/presence_simulator/` into your Home
Assistant `config/custom_components/` folder and restart HA.

Then **Settings → Devices & Services → Add Integration → Presence Simulator**.

## Configure (all in the UI)

- **Step 1 – Entities**: pick entities to *monitor* and entities to *control*.
- **Step 2 – Behaviour**: slot size, randomness, min dwell, jitter, max
  concurrent fraction, power threshold, and quiet hours. Sensible defaults are
  provided. All of this is editable later via **Configure**.

## Entities created

- `switch.presence_simulator_away_simulation` – turn on to start simulating.
- `sensor.presence_simulator_learning_coverage` – % of the weekly schedule
  observed at least once (let it run ~1 week for full coverage).
- `sensor.presence_simulator_observations` – total samples collected.

## Services

- `presence_simulator.reset_model` – wipe learned history.
- `presence_simulator.run_step` – force a simulation step now (for testing).
- `presence_simulator.export_model` – returns a model summary (response data).

## Example away-mode automation

Let it learn for at least a few days first. Then flip the switch based on
presence — e.g. when everyone leaves:

```yaml
alias: Presence Simulator - follow occupancy
trigger:
  - platform: state
    entity_id: group.family   # or zone.home person count, alarm armed_away, etc.
    to: "not_home"
    for: "00:10:00"
  - platform: state
    entity_id: group.family
    to: "home"
action:
  - service: "switch.turn_{{ 'on' if trigger.to_state.state == 'not_home' else 'off' }}"
    target:
      entity_id: switch.presence_simulator_away_simulation
mode: single
```

Or tie it to your alarm: turn the switch on when armed `away`, off when
disarmed.

## Notes

- The model is persisted, so it survives restarts and keeps improving.
- Changing the slot size resets the model (bucket layout changes).
- This is a deterrent, not a guarantee; combine with other security measures.
