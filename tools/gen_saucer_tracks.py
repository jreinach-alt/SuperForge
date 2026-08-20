#!/usr/bin/env python3
"""gen_saucer_tracks.py — boss_saucer's five matrix-track blobs.

Emits (byte-identical on re-run, pure integer math after the trig):

    sau_ring.bin    2 + 256*4 = 1,026 B   256 headings at the REST scale 900
    sau_reveal.bin  2 +  61*4 =   246 B   the grow-in,  1260 -> 900
    sau_appr.bin    2 +  45*4 =   182 B   the LUNGE approach,  900 -> 637
    sau_retr.bin    2 +  45*4 =   182 B   the LUNGE retreat,   637 -> 900
    sau_death.bin   2 +  61*4 =   246 B   the recede,    900 -> 1260

Track format (m7_track/feature.toml is the contract): a u16 LE entry count,
then N entries of (M7A, M7B) as i16 LE. M7C = -M7B and M7D = M7A are derived
by the player at apply time (uniform-scale identity — two words stored, not
four, because uniform scale makes C and D redundant). The generator is
gen_boss_tracks.py's, extended with
the lunge pair; the arithmetic below is that file's verbatim, which is the
point of a shared mechanism.

THE ARITHMETIC, bit for bit
-------------------------------------------
A saucer that computed each frame's matrix at RUNTIME would do it through the
same `sf_boss_matrix scale, angle` shape the boss uses:

    cosa/sina = sincos(angle)            signed 1.7.8 trig words
    M7A = (cosa * scale) >> 8            smul16's s32 product, bytes 1-2 —
    M7B = (sina * scale) >> 8            an ARITHMETIC shift, i.e. floor
    M7C = -M7B                           negated AFTER the shift (:173-175)
    M7D =  M7A

Python's `>>` on signed ints is floor division, so `(trig * scale) >> 8`
reproduces the byte-extraction exactly. At scale $0100 the shift is the
identity, which `_selftest` asserts.

THE SCHEDULES, AND THE SIZE ENVELOPE THEY PITCH
-----------------------------------------------------------------------------
Scale maps screen->texel: a LARGER value samples a wider texel span, so the
saucer looks SMALLER. The disc is 22.0 tiles of radius (tile_color's `r > 22.0`
edge), so its RENDERED diameter is exactly

    disc_px = 2 * 22.0 * 8 * 256 / scale = 90112 / scale

which reproduces the emulator to the pixel (measured: scale 384 renders a
235 px disc; 90112/384 = 234.7).

THE ENVELOPE WAS RE-PITCHED (the numbers below are not the debut's). The
debut ran rest = 384 and a lunge apex of 160 — a 563 px disc on a 256 px
screen, i.e. 2.2 SCREENS wide and magnifying every texel 1.6x, which is what
made the apex read as a pixelated square rather than as a saucer. THREE rails
bound the re-pitch and all three are measured, not chosen:

  * THE MAGNIFICATION FLOOR. scale < 256 means MORE than one screen pixel per
    texel. Everything below stays well above it (the apex is 637 = 2.49 texels
    per pixel), so nothing in the envelope is ever magnified.
  * THE WRAP CEILING, and it is the tight one. M7SEL = 0 (sau_floor's wrap
    selection) and the map is 1024 px, so the plane TILES: sample far enough
    from the pivot and the NEXT copy of the saucer is what you get. A screen
    is a rotated 256x224 rectangle about the pivot, whose support in the
    direction of a neighbouring copy is
    max(128|cos| + 112|sin|, 128|sin| + 112|cos|) * scale/256, and a neighbour
    intrudes as soon as that plus the disc's own 176 px radius reaches 1024.
    At a heading of 41 degrees the factor peaks at 170, so a pose that can be
    rendered at ANY heading is capped at scale 1264 — a 71 px disc, which is
    the SMALLEST this saucer can be drawn at all. The reveal reaches a little
    past it only because its large scales are spent at small headings.
    THIS WAS MEASURED THE HARD WAY: a first re-pitch put REVEAL_SCALE at 1696
    on the angle-0 arithmetic alone (0.5 * scale), built, and rendered a bright
    slice of the NEXT saucer's rim down the screen edge on every reveal, death
    and result frame. The rotation term is not optional.
  * THE COMPOSITION. The beam has to read as leaving the saucer and reaching
    the gunship at row 184, so the disc's lower rim has to stay above it: a
    radius under 72 px, i.e. a disc under 144 px.

Together those pin the whole envelope to a 71..144 px disc — a 2.0x band, and
the entire band is spent:

    REVEAL_SCALE 1260   disc  71 px   the far pose, the death's end, and one
                                      pixel under the all-headings ceiling
    INIT_SCALE    900   disc 100 px   rest / FAR
    NEAR_SCALE    637   disc 141 px   the lunge apex: the LARGEST the saucer
                                      ever gets — 4.0x smaller than the debut's
                                      apex, and still 40% smaller than the
                                      debut's SMALLEST fight pose

so the reveal grows the saucer 1.40x, the dive grows it 1.41x again (2.0x in
area), and the result card holds it at 71 px — which is the size this rail was
asked to sit near, and is within four pixels of what the debut's card showed.
The saucer is never magnified, never clipped, and never covers the gunship.

Derived, never narrated: REVEAL_STEP = (REVEAL - INIT)/REVEAL_FRAMES =
360/60 = 6, LUNGE_STEP = (INIT - NEAR)/40 = 263/40 = 6.

  RING (HOLD only, on this rail). 256 headings at the rest scale. The saucer's
  FIGHT does NOT rotate — `stz b_angle` at the HOLD exit ("rotation OFF in the
  fight (scaling is the motion)") holds the angle at 0 for the whole fight,
  which is why every fight-side ramp below bakes ABSOLUTELY and this rail needs
  no ring-capture beat. The ring serves HOLD's +1/frame idle spin and supplies
  the reference entry the seam asserts compare against.

  REVEAL (su_reveal, armed by battle_init with b_angle=0). Per frame f=1..60:
  angle = f, scale interpolated ENDPOINT-EXACT,
  entry f = round(REVEAL + (INIT - REVEAL) * f / 60), so the ramp lands on
  INIT at f=60 with no terminal pop (a truncated fixed step would leave a
  remainder for the state exit to close in one frame — a visible size jump on
  the reveal's last frame, which is why the lerp form is used). Entry 0 is the
  PRE-reveal pose (angle 0, scale REVEAL) — the matrix battle_init shows
  before the fade lifts.

  THE LUNGE. This is the rail's headline and it is a
  pure SCALE axis: angle is 0 throughout. The ramp runs by COMPARISON, not
  by counting — `sbc #LUNGE_STEP / cmp #LUNGE_NEAR_SCALE / bcs store` — so the
  nominal 40 sets only the STEP; the realized approach is
  900 -> 900-6f (f=1..43) -> a final clamp to 637, i.e. FORTY-FOUR frames
  with a terminal step of -5. Retreat is the mirror: 637 -> 637+6f (f=1..43)
  -> a final clamp to 900, again 44 frames, terminal step +5.
  BOTH realized sequences are baked EXACTLY, and they are NOT each
  other's reverse (reversed-approach frame 1 is 642, retreat frame 1 is 643),
  which is why there are two blobs rather than one walked both ways. Those
  terminal steps are SMALLER than a normal step (5 vs 6), so they cannot pop
  — and the one unit between them is exactly the break_off mirror's residue.

  DEATH. Per frame f=1..60: scale += REVEAL_STEP, angle += 3 — and it lands on
  REVEAL_SCALE exactly (900 + 60*6 = 1260), so the saucer recedes to precisely
  the distance it arrived from and the loop closes on one size. Asserted below.
  The $0700 clamp NEVER fires (1260 < 1792). Entry 0 is
  (angle 0, scale INIT) == ring[0] == appr[0]: the fight->death seam, which is
  EXACT here rather than captured, because the fight's angle is 0 by
  construction.

SEAM ASSERTS — the four handovers cannot drift
----------------------------------------------
  reveal[60] == ring[60]   reveal -> hold (the spin continues at rest scale)
  appr[0]    == ring[0]    hold -> fight (the FAR/rest pose, angle snapped to 0)
  retr[0]    == appr[44]   near -> retreat (the apex pose is one pose)
  retr[44]   == appr[0]    retreat -> far (the cycle closes on the rest pose)
  death[0]   == ring[0]    fight -> death (angle 0, exact, no capture beat)
  death's last SCALE == REVEAL_SCALE   the recede ends where the reveal began,
                           so the loop closes on ONE size rather than on two
                           that happen to look similar
All compare the full (A, B) pair; a generator edit that breaks one stops the
build here, before an emulator ever renders the discontinuity.
"""
from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

HEADINGS = 256              # one full turn, the rail's 8-bit heading
ONE = 256                   # 1.0 in signed 1.7.8

# The envelope, in the units the matrix takes (see THE SCHEDULES above for the
# two measured rails that bound it and the disc_px each renders).
INIT_SCALE = 900            # rest: a 100 px disc
REVEAL_SCALE = 1260         # reveal start / death end: a 71 px disc, one
                            #   under the all-headings wrap ceiling of 1264
NEAR_SCALE = 637            # the lunge apex: a 141 px disc, the largest the
                            #   saucer ever gets, and still 2.49 texels per
                            #   screen pixel — minified, never magnified. The
                            #   exact value is set by the MIRROR: break_off
                            #   resumes the climb at retreat index 44 - a after
                            #   dive index a, and retr[T] - appr[44-T] is
                            #   (LUNGE_STEP - the dive's terminal clamp step).
                            #   263 leaves a terminal step of 5, so that
                            #   mismatch is ONE unit of 900 — while an exact
                            #   multiple of the step would make the two ramps
                            #   each other's reverse and moot the second blob
REVEAL_FRAMES = 60          # reveal/death ramp length
REVEAL_STEP = (REVEAL_SCALE - INIT_SCALE) // REVEAL_FRAMES  # = 14
LUNGE_STEP = (INIT_SCALE - NEAR_SCALE) // 40                # = 5
DEATH_SPIN = 3              # su_death's per-frame angle add

# The realized lunge ramp length: the walk stops on a COMPARISON, so this is
# derived here exactly as the ASM derives it, never narrated.
LUNGE_FRAMES = 1 + (INIT_SCALE - NEAR_SCALE - 1) // LUNGE_STEP      # = 44


def trig(a: int) -> tuple[int, int]:
    """(cos, sin) for heading `a`, signed 1.7.8 — gen_m7_affine_lut.py's
    exact convention, which that file proves bit-identical to the vendored
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


def blob(entries: list[tuple[int, int]]) -> bytes:
    assert 1 <= len(entries) <= 256, len(entries)
    out = bytearray(struct.pack("<H", len(entries)))
    for a, b in entries:
        out += struct.pack("<hh", a, b)
    return bytes(out)


def build_ring() -> list[tuple[int, int]]:
    return [entry(a, INIT_SCALE) for a in range(HEADINGS)]


def build_reveal() -> list[tuple[int, int]]:
    out = [entry(0, REVEAL_SCALE)]                  # the pre-reveal pose
    for f in range(1, REVEAL_FRAMES + 1):
        scale = round(REVEAL_SCALE + (INIT_SCALE - REVEAL_SCALE)
                      * f / REVEAL_FRAMES)          # endpoint-exact
        out.append(entry(f, scale))
    assert scale == INIT_SCALE                      # the lerp lands exactly
    return out


def _ramp(start: int, stop: int, step: int) -> list[int]:
    """The compare-and-clamp ramp, realized: walk `step` per frame
    from `start` toward `stop`, clamping onto `stop` on the frame the walk
    would overshoot it. Returns the whole rendered sequence INCLUDING the
    start pose at index 0."""
    out = [start]
    v = start
    for _ in range(LUNGE_FRAMES):
        v = v - step if stop < start else v + step
        if (stop < start and v < stop) or (stop > start and v > stop):
            v = stop
        out.append(v)
    assert out[-1] == stop and out[-2] != stop, out[-3:]
    return out


def build_appr() -> list[tuple[int, int]]:
    """The approach: rest -> apex, angle 0 (the fight does not rotate)."""
    return [entry(0, s) for s in _ramp(INIT_SCALE, NEAR_SCALE, LUNGE_STEP)]


def build_retr() -> list[tuple[int, int]]:
    """The retreat: apex -> rest, angle 0."""
    return [entry(0, s) for s in _ramp(NEAR_SCALE, INIT_SCALE, LUNGE_STEP)]


def build_death() -> list[tuple[int, int]]:
    out = [entry(0, INIT_SCALE)]                    # == ring[0], the seam
    for f in range(1, REVEAL_FRAMES + 1):
        out.append(entry(DEATH_SPIN * f, INIT_SCALE + REVEAL_STEP * f))
    return out


def _selftest(ring, reveal, appr, retr, death) -> None:
    # the identity case: at scale $0100 the shift is a no-op, so the
    # arithmetic here degenerates to gen_m7_affine_lut's exactly
    for a in range(HEADINGS):
        c, s = trig(a)
        assert ((c * 0x100) >> 8, (s * 0x100) >> 8) == (c, s), a
    # the realized lunge length is the ASM's, not a narrated 40. It is
    # SAU_LUNGE_FRAMES in game/boss_saucer/saucer.inc; a drift here and there
    # would put the state machine's cursor off the end of the blob it walks.
    assert LUNGE_FRAMES == 44, LUNGE_FRAMES
    assert len(appr) == len(retr) == LUNGE_FRAMES + 1
    # the four seams (every handover the state machine performs)
    assert reveal[REVEAL_FRAMES] == ring[REVEAL_FRAMES], "reveal->hold seam"
    assert appr[0] == ring[0], "hold->fight seam (the FAR rest pose)"
    assert retr[0] == appr[LUNGE_FRAMES], "near->retreat seam (the apex pose)"
    assert retr[LUNGE_FRAMES] == appr[0], "retreat->far seam (cycle closes)"
    assert death[0] == ring[0], "fight->death seam (angle 0, exact)"
    # the recede ends at the distance the reveal starts from: one size closes
    # the loop, so `loop_reveal` and `win_card` are the same pose apart from
    # the heading the death track spun to
    assert INIT_SCALE + REVEAL_STEP * REVEAL_FRAMES == REVEAL_SCALE, \
        "the recede does not land on the reveal's start scale"
    # the lunge pair is NOT a reversal of one blob — the truncation lands on
    # different frames, which is why two blobs ship
    assert appr[::-1] != retr, "the ramps became reverses; one blob would do"
    # the reveal only GROWS the saucer: check the SCHEDULE (M7A at angle f is
    # cos(f)*scale and is not monotone in itself), and the lunge likewise
    prev = REVEAL_SCALE + 1
    for f in range(REVEAL_FRAMES + 1):
        sc = round(REVEAL_SCALE + (INIT_SCALE - REVEAL_SCALE)
                   * f / REVEAL_FRAMES) if f else REVEAL_SCALE
        assert sc < prev or f == 0, f
        prev = sc
    ap = _ramp(INIT_SCALE, NEAR_SCALE, LUNGE_STEP)
    rt = _ramp(NEAR_SCALE, INIT_SCALE, LUNGE_STEP)
    assert all(b < a for a, b in zip(ap, ap[1:])), ap
    assert all(b > a for a, b in zip(rt, rt[1:])), rt


def main(argv):
    if len(argv) != 2:
        print("usage: gen_saucer_tracks.py <outdir>", file=sys.stderr)
        return 2
    outdir = Path(argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    ring, reveal = build_ring(), build_reveal()
    appr, retr, death = build_appr(), build_retr(), build_death()
    _selftest(ring, reveal, appr, retr, death)
    for name, entries, want in (("sau_ring", ring, 1026),
                                ("sau_reveal", reveal, 246),
                                ("sau_appr", appr, 182),
                                ("sau_retr", retr, 182),
                                ("sau_death", death, 246)):
        data = blob(entries)
        assert len(data) == want, (name, len(data), want)  # == the rom claim
        (outdir / f"{name}.bin").write_bytes(data)
        print(f"wrote {outdir / name}.bin ({len(data)} B, "
              f"{len(entries)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
