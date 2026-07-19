#!/usr/bin/env python3
"""make_enemy.py — the m7_dungeon enemy OBJ, converted from a CC0 pack sprite.

Wave-D dressing: the enemy is the dungeonSprites **demon** — a WARM orange-red
character, deliberately not the cool knight hero and not the cool blue floor, so a
rendered frame plainly shows the enemy on the rotating floor and the color-band
enemy test can tell it from wall/floor/hero. Converted through `tools/png2snes.py`
(imported), then emitted in the shape main.asm consumes (enemy_chr / ENEMY_CHR_BYTES
/ enemy_pal / ENEMY_TILE), so the ROM's CHR/pal load path is unchanged.

Why the demon (not the S1 "slime/skeleton"): slime is olive-GREEN and skeleton is
bone-WHITE — neither is warm-dominant, and the white would collide with the knight
hero's bone-white in the phantom-diamond regression. The demon keeps a clean warm
enemy anchor that separates from the warm brick wall by BRIGHTNESS (its orange body
is brighter/redder than any wall tone). It uses its OWN OBJ palette (palette 1).

  cmd (equivalent CLI): png2snes.py sprite \\
      art/dungeonSprites_v1.0/demon_/idle_/lIdle_0.png --size 16 --frames 0-0 \\
      --name enemy --out templates/m7_dungeon/assets/enemy.inc
  pack:  dungeonSprites_v1.0 — analogStudios_ (Kevin's Mom's House), the fantasy_ series
  grant: CC0 (public domain; no attribution required) — see examples/itch_cc0/LICENSES.md

Regenerate (from the materialized kit root, after unzipping the pack):
    unzip -o -q examples/itch_cc0/dungeonSprites_v1.0.zip -d art/
    PYTHONPATH=. python3 templates/m7_dungeon/assets/make_enemy.py
"""
from __future__ import annotations
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT_ROOT = HERE.parents[2]
SRC_PNG = KIT_ROOT / "art" / "dungeonSprites_v1.0" / "demon_" / "idle_" / "lIdle_0.png"
NAME = "enemy"


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
    boxed, over = p.recenter(img, 16, "center")
    if over:
        raise SystemExit(f"{src_png}: content {over} exceeds the 16x16 OBJ box.")
    cols = p.opaque_colors(boxed)
    if len(cols) > 15:
        raise SystemExit(f"{src_png}: {len(cols)} colours > 15 (OBJ palette limit).")
    pal_words, c2i = p.build_palette(cols)
    rows = p.index_frame(boxed, c2i)

    def quad(ox, oy):
        return p.encode_tile_4bpp([rows[oy + y][ox:ox + 8] for y in range(8)])
    tiles = {0: quad(0, 0), 1: quad(8, 0), 16: quad(0, 8), 17: quad(8, 8)}
    blob = bytearray()
    for t in range(18):
        blob.extend(tiles.get(t, bytes(32)))

    lines = [
        f"; enemy.inc — GENERATED ({Path(__file__).name}); DO NOT EDIT BY HAND.",
        f"; cmd: png2snes.py sprite {src_png.relative_to(KIT_ROOT)} --size 16 "
        f"--frames 0-0 --name {name} (re-emitted to the enemy_chr/ENEMY_* contract)",
        "; pack: dungeonSprites_v1.0 — analogStudios_ (Kevin's Mom's House)",
        "; grant: CC0 (public domain, no attribution) — examples/itch_cc0/LICENSES.md",
        "ENEMY_TILE = 0",
        "enemy_chr:",
    ]
    for i in range(0, len(blob), 16):
        lines.append("    .byte " + ", ".join(f"${b:02X}" for b in blob[i:i + 16]))
    lines.append(f"ENEMY_CHR_BYTES = {len(blob)}")
    lines.append("")
    lines.append("enemy_pal:")
    for w in pal_words:
        lines.append(f"    .word ${w:04X}")
    lines.append("ENEMY_PAL_COUNT = 16")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    (HERE / "enemy.inc").write_text(build_inc(NAME, SRC_PNG))
    print(f"wrote enemy.inc (demon, from {SRC_PNG.name})")


if __name__ == "__main__":
    main()
