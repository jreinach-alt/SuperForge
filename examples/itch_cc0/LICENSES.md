# examples/itch_cc0/ — Asset Pack Provenance & Licenses

Per-pack source, author, and license for every art pack shipped with the kit.
These packs are the **source material** for the asset pipeline (`tools/png2snes.py`)
and the converted assets committed under `templates/*/assets/`.

CC0 requires no attribution — this file exists to record provenance for the
release. **Policy** (see CONTRIBUTING.md): CC0 / public-domain packs are
accepted into this directory, with source URL + author recorded here at the
time of addition. One pack (Rotting Pixels, below) ships under a recorded
no-strings permissive grant instead of literal CC0 — the grant covers
everything the kit does with it (free + commercial use, modification, no
attribution required); it is recorded as what it actually is.

All four grants below were re-verified against the live itch.io pages on
**2026-07-18** (push-checklist item F4). The analogStudios_ pages now
redirect to the author's renamed account, `kevins-moms-house.itch.io` —
both URLs are recorded.

| Pack (zip) | Author | Source | License |
|---|---|---|---|
| `Four Seasons Platformer Tileset [16x16][FREE] - RottingPixels.zip` | Rotting Pixels | https://rottingpixels.itch.io/four-seasons-platformer-tileset-16x16free | **Custom permissive grant (not CC0)** — itch.io page, quoted live 2026-07-18: "This asset pack can be used in both free and commercial projects. You can modify it to suit your own needs. Credit is not necessary, but appreciated." The in-zip `RottingPixels.txt` is a follow-us note, not a license; the grant is on the itch.io page. |
| `Four_Seasons_Platformer_Sprites.zip` | analogStudios_ (Kevin's Mom's House) | https://analogstudios.itch.io/four-seasons-platformer-sprites → https://kevins-moms-house.itch.io/four-seasons-platformer-sprites | CC0 — verified live 2026-07-18; page links the CC-0 deed ("credit would be appreciated but not necessary [CC-0]") |
| `camelot_ [version 1.0].zip` | analogStudios_ (Kevin's Mom's House) — the `legends_` series | https://analogstudios.itch.io/camelot → https://kevins-moms-house.itch.io/camelot | CC0 — verified live 2026-07-18; page links the CC-0 deed |
| `dungeonSprites_v1.0.zip` | analogStudios_ (Kevin's Mom's House) — the `fantasy_` series | https://analogstudios.itch.io/dungeonsprites → https://kevins-moms-house.itch.io/dungeonsprites | CC0 — verified live 2026-07-18; page links the CC-0 deed |
| `SNES_overworld_RPG_character_sprite_top-down_persp.zip` | project-owner-generated via an AI sprite tool (2026-04) | n/a (generated, not downloaded) | Included **solely as the converter's canonical reject fixture** — it is deliberately *not* hardware-scale pixel art and `png2snes.py` must reject it with a useful error. The zip's `metadata.json` embeds the original generation prompt (style reference scrubbed to mechanism-only — no commercial-game titles); no commercial asset is contained or extracted, and nothing in the kit's templates derives from this pack. |

Converted derivatives in this repo (e.g. `templates/brawler/assets/*.inc`,
`templates/shmup/assets/*.inc`) are mechanical format conversions of the
packs above. Conversions of the CC0 packs are released CC0 as well; the
`terrain.inc` tiles converted from the Rotting Pixels tileset
(`templates/brawler/`, `templates/shmup/`, `tests/fixtures/png2snes/`)
carry that pack's permissive grant (free + commercial use, modification
allowed, credit optional) rather than CC0 — we cannot re-dedicate someone
else's work to the public domain.
