#!/usr/bin/env python3
"""gen_m7f_gradient.py — the flight rail's COLDATA sky ramp and horizon fog.

Emits m7f_grad.bin (672 B, byte-identical on re-run, pure integer math) — the
blob that backs `rgb_gradient`'s `grad_tabs` ROM claim for this rail.

WHY THIS RAIL NEEDS ITS OWN GENERATOR RATHER THAN gen_gradient.py's OUTPUT.
`tools/gen_gradient.py` bakes microzero's table: ONE byte per scanline of the
whole frame, sky above a FIXED seam at line 44 and fog below it. That shape is
correct for a rail whose camera height never changes (its own docstring says
so — a fixed camera height over fixed geometry). This rail's horizon MOVES
between scanline 64 and 104 with altitude, so a table indexed
directly by scanline would nail the fog to one altitude's horizon and let it
tear away from the split at every other. The DATA here is therefore indexed by
DISTANCE FROM THE HORIZON, and m7f_floor's `fog_reanchor` re-points three
short HDMA header tables at it whenever the horizon moves.

THE ENCODING, and what buys the density. rgb_gradient's `grad_tabs` claim is
672 B — 224 per plane — and that is a SHARED feature's number, not ours to
grow. The obvious encoding spends 672 B on ONE snapshot
(SKY_SNAP_STRIDE = 672, 8 snapshots = 5,376 B) because it writes a literal byte
for every scanline of the frame. Two facts collapse that:

  * a HDMA non-repeat entry HOLDS its value for the lines it covers, so the
    flat zenith region costs ONE byte however many scanlines it spans;
  * a terminator leaves the last value standing, so the clear floor below the
    fog costs NOTHING — the fade's last byte is intensity 0 and the table ends.

What is left per snapshot is the part that actually varies per line: RAMP_LEN
bytes of sky ramp and FOG_LEN of fog fade. At 55 B per plane per snapshot the
whole day/night cycle — SNAPSHOTS of them — fits the claim with bytes to
spare, and rgb_gradient composes with nothing vestigial.

THE VALUES ARE DELTAS, NOT COLOURS, and that follows from the mechanism:
colour math ADDS the COLDATA fixed colour to the layer under it, so the sky a
player sees is CGRAM[0] + ramp and the floor is its own palette + fog. CGRAM[0]
is the ZENITH (gen_m7f_assets.py's `SKY`), so ramp[0] is 0 by construction and
the ramp is the climb from the zenith to the horizon haze. That is what makes
the day/night clock a CGRAM word update plus a snapshot index rather than a
recolour of everything.

AUTHORED, NOT CONVERTED: every number below is written here, so this asset
incurs no import-provenance obligation. The SHAPE it follows — snapshots,
sky/horizon pairs, a CGRAM sky+cloud word per snapshot — is a well-worn one;
the bytes are this file's.
"""
import sys
from pathlib import Path

# --- the claim this blob backs (rgb_gradient/feature.toml) ------------------
PLANE_BYTES = 224                   # grad_tabs is 672 = 3 planes x this
PLANE = (0x20, 0x40, 0x80)          # COLDATA plane-select bits (R, G, B)

# --- the shape, in lines ----------------------------------------------------
# RAMP_LEN is the sky's ACTIVE band: the lines immediately above the horizon
# over which the zenith climbs to the haze. Above it the held zenith byte
# covers whatever is left, which is 24 lines at the deck horizon (64) and 64 at
# the ceiling (104) — so climbing reveals MORE deep sky, which is what a climb
# does.
#
# FOG_LEN is the haze below the horizon. A conventional fade of this kind is
# EIGHT lines wide — a 32-byte fade table spends entries 0-15 above the horizon
# and 24-31 clear, leaving entries 16-23 for the fade proper — so 15 is nearly
# twice that depth and still cheap.
RAMP_LEN = 40
FOG_LEN = 15
SNAP_STRIDE = RAMP_LEN + FOG_LEN                    # 55 B per plane
ZERO_OFS = 0                                        # the shared plane|0 byte
SNAP_BASE = 1                                       # ...snapshots start after it

# --- the day/night snapshots ------------------------------------------------
# FOUR, and the number is the claim's arithmetic rather than a taste: 1 +
# SNAPSHOTS * SNAP_STRIDE must fit 224, which caps it at four. Eight would fit
# only at 672 B each; at 55 B the whole cycle costs 220.
#
# Each is (name, zenith, haze) in 5-bit BGR555 channel intensities. `zenith` is
# CGRAM[0] for that time of day — the colour the held byte shows — and `haze`
# is what the ramp reaches at the horizon. The ramp is haze-minus-zenith, so
# EVERY channel of haze must be >= the same channel of zenith: colour math adds
# and cannot subtract here.
# THE HAZE DELTAS ARE TUNED TO BE NEIGHBOURS, and that is a consequence of how
# the clock moves rather than a palette preference. The ZENITH is interpolated
# every eight frames (the m7f_tod table below), but the ramp is a ROM blob and
# swaps in ONE frame — so what a player could see popping is the step in
# `haze - zenith` at a segment boundary, on the bright thin band at the
# horizon. Held to <= 4/31 per channel all the way round the cycle:
#   dawn (22,14,2) -> day (20,14,5) -> dusk (23,12,3) -> night (19,10,6) -> dawn
SNAPSHOTS = [
    ("dawn",  (6, 6, 16), (28, 20, 18)),
    ("day",   (4, 12, 24), (24, 26, 29)),
    ("dusk",  (8, 4, 9), (31, 16, 12)),
    ("night", (1, 2, 8), (20, 12, 14)),
]
DAY_INDEX = 1                       # the snapshot the rail boots on

# --- the AMBIENT, and why the floor palette is in this table too ------------
# Colour math on this rail can only ADD (CGADSUB has one global subtract bit
# and the sky and the floor share it), so the COLDATA ramp can light the sky
# but can never DARKEN the ground. Left there, the first render of the cycle
# showed a convincing night sky over a noon-bright landscape — the sky was the
# only thing that knew what time it was.
#
# So the clock also rewrites the fifteen FLOOR words. Per channel, out = base *
# level / 32, with `level` interpolated between snapshots exactly as the zenith
# is. That is a plain CGRAM word update on the same schedule, and it is what
# an earlier day/night store does for its two words (sky + cloud) generalised
# to the palette this rail actually has.
AMBIENT = {
    "dawn":  (30, 26, 26),          # a touch dim, slightly warm
    "day":   (32, 32, 32),          # full
    "dusk":  (32, 24, 20),          # warm and dimming
    "night": (10, 11, 18),          # dark, and blue rather than grey
}

# --- the clock -------------------------------------------------------------
# A 16-bit phase incremented once per armed VBlank. A full cycle is 2,048
# frames — 34.1 s of NTSC, and the rate is the SLOW-CLOCK half of the plan's
# "slow-clock swap/interpolation". Picked against what it does rather than for
# a round number: at the first rate tried (1,024 frames) the zenith visibly
# shifted every few seconds and the sky read as a time-lapse rather than as
# weather; at 2,048 a pilot flies through one time of day and arrives in the
# next. It also makes the picture HOLD STILL for sixteen frames at a stretch,
# which is what lets the skip's byte-identity cases stay whole-frame.
# (A snapshot-swapped day/night needs no clock at all — the generator emits the
# blobs and the ROM picks one. The clock, and therefore this rate, is this
# rail's own choice, and is recorded here rather than left implicit.)
# SIXTY-FOUR steps, not 128, and the number is set by the LONGEST period the
# picture already has rather than by how smooth the interpolation could be:
# the airship's propeller is a two-state flip every 8 frames
# (m7f_obj.asm:27), so the frame repeats on a 16-frame cycle, and a
# time-of-day step SHORTER than that leaves no window in which two frames are
# byte-identical for any reason. The skip's whole user-visible claim is
# byte-identity, so the clock is built to leave it a window: a step is 32
# frames, two propeller periods. (Found by measurement — at 16-frame steps
# three identity cases failed on the propeller, not on the sky.)
TOD_STEPS = 64                      # zenith updates per full cycle
TOD_SEG_STEPS = TOD_STEPS // len(SNAPSHOTS)         # ...16 per segment
TOD_RATE = 32                       # phase units per armed VBlank
TOD_STEP_SHIFT = 10                 # step = phase >> 10
TOD_SEG_FRAMES = (1 << 16) // len(SNAPSHOTS) // TOD_RATE        # 256
TOD_CYCLE_FRAMES = TOD_SEG_FRAMES * len(SNAPSHOTS)              # 1,024
TOD_STEP_FRAMES = (1 << TOD_STEP_SHIFT) // TOD_RATE             # 8

# THE ADD-ONLY CONSTRAINT, CHECKED HERE rather than discovered as a wrapped
# byte 200 lines later. CGADSUB adds; there is no per-line subtract on this
# path, so a snapshot whose haze is DARKER than its zenith in any channel
# cannot be expressed and is a design error, not a clamp. The first dusk
# written for this rail had zenith B=14 against haze B=10 and this is what
# named it.
for _n, _z, _h in SNAPSHOTS:
    for _i, _c in enumerate("RGB"):
        assert _h[_i] >= _z[_i], (
            f"snapshot {_n}: haze {_c}={_h[_i]} is darker than zenith "
            f"{_c}={_z[_i]} — colour math ADDS, so the horizon cannot be "
            f"dimmer than the zenith in any channel")

# The fog's peak is the horizon haze itself, so the sky's last ramp byte and
# the fog's first are the SAME value and the two bands meet with no step in the
# addend. gen_gradient.py takes the same position (FOG_PEAK = SKY_HORIZON) for
# the same reason.
FOG_FALLOFF = 2                     # exponent of the fog's decay to clear


def _lerp(a: int, b: int, i: int, n: int) -> int:
    """Integer linear interpolation a -> b over n steps, at step i."""
    return a + (b - a) * i // max(1, n - 1)


def ramp_deltas(snap: int, plane_idx: int) -> list[int]:
    """The sky ramp for one plane: RAMP_LEN intensities, zenith-relative.

    Entry i is the value shown RAMP_LEN-i lines above the horizon, so entry
    RAMP_LEN-1 is the horizon line itself. This is the VISUAL contract a
    rendered-pixel test asserts against.
    """
    _, zen, haze = SNAPSHOTS[snap]
    top = 0                                     # at the ramp's start: zenith
    end = haze[plane_idx] - zen[plane_idx]      # ...and the haze at the horizon
    return [_lerp(top, end, i, RAMP_LEN) for i in range(RAMP_LEN)]


def fog_deltas(snap: int, plane_idx: int) -> list[int]:
    """The horizon fog for one plane: FOG_LEN intensities, floor-relative.

    Entry j is the value on the floor line j below the horizon. Entry 0 is the
    haze the sky ramp ended on (no step at the seam) and the LAST entry is 0 —
    which is what lets the table terminate here and leave the floor below it
    untinted for free.
    """
    _, zen, haze = SNAPSHOTS[snap]
    peak = haze[plane_idx] - zen[plane_idx]
    out = []
    for j in range(FOG_LEN):
        # (1 - j/(n-1))^FOG_FALLOFF, in integers: the haze thins fastest just
        # under the horizon, which is where the plane's compression is highest.
        num = (FOG_LEN - 1 - j) ** FOG_FALLOFF
        den = (FOG_LEN - 1) ** FOG_FALLOFF
        out.append(peak * num // den)
    return out


def plane_bytes(plane_idx: int) -> list[int]:
    """One plane's 224 B region of the blob."""
    sel = PLANE[plane_idx]
    out = [sel | 0]                             # ZERO_OFS: the zenith/clear byte
    for snap in range(len(SNAPSHOTS)):
        for v in ramp_deltas(snap, plane_idx) + fog_deltas(snap, plane_idx):
            assert 0 <= v <= 31, (
                f"snapshot {SNAPSHOTS[snap][0]} plane {plane_idx} intensity "
                f"{v} does not fit COLDATA's 5-bit field — OR-ing it with the "
                f"plane select would set a foreign plane bit and write another "
                f"channel's plane")
            out.append(sel | v)
    assert len(out) == SNAP_BASE + len(SNAPSHOTS) * SNAP_STRIDE
    return out + [sel | 0] * (PLANE_BYTES - len(out))


def blob() -> bytes:
    return bytes(b for p in range(3) for b in plane_bytes(p))


# =============================================================================
# The day/night clock's table — one ROM row per step, and NO MULTIPLY
# =============================================================================
# Row i is [zenith BGR555 word][snapshot byte offset], four bytes, indexed by
# `phase >> 9`. Both halves are baked for the same reason: the hardware
# multiplier is `m7f_cam`'s WHOLE claim (one owner per scene), so m7f_floor
# cannot interpolate at runtime even if it wanted to — and it should not want
# to, because the interpolation is a pure function of these constants and the
# generator is where such functions live on this rail.
#
# THE OFFSET COLUMN LAGS THE ZENITH BY HALF A SEGMENT, deliberately: the ramp
# swaps when the interpolated zenith is already halfway to the next snapshot,
# which halves the step a player could see at the swap. Baking it as a column
# rather than deriving it in ASM is what makes that a decision with a reason
# rather than an off-by-sixteen.
def tod_zenith(step: int) -> tuple[int, int, int]:
    seg = step // TOD_SEG_STEPS
    i = step % TOD_SEG_STEPS
    a = SNAPSHOTS[seg][1]
    b = SNAPSHOTS[(seg + 1) % len(SNAPSHOTS)][1]
    return tuple(a[c] + (b[c] - a[c]) * i // TOD_SEG_STEPS for c in range(3))


def tod_snapshot(step: int) -> int:
    """Which snapshot's ramp is in force at this step — the NEAREST one."""
    return ((step + TOD_SEG_STEPS // 2) // TOD_SEG_STEPS) % len(SNAPSHOTS)


def tod_table() -> bytes:
    """m7f_tod: one word per step — the snapshot's byte offset into a plane."""
    out = bytearray()
    for step in range(TOD_STEPS):
        ofs = tod_snapshot(step) * SNAP_STRIDE
        out += bytes((ofs & 0xFF, ofs >> 8))
    return bytes(out)


def tod_ambient(step: int) -> tuple[int, int, int]:
    seg = step // TOD_SEG_STEPS
    i = step % TOD_SEG_STEPS
    a = AMBIENT[SNAPSHOTS[seg][0]]
    b = AMBIENT[SNAPSHOTS[(seg + 1) % len(SNAPSHOTS)][0]]
    return tuple(a[c] + (b[c] - a[c]) * i // TOD_SEG_STEPS for c in range(3))


# The clouds' four OBJ colours, before the ambient. Word 0 is never rendered
# (colour 0 of an OBJ palette is transparent by hardware) and is carried so the
# run is contiguous — CGADD auto-increments, and a hole would cost a second
# port setup for nothing.
# SIXTEEN words, of which four carry cloud art and twelve are black padding —
# and the padding is LOAD-BEARING. The ROM finds its row with a shift and a
# mask (`tod_commit`), which is only a division by the row stride when that
# stride is a POWER OF TWO. A 20-word row is 40 bytes, and the first build with
# one silently served a NEIGHBOURING row's colours: the picture was a plausible
# sunset that belonged to no snapshot. Padding to 32 words puts the row back on
# 64 bytes and the mask back on a bit boundary; the alternative is a multiply,
# and the multiplier belongs to m7f_cam.
CLOUD_PAL = ([(0, 0, 0), (31, 31, 31), (26, 27, 31), (20, 21, 27)]
             + [(0, 0, 0)] * 12)
CLOUD_WORDS = len(CLOUD_PAL)
PAL_WORDS = 16 + CLOUD_WORDS
assert PAL_WORDS & (PAL_WORDS - 1) == 0, (
    f"the day/night palette row is {PAL_WORDS} words — tod_commit finds its "
    f"row with a mask, which is only a division when the stride is a power "
    f"of two")


def tod_palette(step: int, base: list[tuple[int, int, int]]) -> list[int]:
    """The CGRAM words in force at this step: the floor's sixteen, then the
    clouds' four.

    Word 0 is the ZENITH — the sky the split reveals, which is not dimmed by
    the ambient because it IS the ambient. Everything after it is scaled by the
    ambient, clouds included: a white cloud over a night landscape is the same
    defect the floor had, one layer up.
    """
    amb = tod_ambient(step)
    words = [tod_zenith(step)]
    for c in list(base[1:]) + CLOUD_PAL:
        words.append(tuple(c[k] * amb[k] // 32 for k in range(3)))
    return [(b << 10) | (g << 5) | r for r, g, b in words]


def tod_palette_table(base: list[tuple[int, int, int]]) -> bytes:
    out = bytearray()
    for step in range(TOD_STEPS):
        for w in tod_palette(step, base):
            out += bytes((w & 0xFF, w >> 8))
    return bytes(out)


def floor_palette_5bit() -> list[tuple[int, int, int]]:
    """gen_m7f_assets.py's sixteen floor colours, in 5-bit channels.

    IMPORTED rather than copied: that generator owns the palette, this one owns
    what the clock does to it, and a second hand-written copy here would be a
    second place for the floor's colours to be wrong.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "gen_m7f_assets", Path(__file__).with_name("gen_m7f_assets.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return [tuple(v >> 3 for v in c) for c in mod.PALETTE]


def main() -> int:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "build/assets")
    out_dir.mkdir(parents=True, exist_ok=True)
    data = blob()
    assert len(data) == 3 * PLANE_BYTES, len(data)
    assert SNAP_BASE + len(SNAPSHOTS) * SNAP_STRIDE <= PLANE_BYTES, (
        "the day/night cycle no longer fits rgb_gradient's grad_tabs claim")
    (out_dir / "m7f_grad.bin").write_bytes(data)
    tod = tod_table()
    assert len(tod) == 2 * TOD_STEPS, len(tod)
    (out_dir / "m7f_tod.bin").write_bytes(tod)
    base = floor_palette_5bit()
    assert base[0] == SNAPSHOTS[DAY_INDEX][1], (
        f"gen_m7f_assets' CGRAM[0] is {base[0]} but the boot snapshot "
        f"('{SNAPSHOTS[DAY_INDEX][0]}') is built as a delta from "
        f"{SNAPSHOTS[DAY_INDEX][1]} — the two generators have drifted")
    pal = tod_palette_table(base)
    assert len(pal) == TOD_STEPS * 2 * PAL_WORDS, len(pal)
    (out_dir / "m7f_todpal.bin").write_bytes(pal)
    print(f"m7f_grad: {len(data)} B  "
          f"{len(SNAPSHOTS)} snapshots x {SNAP_STRIDE} B/plane "
          f"(ramp {RAMP_LEN}, fog {FOG_LEN})")
    print(f"m7f_todpal: {len(pal)} B  {TOD_STEPS} x {PAL_WORDS} CGRAM words")
    print(f"m7f_tod:  {len(tod)} B  {TOD_STEPS} steps "
          f"({TOD_SEG_STEPS}/segment, a step every {TOD_STEP_FRAMES} frames, "
          f"{TOD_CYCLE_FRAMES} frames = {TOD_CYCLE_FRAMES / 60:.2f} s per cycle)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
