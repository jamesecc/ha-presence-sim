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

## Repository & distribution status

- **Remote:** `git@github.com:jamesecc/ha-presence-sim.git`, branch `main`. Push over **SSH** (the key works). `gh` is now authenticated (see environment note) and usable for releases/API.
- **Visibility: PUBLIC.** HACS custom-repo install works without a PAT. README documents both HACS and manual install.
- **Commit identity:** author/commit with `jamesecc <42879532+jamesecc@users.noreply.github.com>` (GitHub noreply). The original commits used the real iCloud email and were rewritten + force-pushed to scrub it. Keep using the noreply email for all future commits via `git -c user.name=... -c user.email=...`.
- **Packaging:** `hacs.json` lives at the **repo root** (HACS reads it there). The canonical README is at the repo root (HACS renders the root README); the in-folder `custom_components/.../README.md` is just a pointer to avoid drift.
- **License:** MIT (`LICENSE`, © 2026 jamesecc) — chosen as the HACS/HA-custom-integration norm; Apache 2.0 was the considered alternative (declined as heavier than needed).
- **CI:** `.github/workflows/validate.yml` runs on push/PR/weekly-cron with three jobs — `hassfest` (HA manifest/structure validation, Docker action), `hacs` (HACS validation, `category: integration`, `ignore: brands` since the domain isn't in home-assistant/brands), and `syntax` (py_compile + JSON validation). The weekly cron exists to catch HA releases that invalidate the manifest without a push.

## Corrections already applied (don't reintroduce)

- **`.claude/` and `__pycache__/` are git-ignored.** `.claude/settings.local.json` was accidentally staged once and amended out before the first push — it must never be tracked.
- **`manifest.json` key order is load-bearing:** hassfest requires `domain`, `name`, then strictly alphabetical. `integration_type` must come before `iot_class`. Keep new keys alphabetised.
- **GitHub Actions pinned to Node-24 versions:** `actions/checkout@v5`, `actions/setup-python@v6` (Node 20 was deprecated). Don't downgrade.
- **No literal URLs in `strings.json`/`translations/en.json`:** hassfest's `TRANSLATIONS` check fails any step text containing a URL (`[ERROR] [TRANSLATIONS] ... the string should not contain URLs, please use description placeholders instead`). Put a `{placeholder}` in the string and inject the real URL at runtime via `description_placeholders=` on `async_show_form`/`async_show_menu`. The options `help` guide does this for the README link (`{readme_url}` → `README_URL` in `config_flow.py`). This bit `v0.1.0-alpha.2` and was fixed in `310893a`.

## Open decisions / not yet done

- Submitting to the **HACS default store** (would require adding the domain to home-assistant/brands and a PR to HACS) — not done; custom-repo install works in the meantime.
- **Custom Lovelace card / heatmap visualisation for the learned schedule** — deferred to a later date. Today the schedule is viewable via the `export_schedule` service (structured probabilities + a text `table`), which can feed a Markdown card. A dedicated frontend card (e.g. a weekday×time heatmap) would be a nicer UX but is net-new frontend work; not started.
- **Brand icon:** the icon shown in HACS and on the HA integration page comes from `home-assistant/brands` (served via `brands.home-assistant.io`, keyed by domain), **not** from this repo. Print-ready assets are prepared in `brand/` (`icon.png` 256², `icon@2x.png` 512², transparent + trimmed, plus `icon-master.png`). To make the icon appear, PR those to `home-assistant/brands` under `custom_integrations/presence_simulator/`. Not yet submitted (brands is a different repo, out of this session's GitHub scope). `brand/README.md` has the steps.

GitHub "Block command line pushes that expose my email" is **enabled**, so always commit with the noreply email (`42879532+jamesecc@users.noreply.github.com`) or pushes will be rejected.

## Releases

- Repo is **public**. Stable releases `v0.0.1`/`v0.0.2` are on `main`. The **`v0.1.0` line ships as pre-releases** — `v0.1.0-alpha` (`9b2c915`) and `v0.1.0-alpha.2` (`ddf8743`) were cut from the `claude/config-ux-improvements-eibdx0` feature branch; **`main` is still `v0.0.2`** (the 0.1.0 work isn't merged yet).
- `manifest.json` `version` is kept **in sync with the tag** — bump both together (HACS uses the tag as the installed version and also reads the manifest version). The manifest value is the tag **without** the leading `v`. SemVer pre-release tags pass hassfest (e.g. tag `v0.1.0-alpha.2` ↔ manifest `0.1.0-alpha.2`).
- **Release-notes format (user preference):** always deliver proposed release notes as raw GitHub-flavored **markdown inside a single fenced code block** so they can be pasted straight into the GitHub Release — don't only render them in chat. Ask/choose between *cumulative since last stable* and *incremental since last pre-release*.
- Release flow (the user runs the final steps **locally**): bump `manifest.json` + commit, push, `git tag -a vX.Y.Z` **with the noreply identity** (`git -c user.name=jamesecc -c user.email=42879532+jamesecc@users.noreply.github.com tag -a ...`) or the push is rejected by the email-privacy block (GH007), push the tag, then create the GitHub Release (tick *pre-release* for alphas/betas).
- **In the Claude Code web/remote session you can't finish a release yourself:** tag pushes hit the egress-policy `403` (only the session's working branch is pushable) and there's no `gh`/MCP release-creation tool. Prepare the manifest bump + markdown notes and hand the tag/release steps to the user.
- `v0.0.2` fixed a setup crash where the immediate startup sample wrapped the synchronous `_async_sample` `@callback` in `hass.async_create_task` (`TypeError: a coroutine was expected, got None`); it's now called directly.

## Environment

`~/.config` was previously owned by **root** (mode 700), which broke `gh` and made `git` print `Permission denied` warnings. **Fixed** by the user with `sudo chown -R "$(id -un)":staff ~/.config` — git is now clean. `gh` is now **authenticated** as `jamesecc` (git protocol SSH) and works for releases/API; SSH also works for all GitHub operations.
