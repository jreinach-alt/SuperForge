#!/usr/bin/env python3
"""make_ships.py — the shmup hero + enemy spaceships + kill-burst explosion,
converted from the CC0 AlcWilliam "Spaceship Pack" (examples/itch_cc0/Spaceship
Pack.zip).

Why this preprocessing generator exists
---------------------------------------
The pack draws each ship as a detailed **48x48** sprite with smooth shading —
NOT hardware-scale pixel art (png2snes.detect_integer_scale == 1). The shmup
rail renders its actors at **16x16** (the OBSEL 8x8/16x16 size pair; the hero
and ghost are drawn `spr ... , #2` = the 16x16 large half). png2snes.py never
scales — it re-centers content into the box and REJECTS content larger than it —
so the art has to be brought down to the 16x16 grid first. This generator does
that pre-authoring the same way make_terrain.py pre-authors the island:

  1. unzip the registered pack, pick one ship for the hero and a DIFFERENT ship
     for the enemy (a hostile silhouette, rotated 180 so it noses DOWN at the
     player — the "ghost" slot in main.asm);
  2. edge-bleed + area-downscale (BOX) each 48x48 ship to the 16x16 box, with a
     small contrast/sharpen pass so the silhouette survives the 3x reduction;
  3. composite the pack's engine-flame plume (turbo_blue for the hero, turbo_green
     for the enemy's alien thrusters) at the engine, ALTERNATING the plume's two
     frames across the 8 idle steps — this is the sprite animation the rail's
     shared frame clock cycles (OAM tile 0,2,..,E per step; the plume flickers);
  4. quantize the whole 8-frame set to ONE shared <=15-color OBJ palette;
  5. hand the finished 16x16 frames to tools/png2snes.py (the kit's converter),
     which encodes the VRAM-grid CHR + palette + per-frame tile + anim tables.

The emitted hero.inc / ghost.inc keep the exact symbol names main.asm already
wires (hero_chr/hero_pal/hero_anim_idle[_len], ghost_chr/ghost_pal/
ghost_anim_idleWalkRun), so the swap needs no main.asm sprite-wiring change.

Regenerate (from a materialized kit root, or the parent monorepo root — same
import path; needs the registered CC0 pack zip under examples/itch_cc0/):
    PYTHONPATH=. python3 templates/shmup/assets/make_ships.py
Deterministic: same script + same pack -> same 16x16 frames -> same .inc bytes.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from PIL import Image, ImageEnhance

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent                     # kit root (or monorepo root)
ZIP_NAME = "Spaceship Pack.zip"
PNG2SNES = "tools/png2snes.py"
BOX = 16                                             # rail OBJ render size (16x16)

# art choices (see the pack montage in the reskin notes): a blue/white fighter
# reads cleanly as the hero over the navy sky + tan/green islands; a red claw
# ship, nosed DOWN, reads as the hostile descending enemy — max colour contrast.
HERO_SHIP = "ship_2.png"
HERO_FLAME = "turbo_blue.png"
ENEMY_SHIP = "ship_5.png"
ENEMY_FLAME = "turbo_blue.png"

# explosion: the kill-burst, from the pack's 7-frame 48x48 blast sheet. Frames
# 0-3 are the bright arc (spark -> peak fireball -> break-up -> embers); frames
# 4-6 go too dark to read at 16px, so the burst uses the first four. They get a
# UNIFORM 3x downscale (not the ships' content-fit) so the blast's grow-then-fade
# size arc survives, and their OWN warm OBJ palette (the hero/enemy palettes are
# blue and set). main.asm plays them on a small burst pool at each kill site.
EXPLOSION_SHEET = "Space Ships Explosion.png"
EXPL_FRAMES = 4

# intermediate 16x16 frames png2snes reads (working dir, not committed — same
# convention as the extracted-zip `art/` paths in the other .inc `; cmd:` lines).
ART = ROOT / "art" / "spaceship"


def find_zip() -> Path:
    for base in (ROOT, ROOT.parent):
        p = base / "examples" / "itch_cc0" / ZIP_NAME
        if p.exists():
            return p
    raise SystemExit("make_ships: pack zip not found under examples/itch_cc0/")


def load_pack():
    imgs = {}
    with zipfile.ZipFile(find_zip()) as zf:
        for name in (HERO_SHIP, HERO_FLAME, ENEMY_SHIP, ENEMY_FLAME,
                     EXPLOSION_SHEET):
            with zf.open(name) as fh:
                imgs[name] = Image.open(fh).convert("RGBA").copy()
    return imgs


def bleed_rgb(img: Image.Image) -> Image.Image:
    """Fill transparent pixels with the mean of opaque neighbours (iterative
    dilation) so a smooth downscale does not pull black from (0,0,0,0)."""
    img = img.convert("RGBA").copy()
    px = img.load()
    w, h = img.size
    opaque = [[px[x, y][3] >= 128 for x in range(w)] for y in range(h)]
    for _ in range(max(w, h)):
        add = {}
        for y in range(h):
            for x in range(w):
                if opaque[y][x]:
                    continue
                acc = [0, 0, 0]
                n = 0
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        xx, yy = x + dx, y + dy
                        if 0 <= xx < w and 0 <= yy < h and opaque[yy][xx]:
                            r, g, b, _ = px[xx, yy]
                            acc[0] += r; acc[1] += g; acc[2] += b; n += 1
                if n:
                    add[(x, y)] = (acc[0] // n, acc[1] // n, acc[2] // n, 0)
        if not add:
            break
        for (x, y), c in add.items():
            px[x, y] = c
            opaque[y][x] = True
    return img


def downscale(src: Image.Image, target_h: int, contrast=1.28, sharp=1.5) -> Image.Image:
    """Crop to content, edge-bleed, BOX-downscale to <=BOX wide / target_h tall,
    contrast+sharpen. Returns a small RGBA (not yet boxed)."""
    src = src.convert("RGBA")
    a = src.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
    bb = a.getbbox()
    src = src.crop(bb)
    a = a.crop(bb)
    cw, ch = src.size
    scale = min(BOX / cw, target_h / ch)
    nw, nh = max(1, round(cw * scale)), max(1, round(ch * scale))
    small = bleed_rgb(src).resize((nw, nh), Image.BOX)
    small = ImageEnhance.Contrast(small).enhance(contrast)
    small = ImageEnhance.Sharpness(small).enhance(sharp)
    small.putalpha(a.resize((nw, nh), Image.BOX).point(lambda v: 255 if v >= 110 else 0))
    return small


def plume(flame_img: Image.Image, frame: int, target_h: int, rot: bool) -> Image.Image:
    """One downscaled engine-flame frame from the pack's 2-frame turbo plume."""
    cell = flame_img.crop((frame * 48, 0, frame * 48 + 48, 48))
    p = downscale(cell, target_h, contrast=1.15, sharp=1.2)
    return p.rotate(180) if rot else p


def compose(ship_img, flame_img, *, nose_down: bool) -> list[Image.Image]:
    """8 boxed 16x16 RGBA frames: the (static) ship + the engine plume alternating
    its two turbo frames. nose_down rotates the whole actor 180 (the enemy)."""
    if nose_down:
        ship_img = ship_img.rotate(180)
    ship = downscale(ship_img, target_h=13)                 # leave ~3px for flame
    sw, sh = ship.size
    ship_ox = (BOX - sw) // 2
    # ship engines are at the actor's REAR: bottom for the nose-up hero, top for
    # the nose-down enemy. Anchor the ship there and grow the plume off that edge.
    ship_oy = 0 if not nose_down else BOX - sh
    plumes = [plume(flame_img, f, target_h=6, rot=nose_down) for f in (0, 1)]
    frames = []
    for step in range(8):
        fr = Image.new("RGBA", (BOX, BOX), (0, 0, 0, 0))
        fr.alpha_composite(ship, (ship_ox, ship_oy))
        pl = plumes[step % 2]
        pw, ph = pl.size
        px = (BOX - pw) // 2
        py = (ship_oy + sh - 2) if not nose_down else (ship_oy - ph + 2)
        py = max(0, min(py, BOX - ph))
        fr.alpha_composite(pl, (px, py))
        frames.append(fr)
    return frames


def explosion_frames(sheet: Image.Image) -> list[Image.Image]:
    """The kill-burst frames: sheet frames 0..EXPL_FRAMES-1, each UNIFORMLY
    downscaled 48->16 (a flat 3x reduction — a per-frame content-fit would scale
    every frame to fill the box and flatten the blast's grow-then-fade size arc).
    Edge-bled so the smooth fireball does not pull black from the surround."""
    frames = []
    for f in range(EXPL_FRAMES):
        cell = sheet.crop((f * 48, 0, f * 48 + 48, 48))
        small = bleed_rgb(cell).resize((BOX, BOX), Image.BOX)
        a = (cell.getchannel("A").point(lambda v: 255 if v >= 110 else 0)
             .resize((BOX, BOX), Image.BOX).point(lambda v: 255 if v >= 90 else 0))
        small.putalpha(a)
        frames.append(small)
    return frames


def shared_quantize(frames: list[Image.Image], ncolors: int) -> list[Image.Image]:
    """Reduce all frames to ONE shared <=ncolors palette, alpha preserved."""
    strip = Image.new("RGB", (sum(f.width for f in frames), BOX), (0, 0, 0))
    x = 0
    for f in frames:
        strip.paste(f.convert("RGB"), (x, 0)); x += f.width
    pal = strip.quantize(colors=ncolors, dither=Image.Dither.NONE)
    out = []
    for f in frames:
        a = f.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
        q = f.convert("RGB").quantize(palette=pal, dither=Image.Dither.NONE).convert("RGBA")
        q.putalpha(a)
        out.append(q)
    return out


def save_frames(frames, subdir: str, anim: str) -> Path:
    d = ART / subdir / f"{anim}_"
    if d.exists():
        for old in d.glob("*.png"):
            old.unlink()
    d.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(frames):
        f.save(d / f"frame_{i:02d}.png")
    return d


SOURCE_BLOCK = {
    "hero": [
        "; source-pack: Spaceship Pack (ship_2 delta fighter) — AlcWilliam",
        ";   (examples/itch_cc0/; grant: CC0 — see examples/itch_cc0/LICENSES.md).",
        ";   Native 48x48 pack art DOWNSCALED 3x to the rail's 16x16 OBJ box, with the",
        ";   engine flame composited from the pack's turbo_blue plume (its two frames",
        ";   alternate across the 8 idle steps). Pre-authored by",
        ";   templates/shmup/assets/make_ships.py; png2snes.py then encoded the frames.",
    ],
    "ghost": [
        "; source-pack: Spaceship Pack (ship_5 fighter, rotated nose-down) — AlcWilliam",
        ";   (examples/itch_cc0/; grant: CC0 — see examples/itch_cc0/LICENSES.md).",
        ";   Native 48x48 pack art DOWNSCALED 3x to the rail's 16x16 OBJ box and turned",
        ";   180 so it noses DOWN at the player, with thrusters composited from the",
        ";   pack's turbo_blue plume (its two frames alternate across the 8 steps).",
        ";   Pre-authored by templates/shmup/assets/make_ships.py; png2snes.py encoded it.",
    ],
    "expl": [
        "; source-pack: Spaceship Pack (Space Ships Explosion, frames 0-3) — AlcWilliam",
        ";   (examples/itch_cc0/; grant: CC0 — see examples/itch_cc0/LICENSES.md).",
        ";   The 7-frame 48x48 blast sheet's bright arc (spark -> peak fireball ->",
        ";   break-up -> embers) UNIFORMLY downscaled 3x to the rail's 16x16 OBJ box,",
        ";   quantized to its own warm OBJ palette (the ships' palettes are blue).",
        ";   Pre-authored by templates/shmup/assets/make_ships.py; png2snes.py encoded it.",
    ],
}


def inject_source_block(inc_path: Path, key: str) -> None:
    """Insert the hand-authored source-pack attribution block right after the
    `; cmd:` line png2snes emits (the split_v_fight/knight.inc convention)."""
    lines = inc_path.read_text().splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("; cmd:"):
            lines[i + 1:i + 1] = SOURCE_BLOCK[key]
            break
    inc_path.write_text("\n".join(lines) + "\n")


def run_png2snes(frame_dir: Path, name: str, out_rel: str) -> None:
    # invoke with paths RELATIVE to the kit root so the committed `; cmd:` header
    # is environment-independent (matches the other png2snes-from-pack entries).
    rel = frame_dir.relative_to(ROOT).as_posix()
    cmd = [sys.executable, PNG2SNES, "sprite", rel,
           "--size", str(BOX), "--name", name, "--out", out_rel]
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> int:
    pack = load_pack()
    hero = shared_quantize(
        compose(pack[HERO_SHIP], pack[HERO_FLAME], nose_down=False), 15)
    enemy = shared_quantize(
        compose(pack[ENEMY_SHIP], pack[ENEMY_FLAME], nose_down=True), 15)
    expl = shared_quantize(explosion_frames(pack[EXPLOSION_SHEET]), 15)

    hero_dir = save_frames(hero, "hero", "idle")
    enemy_dir = save_frames(enemy, "ghost", "idleWalkRun")
    expl_dir = save_frames(expl, "expl", "burst")

    run_png2snes(hero_dir, "hero", "templates/shmup/assets/hero.inc")
    run_png2snes(enemy_dir, "ghost", "templates/shmup/assets/ghost.inc")
    run_png2snes(expl_dir, "expl", "templates/shmup/assets/explosion.inc")

    inject_source_block(HERE / "hero.inc", "hero")
    inject_source_block(HERE / "ghost.inc", "ghost")
    inject_source_block(HERE / "explosion.inc", "expl")

    # The 16x16 frames are a transient conversion input (the same status as the
    # extracted-zip `art/<pack>/` paths in the other conversions' `; cmd:` lines):
    # png2snes has consumed them, so drop them — they are NOT a committed asset.
    shutil.rmtree(ART, ignore_errors=True)
    try:
        (ROOT / "art").rmdir()          # remove the now-empty parent, if it is
    except OSError:
        pass
    print("make_ships: hero.inc + ghost.inc + explosion.inc regenerated "
          "from the Spaceship Pack")
    return 0


if __name__ == "__main__":
    sys.exit(main())
