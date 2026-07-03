# Brand assets

The integration's icon. These files are the **source of truth** for the icon —
but note that Home Assistant and HACS do **not** read icons from this repo.

## Where the icon actually has to live

Both the HA "Devices & Services" page and the HACS UI load integration icons
from the separate [`home-assistant/brands`](https://github.com/home-assistant/brands)
repository, served via `https://brands.home-assistant.io/`, keyed by the
integration **domain** (`presence_simulator`).

To make the icon appear, submit a PR to `home-assistant/brands` placing these
files at:

```
custom_integrations/presence_simulator/icon.png      # 256x256
custom_integrations/presence_simulator/icon@2x.png   # 512x512
```

Requirements (already met by the files here):

- square PNG, with transparency
- `icon.png` is 256x256, `icon@2x.png` is exactly double (512x512)
- trimmed (no surrounding transparent/solid border)

After that PR merges, it is served at
`https://brands.home-assistant.io/presence_simulator/icon.png` and both HACS and
HA pick it up automatically (HA caches brands, so allow some time / a restart).

`hacs.json`/`manifest.json` need no changes — brands is matched purely by domain.

## Files

- `icon.png` — 256x256, for the brands `custom_integrations/presence_simulator/`.
- `icon@2x.png` — 512x512 (hDPI), same destination.
- `icon-master.png` — full-resolution trimmed, transparent master to regenerate from.

## Regenerating from a new source image

The sized assets are produced from the master by downscaling with Lanczos:

```python
from PIL import Image
m = Image.open("brand/icon-master.png").convert("RGBA")
m.resize((512, 512), Image.LANCZOS).save("brand/icon@2x.png", optimize=True)
m.resize((256, 256), Image.LANCZOS).save("brand/icon.png", optimize=True)
```
