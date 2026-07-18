# boss template — assets

First-party, clean-room asset pipeline for the Mode 7 animated boss battle.
Everything here is original art generated deterministically by two scripts; the
committed binaries/`.inc`s are the artifacts the template assembles against.

## What's here

| File | What it is |
|------|-----------|
| `make_boss.py` | Authors `boss.png` (1024×1024, the 128×128-tile Mode 7 grid) — the "Cragmaw Sentinel" horned stone golem head centered in a dark arena — then runs it through `convert_map_png` + `interleave_mode7_data` to emit the VRAM blob and palette. |
| `boss.png` | The authored source image (committed so the art is reviewable without running the script). |
| `boss_map.bin` | **Exactly 32,768 bytes** — interleaved Mode 7 VRAM blob (even bytes = 128×128 tilemap, odd = 8bpp tile pixels). This is what `sf_mode7_load_map boss_map, #$8000` DMAs to VRAM word `$0000`. |
| `boss_palette.inc` | ca65 CGRAM data: `boss_pal:` (BGR555 `.word`s) + `BOSS_PAL_COUNT`. CGRAM index 0 = the dark arena backdrop (shown wherever BG1 is off). |
| `make_sprites.py` | Hand-authors the OBJ battle actors (player gunship, enemy projectile, player shot) and encodes them to 4bpp planar CHR + an OBJ palette. |
| `sprites.inc` | ca65 OBJ data: `sprite_chr:` (1024-byte 4bpp blob), `sprite_chr_bytes`, `sprite_pal:` (16 BGR555 words), `SPRITE_PAL_COUNT`, and base-tile equates. |

## Regenerate

Run from a kit root that has `toolchain/` on the path (the materialized kit
tree; in the parent monorepo run from the parent root — the import path is the
same). Output is deterministic: same script, same bytes.

```bash
PYTHONPATH=. python3 templates/boss/assets/make_boss.py
PYTHONPATH=. python3 templates/boss/assets/make_sprites.py
```

`make_sprites.py` is stdlib-only (no `toolchain/` import needed), but the
`PYTHONPATH=.` form is harmless and keeps the two commands uniform.

## Committed-output contract

The `.bin` / `.inc` / `.png` outputs are **committed** and are the source of
record the template assembles against. Regenerate them only when you change the
art, and commit the regenerated files in the same change. `boss_map.bin` must
always be exactly 32,768 bytes.

## Load contract (how the template wires these up)

Mode 7 owns VRAM `$0000–$3FFF`; OBJ CHR goes to the OBJ name base at VRAM word
`$4000` (= tile **1024**). During forced blank, after `sf_coldstart` and before
the screen turns on:

```asm
; Mode 7 arena map -> VRAM word $0000, palette -> CGRAM
sf_mode7_load_map boss_map, #$8000
; (upload boss_pal / BOSS_PAL_COUNT to CGRAM via the engine palette path)

; battle actors -> OBJ name base (VRAM word $4000 = tile 1024)
sf_load_obj_chr 1024, sprite_chr, sprite_chr_bytes
sf_load_obj_pal 0, sprite_pal
```

A sprite's OAM tile number is `1024 + SPR_<actor>`:

| Equate | Actor | Size | Tiles (relative to base) |
|--------|-------|------|--------------------------|
| `SPR_PLAYER_T0` (`$00`) | player gunship, neutral | 16×16 | `{0, 1, 16, 17}` |
| `SPR_PLAYER_T1` (`$02`) | player gunship, hit/flash | 16×16 | `{2, 3, 18, 19}` |
| `SPR_PROJECTILE` (`$04`) | enemy projectile orb | 8×8 | `{4}` |
| `SPR_SHOT` (`$05`) | player shot (damages boss) | 8×8 | `{5}` |

Use OBSEL size pair 3 (16×16 small / 32×32 large). The player is a 16×16-small
sprite; the 8×8 actors also use 16×16-small slots (the unused 3 subtiles are
transparent, so they render 8×8).
