"""Photograph every one of the railshooter ship's bank poses, zoomed.

Usage:  python3 tools/shot_rs_ship_poses.py [outdir]

This is the sprint's judging instrument and it is deliberately NOT a test: it
crops the ship's 32x32 OAM box out of REAL FRAMES — the PPU's own composite,
through the PPU's own palette, over whatever the rail's floor happened to be
painting — and lays the poses side by side at 6x so a human can read three
things at a glance:

    * the ship is a SOLID seen from behind, not a flat fill: a lit crown, a
      shadowed underside, a rim on the up-facing edge;
    * the roll is PROGRESSIVE — level, then four bank steps, each a distinct
      silhouette rather than one banked frame;
    * the SHADING changes between them. The light does not roll with the hull,
      so the raised wing brightens and the dropped wing falls into shadow. A
      bank that were only a sheared silhouette would show the same tones in
      every column of this strip.

It captures the LEFT bank and the RIGHT bank separately, because the right one
is the left CHR H-flipped and the strip is where you check the mirror actually
reads as the other direction.

The rail flies itself, so there is nothing to drive: the S-curve walks the
pose through its whole range twice per period and this just waits, on emulated
frames, for a pose it has not photographed yet.
"""
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from PIL import Image  # noqa: E402

from mesen_runner import MesenRunner, MemoryType  # noqa: E402

ROM = SUPERFORGE / "build" / "railshooter.sfc"
SETTLE = 150                    # the fade-in is done

# game/railshooter/railshooter.inc
SHIP_SLOT = 2
SHIP_X, SHIP_Y = 112, 150
T_SHIP = (0, 4, 8, 12, 200)     # level, then the four bank steps
ATTR_HFLIP = 1 << 6
# Mesen captures 239 rows and the visible frame starts 7 rows in (MEASURED —
# tests/test_railshooter.py names the same constant beside the seam it was
# found from).
ROW0 = 7
ZOOM = 6
PAD = 3
PERIOD = 256                    # RS_PATH_PERIOD: the whole pose range, twice


def ship_pose(runner):
    """(bank step, mirrored) from the ship's OAM entry, or None while it is
    blinking through the fail state."""
    o = runner.read_bytes(MemoryType.SnesSpriteRam, SHIP_SLOT * 4, 4)
    tile, attr = o[2], o[3]
    if tile not in T_SHIP:
        return None
    return T_SHIP.index(tile), bool(attr & ATTR_HFLIP)


def crop(runner, out, name):
    """The ship's own 32x32 box out of a real frame."""
    img = Image.open(runner.take_screenshot(str(out / f"_{name}.png")))
    return img.convert("RGB").crop((SHIP_X, SHIP_Y + ROW0,
                                    SHIP_X + 32, SHIP_Y + 32 + ROW0))


def strip(tiles, path):
    n = len(tiles)
    w = n * (32 * ZOOM + PAD) + PAD
    sheet = Image.new("RGB", (w, 32 * ZOOM + 2 * PAD), (20, 20, 26))
    for i, t in enumerate(tiles):
        sheet.paste(t.resize((32 * ZOOM, 32 * ZOOM), Image.NEAREST),
                    (PAD + i * (32 * ZOOM + PAD), PAD))
    sheet.save(path)
    print(f"{path}  ({n} poses)")


def main(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    runner = MesenRunner()
    runner.boot_to_frame(str(ROM), SETTLE)
    runner.debug_break()

    # (0, True) is not a pose the rail can produce and its absence is the
    # point: `rs_draw_ship` only reaches the H-flip on a RIGHT bank, so the
    # level frame is never mirrored — a mirrored level frame would mean the
    # flip had leaked out of the bank branch.
    want = [(k, m) for m in (False, True) for k in range(len(T_SHIP))
            if not (k == 0 and m)]
    seen = {}
    # Two whole path periods is every pose twice over; the loop exits as soon
    # as the set is complete.
    for _ in range(2 * PERIOD + 8):
        pose = ship_pose(runner)
        if pose is not None and pose not in seen:
            seen[pose] = crop(runner, out, f"pose_{pose[0]}_{int(pose[1])}")
        if len(seen) == len(want):
            break
        runner.frame_step(1)
    runner.stop()

    missing = [p for p in want if p not in seen]
    if missing:
        print(f"NOT PHOTOGRAPHED: {missing}")

    left = [seen[(k, False)] for k in range(len(T_SHIP)) if (k, False) in seen]
    right = [seen[(k, True)] for k in range(1, len(T_SHIP)) if (k, True) in seen]
    strip(left, out / "rs_ship_poses_left.png")
    # hard over one way, through level, to hard over the other
    strip(list(reversed(right)) + left, out / "rs_ship_poses.png")
    for f in out.glob("_pose_*.png"):
        f.unlink()
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1
                  else "/tmp/rs_ship_poses"))
