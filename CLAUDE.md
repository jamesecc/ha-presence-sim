# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

It doubles as the project's **status file**: sessions have historically committed updates to it whenever a recorded fact changed (see the `Update CLAUDE.md: ...` commits). Keep doing that — **if your change makes anything written here untrue (version, services, architecture, decisions), update this file in the same piece of work.** That is how continuity survives across sessions and models.

## What this is

A single Home Assistant **custom integration** (`custom_components/presence_simulator/`) that learns a home's light/energy usage over the week and replays a realistic, randomized version while away so the house looks occupied. There is no app harness here — the code runs inside a Home Assistant install (minimum HA `2024.4.0`, per `hacs.json`). To use it, the folder is copied into HA's `config/custom_components/` or installed via HACS custom repo, then loaded as an integration.

## How work happens here

- Feature work goes on `claude/<topic>` branches and reaches `main` via PR (e.g. PR #2 merged `claude/more-ux-improvements`). **`main` is the release line.**
- In a Claude Code **web/remote session** you can only push the session's designated working branch — pushes to `main` and tag pushes hit the egress-policy `403`, and there is no `gh` (use the GitHub MCP tools instead). Prepare everything; the user merges PRs and runs release steps **locally** (where `gh` is authenticated as `jamesecc` and SSH works).
- Verification without a real HA instance is limited (see next section). **State plainly what you verified and what you couldn't** — never imply behavioral testing that didn't happen.

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

Behavioral verification beyond pure logic requires running inside a real Home Assistant instance — the user does that; you cannot.

## Definition of done

Before calling any change finished, run from the repo root:

```bash
python3 -m py_compile custom_components/presence_simulator/*.py
python3 -c "import glob, json; [json.load(open(f)) for f in ['hacs.json'] + glob.glob('custom_components/**/*.json', recursive=True)]"
diff custom_components/presence_simulator/strings.json custom_components/presence_simulator/translations/en.json  # must print nothing
```

Then check, where applicable:

- **Pure-logic changes** (`model.py`, `const.py`): actually exercised via the synthetic-package loader with a few concrete inputs, not just compiled.
- **`manifest.json`** still ordered `domain`, `name`, then strictly alphabetical.
- **No literal URLs** in `strings.json`/`translations/en.json` (hassfest fails them — see Corrections).
- **UI text changed** → both strings files updated identically; keys stay in sync with config-flow step ids, `services.yaml`, and entity `translation_key`s (`entity.number.<key>.name`, `entity.time.<key>.name`).
- **Facts in this file** still true; update it if not.
- Commit as `jamesecc <42879532+jamesecc@users.noreply.github.com>` (hard rule, see below).

```bash
python3 -m unittest discover tests   # pure-logic tests for model.py
```

These mirror the three CI jobs (`hassfest`, `hacs`, `syntax`) — if they pass locally, CI almost always passes. The `syntax` job now also runs the strings/translations `diff` and the unit tests.

## Architecture

The data flow is **learn → store → simulate**, with `coordinator.py` as the hub:

- **`model.py`** — `ActivityModel` plus the two pure functions that shape replay: `apply_variation(p, variation, rng)` (multiplicative jitter — keeps 0 at 0, can't exceed 1, preserves bucket ordering) and `next_state(currently_on, p, persistence, low, high, rng)` (sticky two-state chain: `P(off→on)=p/K`, `P(on→off)=(1−p)/K`, so the stationary on-probability is `p` while mean run length in either state is ≥ `K` slots; outside the `PROB_DEADBAND_LOW`/`HIGH` band the answer is unconditional). Both take an injectable `rng` so they're deterministic under test. `fallback_buckets(entity_id)` reports how many buckets are being filled from the household aggregate. The learning core: The week is split into fixed slots (default 30 min → 336 buckets: `weekday * slots_per_day + slot_of_day`, see `bucket_for`; `slot_label` is its inverse). Per monitored entity it accumulates `on`/`total` counts per bucket and exposes a Laplace-smoothed on-probability (`PRIOR_ON`/`PRIOR_TOTAL`). Keeps an aggregate household profile as the fallback for controlled-but-never-monitored entities. `schedule(entity_ids)` returns per-entity probability rows plus an `"aggregate"` row — rendering is left to callers so this module stays HA-free. `is_active(state, attributes, threshold, unavailable_is_off)` maps raw states to active/inactive: numeric states are power sensors (active above the watt threshold); `unknown`/`unavailable` return `None` (skip) by default, but **`False` when `unavailable_is_off`** — used for `CONTROLLABLE_DOMAINS`, because a smart bulb cut from power reports `unavailable` and should be learned as off, not skipped (skipping would fall back to the inflated household aggregate; commit `5d2e3e4`).
- **`coordinator.py`** — `PresenceCoordinator` owns the model and two loops:
  - *Learning* samples every `SAMPLE_MINUTES` (5) and persists. **`monitored` is the union of the monitored and controlled lists** — controlled entities are always learned from, the user never lists anything twice. **`_async_sample` returns early while `away_active`**: controlled entities are in `monitored`, so sampling during simulation would train the model on the simulator's own output. `last_sample` deliberately freezes during away mode.
  - *Simulation* runs only while away mode is on. Each slot, per controlled entity: look up `entity_probability`; **inside quiet hours** the decision is binary on the *raw* probability (`p >= QUIET_KEEP_ON_THRESHOLD` → held on, else off — no chain, no variation, because jittering a device that sits near the threshold would drag it back and forth across the cliff every slot); **otherwise** apply `apply_variation` then `next_state`. Then the max-concurrent cap trims surplus on-decisions, and `_sim_on` is updated with the *final* decisions so the chain can't desync from what was applied. Application still goes through `_desired` / min-dwell / `_schedule_jittered`, via domain `turn_on`/`turn_off` (covers use `open_cover`/`close_cover`). `_start_simulation` seeds `_desired`/`_sim_on` from live entity state so away-on doesn't command every entity. On away-off it turns off everything it switched on (tracked in `_controlled_by_us`).
  - Every applied action is recorded three ways: an in-memory `history` deque (`HISTORY_MAXLEN` 100, feeds the Last-action sensor), an `EVENT_ACTION` bus event (feeds the Logbook), and the `SIGNAL_ACTION` dispatcher signal.
  - **Slot-size changes are non-destructive**: `async_load` parks the old model under `archived_models[str(slot)]` inside the Store blob and restores a previously learned model for the new slot if one exists. (`ActivityModel.from_dict` still returns an empty model on slot mismatch — the parking logic lives in the coordinator; preserve both halves.) `reset_model` discards archives too.
  - `update_option(key, value)` persists a single live knob into `entry.options` — this is how the number/time entities write.
- **`__init__.py`** — entry setup/unload, the options-update listener, and **four services**: `reset_model`, `run_step`, `export_model`, `export_schedule` (the two exports return service responses, `SupportsResponse.OPTIONAL`). The listener reloads the entry **only on a slot-size change**; everything else is read live via `_opt`, so it just nudges entities to re-render. Also renders `export_schedule`'s weekday×time grids and text `table` (`_grid`, `_render_tables`) so `model.py` stays HA-free. Runtime objects live in `hass.data[DOMAIN][entry_id]`.
- **`config_flow.py`** — **single-page** setup and options (step ids `user` / `configure`): controlled entities (required), monitored entities (optional), `slot_minutes` slider, `power_threshold`. The day-to-day tuning knobs are deliberately *not* wizard fields — they're live entities. The options flow adds a `slot_confirm` step when the slot size changed, and `_save()` merges into existing `entry.options` so entity edits don't wipe the live-knob values. `MONITOR_DOMAINS`/`CONTROL_DOMAINS` define which domains the selectors offer; `README_URL` is injected as the `{readme_url}` placeholder.
- **`number.py` / `time.py`** — live tuning entities (device Configuration block), generated from the `NUMBER_TUNABLES`/`TIME_TUNABLES` spec tuples in `const.py`. Scale convention: **displayed × scale = stored** (fraction knobs display as %, scale 0.01; minute knobs scale 1, stored as int). Writes go through `coordinator.update_option` → `entry.options` and take effect immediately, no reload. **Adding a live knob = a const + a spec tuple + translation keys**; no new entity code.
- **`switch.py` / `sensor.py`** — the away-mode switch and three diagnostics: learning coverage, observations, and last action (recent history in attributes). They re-render via dispatcher signals (`SIGNAL_AWAY_STATE`, `SIGNAL_MODEL_UPDATED`, `SIGNAL_ACTION`) emitted by the coordinator.
- **`logbook.py`** — describes `EVENT_ACTION` so every simulated on/off lands on the native Logbook timeline. Not in `PLATFORMS` — HA's logbook discovers it by module name.
- `PLATFORMS` in `const.py` is `["switch", "sensor", "number", "time"]` — a new entity platform means a new module *plus* an entry there.

## Conventions and invariants

- **`const.py` first**: all tunables, config keys, defaults, service names, signals, and the `NUMBER_TUNABLES`/`TIME_TUNABLES` specs live there; config flow, coordinator, and platforms all reference them — add new options there before anything else.
- **`entry.options` is the single source of truth for live tuning.** The coordinator reads settings via `_opt()` (options, then data, then default). Live knobs never require a reload; only `slot_minutes` does.
- **Slot-size changes must stay non-destructive** (the `archived_models` parking described above) — don't regress to wiping the model.
- Learning treats `unavailable`/`unknown` as *skip* for sensor-style domains but as *off* for `CONTROLLABLE_DOMAINS` — keep that split.
- **Randomness varies the *probability*, never the *outcome*.** `v0.1.1` flipped the on/off decision with probability `randomness`, which is symmetric and therefore forced every entity into a flat `[r, 1−r]` band — at the default `r=0.15` a device never once used still switched on ~15% of slots and the learned pattern was discarded. Don't reintroduce outcome flipping.
- **The replay must produce runs, not independent per-slot draws.** `next_state` is a Markov chain for exactly this reason; an independent Bernoulli per slot makes lights blink regardless of how good the learned probabilities are.
- **`min_dwell_minutes` is the persistence knob.** `coordinator.persistence` derives `K = min_dwell / slot_minutes` from it (floored at 1). It was previously a post-hoc gate that was dead code whenever `min_dwell <= slot_minutes`; that gate still exists as a backstop, but the knob's real job is now shaping run length. Reusing the existing option key meant no new entity, no new translation keys and no options migration.
- `strings.json` and `translations/en.json` are kept **identical**; update both when changing UI text, and keep keys in sync with the config-flow steps, `services.yaml`, and entity `translation_key`s.

## Repository & distribution

- **Remote:** `git@github.com:jamesecc/ha-presence-sim.git`, default branch `main`, **public**. HACS custom-repo install works without a PAT; README documents both HACS and manual install.
- **Commit identity — hard rule:** author/commit as `jamesecc <42879532+jamesecc@users.noreply.github.com>` via `git -c user.name=... -c user.email=...`. GitHub's "Block command line pushes that expose my email" is **enabled** — anything committed or tagged with the real iCloud email is rejected (GH007). The original history was rewritten + force-pushed once to scrub that email; never reintroduce it.
- **Packaging:** `hacs.json` lives at the **repo root** (`content_in_root: false`, `render_readme: true`, min HA `2024.4.0`). The canonical README is the root one (HACS renders it); `custom_components/.../README.md` is just a pointer to avoid drift.
- **License:** MIT (`LICENSE`, © 2026 jamesecc) — the HACS/HA-custom-integration norm; Apache 2.0 was considered and declined as heavier than needed.
- **CI:** `.github/workflows/validate.yml` runs on push/PR/weekly-cron with three jobs — `hassfest` (HA manifest/structure validation, Docker action), `hacs` (HACS validation, `category: integration`, `ignore: brands` since the domain isn't in home-assistant/brands), and `syntax` (py_compile + JSON validation). The weekly cron catches HA releases that invalidate the manifest without a push.

## Corrections already applied (don't reintroduce)

- **`.claude/` and `__pycache__/` are git-ignored.** `.claude/settings.local.json` was accidentally staged once and amended out before the first push — it must never be tracked.
- **`manifest.json` key order is load-bearing:** hassfest requires `domain`, `name`, then strictly alphabetical. `integration_type` must come before `iot_class`. Keep new keys alphabetised.
- **GitHub Actions pinned to Node-24 versions:** `actions/checkout@v5`, `actions/setup-python@v6` (Node 20 was deprecated). Don't downgrade.
- **No literal URLs in `strings.json`/`translations/en.json`:** hassfest's `TRANSLATIONS` check fails any step text containing a URL (`[ERROR] [TRANSLATIONS] ... the string should not contain URLs, please use description placeholders instead`). Put a `{placeholder}` in the string and inject the real URL at runtime via `description_placeholders=` on `async_show_form`. The options `configure` step does this for the README link (`{readme_url}` → `README_URL` in `config_flow.py`). This bit `v0.1.0-alpha.2` and was fixed in `310893a`.
- **Don't wrap synchronous `@callback`s in `hass.async_create_task`:** the immediate startup sample once did (`TypeError: a coroutine was expected, got None`, crashed setup) — fixed in `v0.0.2` by calling `_async_sample` directly.

## Releases

- **Current state: `main` is `v0.1.1`; `v0.2.0` is prepared and awaiting tag** (manifest bumped to `0.2.0` on `claude/home-assistant-security-review-eibdx0` — the simulation-replay rewrite). Tag history: `v0.0.1`, `v0.0.2`, `v0.1.0-alpha`, `v0.1.0-alpha.2`, `v0.1.0-alpha.3`, `v0.1.1-alpha.1`, `v0.1.1-alpha.2`, `v0.1.1`. Pattern: alphas are cut from the feature branch as GitHub pre-releases; the stable is tagged after merge to `main`.
- `manifest.json` `version` is kept **in sync with the tag** — bump both together (HACS uses the tag as the installed version and also reads the manifest). The manifest value is the tag **without** the leading `v`; SemVer pre-release tags pass hassfest (tag `v0.1.1-alpha.2` ↔ manifest `0.1.1-alpha.2`).
- **Release-notes format (user preference, keep):** always deliver proposed release notes as raw GitHub-flavored **markdown inside a single fenced code block** so they can be pasted straight into the GitHub Release — don't only render them in chat. Ask/choose between *cumulative since last stable* and *incremental since last pre-release*.
- Release flow (the user runs the final steps **locally**): bump `manifest.json` + commit, push, `git -c user.name=jamesecc -c user.email=42879532+jamesecc@users.noreply.github.com tag -a vX.Y.Z` (noreply identity or the tag push is rejected, GH007), push the tag, create the GitHub Release (tick *pre-release* for alphas/betas).
- **In a web/remote session you can't finish a release yourself** (tag pushes 403, no release-creation tool): prepare the manifest bump + markdown notes and hand the tag/release steps to the user.

## Open decisions / not yet done

- Submitting to the **HACS default store** (requires adding the domain to home-assistant/brands and a PR to HACS) — not done; custom-repo install works in the meantime.
- **Custom Lovelace card / heatmap visualisation for the learned schedule** — deferred. Today the schedule is viewable via the `export_schedule` service (structured probabilities + a text `table`), which can feed a Markdown card. A dedicated weekday×time heatmap card would be nicer UX but is net-new frontend work; not started.
- **Brand icon:** the icon in HACS and on the HA integration page comes from `home-assistant/brands` (keyed by domain), **not** from this repo. Print-ready assets live in `brand/` (`icon.png` 256², `icon@2x.png` 512², transparent + trimmed, plus `icon-master.png`). To make it appear, PR them to `home-assistant/brands` under `custom_integrations/presence_simulator/` — not yet submitted (different repo, outside session GitHub scope). `brand/README.md` has the steps.
- **Tests cover `model.py` only.** `tests/test_model.py` (17 tests, plain `unittest`, loads the pure modules via the synthetic-package loader so no HA install is needed) runs in the `syntax` CI job. Everything in `coordinator.py`, the config flow and the platforms is still verified by hand in a real HA install.

## Environment

- **Local machine (the user's):** `gh` is authenticated as `jamesecc` (git protocol SSH) and works for releases/API; SSH works for all GitHub operations. (A past quirk — `~/.config` owned by root, breaking `gh` and making git print `Permission denied` — was fixed with `chown`; if those symptoms reappear, that's the cause.)
- **Claude Code web/remote sessions:** no `gh`; use the GitHub MCP tools. Only the session's designated working branch is pushable.
