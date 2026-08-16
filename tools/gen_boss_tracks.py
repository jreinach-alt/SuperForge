#!/usr/bin/env python3
"""gen_boss_tracks.py — the boss rail's three matrix-track blobs.

Emits (byte-identical on re-run, pure integer math after the trig):

    bs_ring.bin     2 + 256*4 = 1,026 B   256 headings at the REST scale 1.5
    bs_reveal.bin   2 +  61*4 =   246 B   the grow-in, 5.0 -> 1.5
    bs_death.bin    2 +  61*4 =   246 B   the recede,  1.5 -> ~4.78

Track format (m7_track/feature.toml is the contract): a u16 LE entry count,
then N entries of (M7A, M7B) as i16 LE. M7C = -M7B and M7D = M7A are derived
by the player at apply time (uniform-scale identity — two words stored, not
four, because uniform scale makes C and D redundant).

THE ARITHMETIC IS THE REFERENCE'S, bit for bit
-------------------------------------------
A boss that computed each frame's matrix at RUNTIME would do it through
`sf_boss_matrix scale, angle`:

    cosa/sina = sincos(angle)            signed 1.7.8 trig words, and
                                         gen_m7_affine_lut.py verified the
                                         shipped table == round(sin(a*pi/128)
                                         * 256) at every heading
    M7A = (cosa * scale) >> 8            smul16's s32 product, bytes 1-2 —
    M7B = (sina * scale) >> 8            an ARITHMETIC shift, i.e. floor
    M7C = -M7B                           negated AFTER the shift (:173-175)
    M7D =  M7A

Python's `>>` on signed ints is floor division, so `(trig * scale) >> 8`
reproduces the byte-extraction exactly, and the player's runtime negate
matches the post-shift `eor #$FFFF / inc a`. At scale $0100 the
shift is the identity ((c * 256) >> 8 == c), which `_selftest` asserts — the
same property gen_m7_affine_lut.py's header proves for the heading LUT.

THE SCHEDULES
-----------------------------------------------------------------------
Scale maps screen->texel: a LARGER value samples a wider texel span, so the
boss looks SMALLER. Constants (:76-83): INIT_SCALE = $0180
(1.5, whole boss at rest), REVEAL_SCALE = $0500 (tiny/far), DEATH_SCALE =
$0700 (declared; see below — never reached). Pacing (:124-127):
REVEAL_FRAMES = 60, and REVEAL_STEP = (REVEAL_SCALE - INIT_SCALE) /
REVEAL_FRAMES, which under ca65 integer division is $380/60 = 14 — the
source's own "~$0015/frame" comment at :130 is a hex slip for the truncated
value it actually assembles.

  RING (fight/hold/dying: free rotation at the rest scale). The fight holds
  scale at INIT_SCALE and steps the angle by boss_phase's 1/2/3 per frame
  (:895-927); HOLD steps +1 (:435-451). One entry per heading, scale $0180.
  m7_affine's own LUT is scale-1.0 only and cannot serve these states.

  REVEAL (su_reveal, :402-432; armed by battle_init :338-340 with b_angle=0).
  Reference, per frame f=1..60: scale -= 14, angle = f. That truncated step
  leaves scale at $01B8 when the timer expires, and the terminal
  a bare `lda #INIT_SCALE` snap closes the last $38 in ONE frame — a
  5x-normal jump, an ~18% size pop on the reveal's final frame.
  The bake interpolates ENDPOINT-EXACT instead — entry f =
  round(REVEAL_SCALE + (INIT_SCALE - REVEAL_SCALE) * f / 60) — so the ramp
  lands on $0180 at f=60 with no pop. That pop is a truncation
  artifact of walking the ramp by subtraction, not choreography; a baked track
  has no reason to reproduce it. Entry 0 is the PRE-reveal pose (angle 0, scale
  $0500) — the matrix battle_init shows before the fade lifts.

  DEATH (su_death, :459-489). Reference, per frame f=1..60: scale += 14
  (REVEAL_STEP again), angle += 3. The $0700 clamp (:465-467) NEVER fires:
  $0180 + 60*14 = $04C8 < $0700. The bake reproduces the REALIZED sequence
  — scale = $0180 + 14*f, angle = 3*f — because the pixels are the contract
  and DEATH_SCALE is dead tuning nothing ever renders. Entry 0 is
  (angle 0, scale $0180) == ring[0]: the DYING->DEATH seam, where the
  ring-capture hands over at heading 0, asserted below.

SEAM ASSERTS — the handovers cannot drift
-----------------------------------------
  reveal[60] == ring[60]   the reveal's last pose IS the ring pose the HOLD
                           state continues from (angle 60, scale $0180)
  death[0]   == ring[0]    the pose the dying spin captures before the
                           recede begins
Both compare the full (A, B) pair. A generator edit that breaks either stops
the build here, before an emulator ever renders the discontinuity.
"""
from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

HEADINGS = 256              # one full turn, the rail's 8-bit heading
ONE = 256                   # 1.0 in signed 1.7.8

INIT_SCALE = 0x0180         # rest: whole boss visible
REVEAL_SCALE = 0x0500       # reveal start: tiny/far
REVEAL_FRAMES = 60          # ramp length
DEATH_STEP = (REVEAL_SCALE - INIT_SCALE) // REVEAL_FRAMES   # = 14 (:130)
DEATH_SPIN = 3              # su_death's per-frame angle add


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


def build_death() -> list[tuple[int, int]]:
    out = [entry(0, INIT_SCALE)]                    # == ring[0], the seam
    for f in range(1, REVEAL_FRAMES + 1):
        out.append(entry(DEATH_SPIN * f, INIT_SCALE + DEATH_STEP * f))
    return out


def _selftest(ring, reveal, death) -> None:
    # the identity case: at scale $0100 the shift is a no-op, so the
    # arithmetic here degenerates to gen_m7_affine_lut's exactly
    for a in range(HEADINGS):
        c, s = trig(a)
        assert ((c * 0x100) >> 8, (s * 0x100) >> 8) == (c, s), a
    # the seams (the handovers the state machine performs)
    assert reveal[REVEAL_FRAMES] == ring[REVEAL_FRAMES], "reveal->hold seam"
    assert death[0] == ring[0], "dying->death seam"
    # the reveal is monotone in scale (the boss only GROWS during the ramp):
    # M7A at angle f is cos(f)*scale — not monotone in itself — so check the
    # schedule, not the words: re-derive each frame's scale from the lerp
    prev = REVEAL_SCALE + 1
    for f in range(REVEAL_FRAMES + 1):
        sc = round(REVEAL_SCALE + (INIT_SCALE - REVEAL_SCALE)
                   * f / REVEAL_FRAMES) if f else REVEAL_SCALE
        assert sc < prev or f == 0, f
        prev = sc


def main(argv):
    if len(argv) != 2:
        print("usage: gen_boss_tracks.py <outdir>", file=sys.stderr)
        return 2
    outdir = Path(argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    ring, reveal, death = build_ring(), build_reveal(), build_death()
    _selftest(ring, reveal, death)
    for name, entries, want in (("bs_ring", ring, 1026),
                                ("bs_reveal", reveal, 246),
                                ("bs_death", death, 246)):
        data = blob(entries)
        assert len(data) == want, (name, len(data), want)  # == the rom claim
        (outdir / f"{name}.bin").write_bytes(data)
        print(f"wrote {outdir / name}.bin ({len(data)} B, "
              f"{len(entries)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
