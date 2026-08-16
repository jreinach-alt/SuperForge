#!/usr/bin/env python3
"""gen_racer_assets.py — deterministic `racer` rail assets.

Emits, byte-identical on re-run (pure integer math, no float in any output):

  racer_kart_chr.bin  1024 B — 32 tiles x 32 B 4bpp: ONE 16-wide OBJ grid row
                      pair, because the PPU reads a 16x16 sprite at
                      N, N+1, N+16, N+17. The kart's straight frame is tiles
                      0,1,16,17 and its LEAN frame 2,3,18,19; the speed bar's
                      dim/lit 8x8 ticks are tiles 4 and 5. Everything else is
                      empty. (The lean frame is drawn leaning LEFT and the
                      right lean is the same tiles H-flipped in OAM — the
                      reference rail's trick, one frame of CHR for two.)
  racer_kart_pal.bin  32 B — 16 BGR555 words, OBJ palette 0, index 0
                      transparent by hardware contract.
  racer_sky_keys.bin  5376 B — KEYS(8) day-night keyframes x 3 COLDATA planes
                      x 224 per-scanline bytes. Keyframe 0 is full DAY and
                      keyframe 7 full NIGHT; rc_grad points its three WRAM
                      header tables at `base + k*672` and the game walks k.
                      Each byte is plane_select | intensity: R = $20|v,
                      G = $40|v, B = $80|v, v in 0..31 — the same encoding
                      tools/gen_gradient.py uses, and for the same reason
                      (COLDATA is one port with three plane-select bits).
  racer_move.inc      the 64-entry heading LUT and the rail's physics equates,
                      so the ROM assembles against ONE source of truth.

THE DIRECTION CONVENTION IS NOT THIS FILE'S TO CHOOSE. `unit()` is imported
from tools/gen_move_lut.py, which locks it against tools/gen_pose_tables.py's
matrix: screen-forward at heading h is world (-sin, -cos), h=0 north, h=16
west, h=32 south, h=48 east, and steering LEFT increments h. Re-deriving it
here would be a second source of truth for a fact the pose blobs already
encode — and pose_rom is shared with microzero, which pins its render.

COLOUR MATH IS **ADD** here, as it is for rgb_gradient (CGADSUB add on
BG1+BG2), NOT the reference rail's subtract. Consequence, and it is the reason
the day-night read is strong on a screenshot: DAY adds a bright warm haze to
the whole frame and NIGHT adds almost nothing but a faint blue, so the
rendered difference between keyframe 0 and keyframe 7 is most of the picture
rather than a tint shift.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_move_lut import POSES, UNIT, unit          # noqa: E402  the SSoT
from gen_m7_assets import bgr                       # noqa: E402

TOTAL_LINES = 224
SEAM = 44                       # lines 0..43 sky band, 44..223 Mode-7 floor.
                                # NOT a free parameter: mode7_persp's index
                                # tables skip exactly HUD_LINES lines and the
                                # pose blobs carry 224-HUD_LINES rows, so the
                                # seam is pinned by pose_rom's geometry.
KEYS = 8                        # day-night keyframes, 0 = day .. 7 = night
PLANE = (0x20, 0x40, 0x80)      # COLDATA plane-select bits (R, G, B)

# --- the two day-night endpoints, as (sky-top, horizon, ground) triples -----
# Each is a 5-bit per-plane ADD intensity. The sky ramps top -> horizon over
# the sky band; the floor decays horizon -> ground over the perspective band,
# so the haze saturates at the far rows and the near track keeps its colours.
DAY_TOP,   DAY_HOR,   DAY_GND   = (2, 7, 18), (15, 13, 7),  (0, 0, 0)
NIGHT_TOP, NIGHT_HOR, NIGHT_GND = (0, 0, 4),  (1, 1, 7),    (0, 0, 0)

FOG_FALLOFF = 3                 # exponent of the floor's decay toward ground

# THE KERB STRIPES ARE STATIC, and that is a DESIGN DECISION rather than a
# simplification. Cycling a pair of kerb CGRAM entries — "the rumble stripes at
# the road edges flash red/white like trackside lights" — reads on screen as
# the kerb flickering rather than as the kart moving past it, which is the
# opposite of the speed cue it is supposed to give. So there is no kerb palette
# artifact here at all: the red and white rumble blocks are two fixed entries
# of the world's own floor palette and the strips render from the tilemap,
# always visible, never changing.
#
# The general lesson: A COMMENT CLAIMING INTENT IS A SECONDARY SOURCE. It is
# usually right and it is not evidence — the same rule AGENTS.md already
# applies to a doc's count or a licence file, applied to a rationale. Play it
# before believing it.

# --- physics (8.8 px/frame, 8.8 px/frame^2) --------------------------------
SPEED_CAP = 0x1800              # 24.0 px/f — top speed
ACCEL = 0x0060                  # 0.375 — B held: 64 frames from rest to cap
DECEL = 0x0030                  # 0.1875 — coasting decay toward a full stop
GRASS_CAP = 0x0600              # 6.0 — the off-road crawl
OFFROAD_DRAG = 0x0180           # 1.5 — bled per frame while on grass
TOD_HOLD = 128                  # frames per DAY / NIGHT hold
TOD_STEP = 16                   # frames per keyframe step during a blend

# --- kart palette ----------------------------------------------------------
T, RED, DRED, GREY, DGREY, WHITE, YELLOW, BLACK = 0, 1, 2, 3, 4, 5, 6, 7
KART_PAL = [
    0x0000,                     # 0 transparent (hardware contract)
    bgr(31, 2, 2),              # 1 kart red
    bgr(17, 0, 0),              # 2 kart dark red (shading)
    bgr(24, 24, 26),            # 3 grey (wings)
    bgr(9, 9, 11),              # 4 dark grey
    bgr(31, 31, 31),            # 5 white (cockpit, lit tick)
    bgr(31, 31, 4),             # 6 yellow (engine glow)
    bgr(3, 3, 5),               # 7 near-black outline
] + [0x0000] * 8

# --- 4bpp tile encoding ----------------------------------------------------
def encode_4bpp(px: list[list[int]]) -> bytes:
    """One 8x8 tile of palette indices -> 32 B SNES 4bpp (planes 0/1
    interleaved per row, then planes 2/3). NO masking: an index outside
    0..15 is a bug in the art, not something to silently quantise (the
    asset-codec rule)."""
    out = bytearray()
    for lo_hi in (0, 2):
        for row in range(8):
            b0 = b1 = 0
            for col in range(8):
                v = px[row][col]
                if not 0 <= v <= 15:
                    raise ValueError(f"palette index {v} at row {row} col {col}"
                                     " is outside 4bpp range 0..15")
                b0 |= ((v >> lo_hi) & 1) << (7 - col)
                b1 |= ((v >> (lo_hi + 1)) & 1) << (7 - col)
            out += bytes((b0, b1))
    return bytes(out)


def _blank() -> list[list[int]]:
    return [[T] * 8 for _ in range(8)]


def _split16(art: list[str], key: dict) -> list[list[list[int]]]:
    """A 16-row x 16-col character map -> the four 8x8 quadrant tile grids in
    PPU order: TL, TR, BL, BR (= tiles N, N+1, N+16, N+17)."""
    quads = [[[T] * 8 for _ in range(8)] for _ in range(4)]
    for r, line in enumerate(art):
        for c, ch in enumerate(line):
            q = (r >= 8) * 2 + (c >= 8)
            quads[q][r % 8][c % 8] = key[ch]
    return quads


KEY = {".": T, "R": RED, "d": DRED, "G": GREY, "g": DGREY,
       "W": WHITE, "Y": YELLOW, "k": BLACK}

# The kart, rear three-quarter view: red body, dark-red shading, grey wings,
# white cockpit slit, yellow engine glow under the tail.
KART_STRAIGHT = [
    "................",
    ".....kkkkkk.....",
    "....kRRRRRRk....",
    "...kRRWWWWRRk...",
    "...kRRWWWWRRk...",
    "..kRRRRRRRRRRk..",
    ".kGgRRRRRRRRgGk.",
    ".kGgRRRRRRRRgGk.",
    ".kGgRddddddRgGk.",
    ".kGgRddddddRgGk.",
    "..kRRddddddRRk..",
    "..kggkYYYYkggk..",
    "..kggkYYYYkggk..",
    "...kk.YYYY.kk...",
    "......kkkk......",
    "................",
]
# The lean frame: the same kart rolled left — the body shifts one column and
# the near wing drops, which is what reads as a lean at this size.
KART_LEAN = [
    "................",
    "....kkkkkk......",
    "...kRRRRRRk.....",
    "..kRRWWWWRRk....",
    "..kRRWWWWRRk....",
    ".kRRRRRRRRRRk...",
    ".kGgRRRRRRRRgk..",
    "kGgRRRRRRRRRgGk.",
    "kGgRddddddRRgGk.",
    ".kgRddddddRRgGk.",
    ".kkRRddddddRRk..",
    "..kgkYYYYkkggk..",
    "..kgkYYYYkkggk..",
    "...k.YYYY..kk...",
    ".....kkkk.......",
    "................",
]

# The speed bar's two 8x8 ticks: a chevron, dim (dark grey) then lit (white
# core with a yellow rim, so a lit tick is unmistakable on a screenshot even
# under the day haze).
TICK_DIM = [
    "..gggg..", ".g....g.", "g......g", "g......g",
    "g......g", "g......g", ".g....g.", "..gggg..",
]
TICK_LIT = [
    "..YYYY..", ".YWWWWY.", "YWWWWWWY", "YWWWWWWY",
    "YWWWWWWY", "YWWWWWWY", ".YWWWWY.", "..YYYY..",
]


def kart_chr() -> bytes:
    """32 tiles x 32 B. Tiles 0,1,16,17 straight; 2,3,18,19 lean; 4 dim tick;
    5 lit tick; the rest empty."""
    tiles = [_blank() for _ in range(32)]
    for base, art in ((0, KART_STRAIGHT), (2, KART_LEAN)):
        tl, tr, bl, br = _split16(art, KEY)
        tiles[base], tiles[base + 1] = tl, tr
        tiles[base + 16], tiles[base + 17] = bl, br
    for slot, art in ((4, TICK_DIM), (5, TICK_LIT)):
        tiles[slot] = [[KEY[ch] for ch in row] for row in art]
    return b"".join(encode_4bpp(t) for t in tiles)


# --- the day-night gradient keyframes --------------------------------------
def _lerp(a: int, b: int, i: int, n: int) -> int:
    return a + (b - a) * i // max(1, n - 1)


def keyframe_tint(k: int, plane: int) -> list[int]:
    """THE VISUAL CONTRACT for keyframe k, plane 0/1/2: the 5-bit ADD
    intensity showing on each scanline 0..223. This is what a rendered-pixel
    test asserts against, and what the .bin below encodes — one function, so
    the oracle cannot drift from the ROM."""
    top = _lerp(DAY_TOP[plane], NIGHT_TOP[plane], k, KEYS)
    hor = _lerp(DAY_HOR[plane], NIGHT_HOR[plane], k, KEYS)
    gnd = _lerp(DAY_GND[plane], NIGHT_GND[plane], k, KEYS)
    out = []
    for y in range(SEAM):                       # sky band: top -> horizon
        out.append(_lerp(top, hor, y, SEAM))
    floor = TOTAL_LINES - SEAM
    for i in range(floor):                      # floor band: horizon -> ground
        # depth 0 at the seam (far) -> 1 at the bottom (near); the haze decays
        # as (1-depth)^FOG_FALLOFF so far rows saturate and near rows clear.
        num = (floor - 1 - i) ** FOG_FALLOFF
        den = max(1, (floor - 1) ** FOG_FALLOFF)
        out.append(gnd + (hor - gnd) * num // den)
    assert len(out) == TOTAL_LINES
    return out


def sky_keys() -> bytes:
    out = bytearray()
    for k in range(KEYS):
        for plane in range(3):
            for v in keyframe_tint(k, plane):
                if not 0 <= v <= 31:
                    raise ValueError(f"intensity {v} outside 0..31")
                out.append(PLANE[plane] | v)
    return bytes(out)


# --- the move LUT + physics equates ----------------------------------------
def move_inc() -> str:
    lines = [
        "; racer_move.inc -- GENERATED by tools/gen_racer_assets.py. Do not edit.",
        "; The 64-entry heading LUT (8.8 unit forward vector per pose) and the",
        "; rail's physics constants: ONE source of truth for the ROM.",
        "; Direction convention is gen_move_lut.unit()'s, which is locked",
        "; against gen_pose_tables' matrix -- see that file's header.",
        "",
        f"RC_SPEED_CAP    = ${SPEED_CAP:04X}    ; 8.8 top speed",
        f"RC_ACCEL        = ${ACCEL:04X}    ; 8.8 gained per frame holding B",
        f"RC_DECEL        = ${DECEL:04X}    ; 8.8 lost per frame coasting",
        f"RC_GRASS_CAP    = ${GRASS_CAP:04X}    ; 8.8 off-road crawl speed",
        f"RC_OFFROAD_DRAG = ${OFFROAD_DRAG:04X}    ; 8.8 bled per frame on grass",
        f"RC_TOD_HOLD     = {TOD_HOLD}      ; frames per DAY / NIGHT hold",
        f"RC_TOD_STEP     = {TOD_STEP}       ; frames per day-night keyframe step",
        f"RC_TOD_KEYS     = {KEYS}        ; keyframes: 0 = day .. 7 = night",
        f"RC_POSES        = {POSES}       ; pose headings (pose_rom's set)",
        "",
        "rc_move_lut:",
    ]
    for h in range(POSES):
        ux, uy = unit(h)
        lines.append(f"    .word ${ux & 0xFFFF:04X}, ${uy & 0xFFFF:04X}   ; h={h}")
    return "\n".join(lines) + "\n"


def main() -> int:
    if not 2 <= len(sys.argv) <= 3:
        print("usage: gen_racer_assets.py <bin-outdir> [<inc-outdir>]",
              file=sys.stderr)
        return 2
    out = Path(sys.argv[1])
    # The .inc goes on the ca65 -I path (the rail's map dir), the .bin on
    # --bin-include-dir. gen_move_lut.py splits them the same way.
    inc = Path(sys.argv[2]) if len(sys.argv) == 3 else out
    out.mkdir(parents=True, exist_ok=True)
    inc.mkdir(parents=True, exist_ok=True)
    (out / "racer_kart_chr.bin").write_bytes(kart_chr())
    pal = b"".join(w.to_bytes(2, "little") for w in KART_PAL)
    assert len(pal) == 32
    (out / "racer_kart_pal.bin").write_bytes(pal)
    keys = sky_keys()
    assert len(keys) == KEYS * 3 * TOTAL_LINES == 5376, len(keys)
    (out / "racer_sky_keys.bin").write_bytes(keys)
    (inc / "racer_move.inc").write_text(move_inc())
    print(f"gen_racer_assets: kart_chr 1024 B, kart_pal 32 B, "
          f"sky_keys {len(keys)} B -> {out}; racer_move.inc -> {inc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
