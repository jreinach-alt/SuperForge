#!/usr/bin/env python3
"""make_hero.py — the m7_dungeon hero OBJ, converted from a CC0 pack sprite.

Wave-D dressing: the hero is the dungeonSprites **knight** (a real hardware-scale
pixel-art character), converted through the kit front door `tools/png2snes.py`
(its recenter + <=15-colour palette + 4bpp VRAM-grid encoder are imported here so
the conversion IS png2snes's), then emitted in the .inc shape main.asm already
consumes (hero_chr / HERO_CHR_BYTES / hero_pal / HERO_TILE), so the ROM's CHR/pal
load path is unchanged — only the pixels + palette change.

Why the knight (not the S1 "top-down RPG character pack"): that pack
(SNES_overworld_RPG_character_sprite_top-down_persp) is the converter's canonical
REJECT fixture (AI art, 40 colours) — png2snes must reject it, so it cannot dress
a rail. The knight is a cool/neutral steel+bone hero, kept distinct from the warm
demon enemy and the warm brick walls for a clean color-band split.

  cmd (equivalent CLI): png2snes.py sprite \\
      art/dungeonSprites_v1.0/knight_/idle_/lIdle_0.png --size 16 --frames 0-0 \\
      --name hero --out templates/m7_dungeon/assets/hero.inc
  pack:  dungeonSprites_v1.0 — analogStudios_ (Kevin's Mom's House), the fantasy_ series
  grant: CC0 (public domain; no attribution required) — see examples/itch_cc0/LICENSES.md

Regenerate (from the materialized kit root, after unzipping the pack):
    unzip -o -q examples/itch_cc0/dungeonSprites_v1.0.zip -d art/
    PYTHONPATH=. python3 templates/m7_dungeon/assets/make_hero.py
"""
from __future__ import annotations
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT_ROOT = HERE.parents[2]                     # templates/m7_dungeon/assets -> kit root
SRC_PNG = KIT_ROOT / "art" / "dungeonSprites_v1.0" / "knight_" / "idle_" / "lIdle_0.png"
NAME = "hero"


def _load_png2snes():
    spec = importlib.util.spec_from_file_location(
        "png2snes", str(KIT_ROOT / "tools" / "png2snes.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_inc(name: str, src_png: Path) -> str:
    p = _load_png2snes()
    if not src_png.exists():
        raise SystemExit(f"{src_png} not found — unzip the pack into art/ first "
                         f"(see this file's header).")
    img = p.load_rgba(src_png)
    boxed, over = p.recenter(img, 16, "center")    # 24x24 pack frame -> 16x16 OBJ box
    if over:
        raise SystemExit(f"{src_png}: content {over} exceeds the 16x16 OBJ box.")
    cols = p.opaque_colors(boxed)
    if len(cols) > 15:
        raise SystemExit(f"{src_png}: {len(cols)} colours > 15 (OBJ palette limit).")
    pal_words, c2i = p.build_palette(cols)          # 16 words, idx0 transparent
    rows = p.index_frame(boxed, c2i)                # 16 rows x 16 indices

    # 16x16 OBJ VRAM layout: tile0=TL, tile1=TR, tile16=BL, tile17=BR. Upload 18
    # tiles (0..17) with 2..15 zero-filled so tile17 lands at the right VRAM offset
    # (identical layout to the pre-dressing generator, so main.asm is unchanged).
    def quad(ox, oy):
        return p.encode_tile_4bpp([rows[oy + y][ox:ox + 8] for y in range(8)])
    tiles = {0: quad(0, 0), 1: quad(8, 0), 16: quad(0, 8), 17: quad(8, 8)}
    blob = bytearray()
    for t in range(18):
        blob.extend(tiles.get(t, bytes(32)))

    lines = [
        f"; hero.inc — GENERATED ({Path(__file__).name}); DO NOT EDIT BY HAND.",
        f"; cmd: png2snes.py sprite {src_png.relative_to(KIT_ROOT)} --size 16 "
        f"--frames 0-0 --name {name} (re-emitted to the hero_chr/HERO_* contract)",
        "; pack: dungeonSprites_v1.0 — analogStudios_ (Kevin's Mom's House)",
        "; grant: CC0 (public domain, no attribution) — examples/itch_cc0/LICENSES.md",
        "HERO_TILE = 0",
        "hero_chr:",
    ]
    for i in range(0, len(blob), 16):
        lines.append("    .byte " + ", ".join(f"${b:02X}" for b in blob[i:i + 16]))
    lines.append(f"HERO_CHR_BYTES = {len(blob)}")
    lines.append("")
    lines.append("hero_pal:")
    for w in pal_words:                              # 16 words (padded by build_palette)
        lines.append(f"    .word ${w:04X}")
    lines.append("HERO_PAL_COUNT = 16")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    (HERE / "hero.inc").write_text(build_inc(NAME, SRC_PNG))
    print(f"wrote hero.inc (knight, from {SRC_PNG.name})")


if __name__ == "__main__":
    main()
