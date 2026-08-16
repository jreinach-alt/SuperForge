#!/usr/bin/env python3
"""gen_meteor_tracks.py — the meteor_event rail's matrix-track blob.

Emits (byte-identical on re-run, pure integer math after the trig):

    met_grow.bin    2 + 109*4 = 438 B   the Mode-7 phase, frame by frame

Track format (m7_track/feature.toml is the contract): a u16 LE entry count,
then N entries of (M7A, M7B) as i16 LE. M7C = -M7B and M7D = M7A are derived
by the player at apply time (uniform-scale identity — two words stored, not
four, because uniform scale makes C and D redundant).

THE ARITHMETIC IS THE REFERENCE'S, bit for bit
-------------------------------------------
A meteor_event that computed each frame's matrix at RUNTIME would do it with
the same macro the boss rail uses (`sf_boss_matrix g_scale, g_angle`):

    cosa/sina = sincos(angle)            signed 1.7.8 trig words; the
                                         convention gen_m7_affine_lut.py
                                         proves bit-identical to the vendored
                                         table at every heading
    M7A = (cosa * scale) >> 8            smul16's s32 product, bytes 1-2 —
    M7B = (sina * scale) >> 8            an ARITHMETIC shift, i.e. floor
    M7C = -M7B                           negated AFTER the shift
    M7D =  M7A

Python's `>>` on signed ints is floor division, so `(trig * scale) >> 8`
reproduces the byte extraction exactly, and the player's runtime negate
matches the post-shift `eor #$FFFF / inc a`. gen_boss_tracks.py
carries the same statement for the same reason; `_selftest` re-proves the
scale-$0100 identity here rather than citing it.

THE SCHEDULE
-----------------------------------------------------------------------------
Scale maps screen->texel: a LARGER value samples a wider texel span, so the
meteor looks SMALLER (:166-172). Constants:

    MET_SCALE_CROSS = $0E00   (:171) ~32 px on-screen meteor at the crossover
    MET_SCALE_FULL  = $0220   (:172) full size, nearly fills the screen height
    MET_SCALE_STEP  = $0030   (:178) 48/frame — "a brisk ramp so the meteor
                                     visibly grows in the pre-glow window"
    TUMBLE_STEP     = 4       (:195) angle units/frame, 256 = one full turn
    SPRITE_END      = 72      (:134) the crossover frame
    SCN_END         = 180     (:135) end of the Mode-7 phase
    M7_LEN          = 108     (:136) = SCN_END - SPRITE_END

THE REFERENCE PRE-DECREMENTS, AND THIS BAKE RE-ANCHORS BY ONE STEP
---------------------------------------------------------------
Read the ORDER of the Mode-7 tick, not just the arithmetic. `ds_mode7_phase`
calls `scene_scale` (:550), `scene_slide` (:551) and `scene_glow` (:552), then
adds TUMBLE_STEP to `g_angle` (:559-564), and only THEN commits the matrix with
`sf_boss_matrix g_scale, g_angle` (:565). Both ramps therefore step BEFORE the
commit: `scene_scale` loads g_scale, subtracts MET_SCALE_STEP,
clamps at MET_SCALE_FULL and stores — so the pose a RUNTIME solve renders on
its Mode-7 tick m is

    reference:  scale = max(CROSS - STEP * (m + 1), FULL)
             angle = (TUMBLE_STEP * (m + 1)) & 255

Measured on the emulator at scene read-timer 73 (the first Mode-7 tick's park):
that form shows g_scale = $0DD0 and angle 4 — one step in, not zero.

This track bakes the m+0 form instead:

    entry m: scale(m) = max(CROSS - STEP * m, FULL)
             angle(m) = (TUMBLE_STEP * m) & 255

so the consumer's cursor `m = g_timer - SPRITE_END` walks entries 0..107 where
the runtime form realizes steps 1..108. That is a DELIBERATE one-step re-anchoring,
not a transcription slip, and the reason is the seam below: it is what makes
entry 0 the crossover pose exactly, which is what lets ONE blob serve both
phases and what `_selftest` pins. The cost is bounded and stated — the scale
clamp fires at step 64 of 107, so both sequences spend their last 44 frames at
MET_SCALE_FULL and END on the same pose; the only difference at any given tick
is 4 angle units of tumble, one frame's worth, against a ramp whose whole
period is 64 frames. 109 entries are baked (0..108) so the last INDEXED entry
is 107 and `m7t_apply`'s clamp arm is never the thing that renders.

ENTRY 0 IS THE CROSSOVER POSE, AND IT IS ALSO THE SPRITE PHASE'S POSE. The
reference holds `MET_SCALE_CROSS` with angle 0 for the whole sprite phase (:534-
537) and `enter_scene` arms the same pair (:922-925). Baking the m+1 form would
put (CROSS - STEP, angle 4) at entry 0 and the hand-off would jump a step on the
frame it is supposed to be seamless. One entry, one blob, two phases — which is
why this rail ships ONE track where the boss ships three.

WHY NO RING, AND WHY THE ANGLE IS BAKED ABSOLUTELY
---------------------------------------------------
m7_track's inheritance contract (feature.toml, third bullet) says a
ramp entered from a FREE heading needs the ring-capture idiom. This rail's
does not: `enter_scene` does `stz g_angle` and the Mode-7 phase is the
only code on the rail that ever advances it, so every entry into this ramp is
from the KNOWN heading 0. Same deterministic-entry shape as the boss's own
reveal and as every one of boss_saucer's ramps. The idiom is available and
unused, and this note is the record of it having been asked.

ASSERTS — the two seams that cannot drift
------------------------------------------
  entry 0 == (angle 0, scale $0E00)   the crossover pose the sprite phase
                                      holds, so the hand-off shows the same
                                      matrix the frame before it did — and the
                                      assert is what pins the one-step
                                      re-anchoring above, since the m+1 form
                                      would fail it
  entry m_clamp is the FIRST entry at MET_SCALE_FULL and every later entry
                                      equals it — the ramp really does stop
                                      growing, which is what the "grew, then
                                      held" half of the grow test reads
A generator edit that breaks either stops the build here, before an emulator
ever renders the discontinuity.
"""
from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

HEADINGS = 256              # one full turn, the rail's 8-bit heading
ONE = 256                   # 1.0 in signed 1.7.8

MET_SCALE_CROSS = 0x0E00    # crossover: ~32 px on screen
MET_SCALE_FULL = 0x0220     # full size
MET_SCALE_STEP = 0x0030     # 48/frame
TUMBLE_STEP = 4             # angle units/frame
SPRITE_END = 72             # the crossover frame
SCN_END = 180               # end of the Mode-7 phase
M7_LEN = SCN_END - SPRITE_END                                # 108 (:136)


def trig(a: int) -> tuple[int, int]:
    """(cos, sin) for heading `a`, signed 1.7.8 — gen_m7_affine_lut.py's exact
    convention, which that file proves bit-identical to the vendored
    sincos table at every heading."""
    t = a * math.pi / (HEADINGS // 2)
    return round(math.cos(t) * ONE), round(math.sin(t) * ONE)


def entry(angle: int, scale: int) -> tuple[int, int]:
    """(M7A, M7B) for (angle, scale) — smul16's floor-shift, baked."""
    c, s = trig(angle & 0xFF)
    a = (c * scale) >> 8
    b = (s * scale) >> 8
    for v in (a, b):
        assert -32768 <= v <= 32767, (angle, scale, v)
    return a, b


def scale_at(m: int) -> int:
    return max(MET_SCALE_CROSS - MET_SCALE_STEP * m, MET_SCALE_FULL)


def blob(entries: list[tuple[int, int]]) -> bytes:
    assert 1 <= len(entries) <= 256, len(entries)
    out = bytearray(struct.pack("<H", len(entries)))
    for a, b in entries:
        out += struct.pack("<hh", a, b)
    return bytes(out)


def build_grow() -> list[tuple[int, int]]:
    return [entry(TUMBLE_STEP * m, scale_at(m)) for m in range(M7_LEN + 1)]


def _selftest(grow) -> None:
    # the identity case: at scale $0100 the shift is a no-op, so the
    # arithmetic here degenerates to gen_m7_affine_lut's exactly
    for a in range(HEADINGS):
        c, s = trig(a)
        assert ((c * 0x100) >> 8, (s * 0x100) >> 8) == (c, s), a
    # the crossover seam: entry 0 IS the pose the sprite phase holds
    assert grow[0] == entry(0, MET_SCALE_CROSS), "crossover seam"
    # the ramp is monotone in scale and then FLAT — check the schedule rather
    # than the words (M7A at angle 4m is cos(4m)*scale, not monotone itself)
    clamp_m = None
    for m in range(1, M7_LEN + 1):
        assert scale_at(m) <= scale_at(m - 1), m
        if scale_at(m) == MET_SCALE_FULL and clamp_m is None:
            clamp_m = m
    assert clamp_m is not None, "the ramp never reaches full size in 108 frames"
    for m in range(clamp_m, M7_LEN + 1):
        assert scale_at(m) == MET_SCALE_FULL, m
    print(f"  ramp reaches full size at Mode-7 frame {clamp_m} "
          f"of {M7_LEN}; {M7_LEN + 1 - clamp_m} frames held at $0220")


def main(argv):
    if len(argv) != 2:
        print("usage: gen_meteor_tracks.py <outdir>", file=sys.stderr)
        return 2
    outdir = Path(argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    grow = build_grow()
    _selftest(grow)
    data = blob(grow)
    assert len(data) == 438, (len(data), 438)   # == the met_grow rom claim
    (outdir / "met_grow.bin").write_bytes(data)
    print(f"wrote {outdir / 'met_grow.bin'} ({len(data)} B, "
          f"{len(grow)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
