#!/usr/bin/env python3
"""gen_saucer_tracks.py — boss_saucer's five matrix-track blobs.

Emits (byte-identical on re-run, pure integer math after the trig):

    sau_ring.bin    2 + 256*4 = 1,026 B   256 headings at the REST scale 1.5
    sau_reveal.bin  2 +  61*4 =   246 B   the grow-in, 5.0 -> 1.5
    sau_appr.bin    2 +  46*4 =   186 B   the LUNGE approach, 1.5 -> 0.625
    sau_retr.bin    2 +  46*4 =   186 B   the LUNGE retreat,  0.625 -> 1.5
    sau_death.bin   2 +  61*4 =   246 B   the recede, 1.5 -> ~4.78

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

THE SCHEDULES
-----------------------------------------------------------------------------
Scale maps screen->texel: a LARGER value samples a wider texel span, so the
saucer looks SMALLER (:98-99). Constants: INIT_SCALE $0180 (:101, the FAR/rest
pose), REVEAL_SCALE $0500 (:104), LUNGE_NEAR_SCALE $00A0 (:113),
DEATH_SCALE $0700 (:105 — declared, never reached), LUNGE_STEP =
(INIT-NEAR)/LUNGE_RAMP_FRAMES = $E0/40 = 5 (:117), REVEAL_STEP =
(REVEAL-INIT)/REVEAL_FRAMES = $380/60 = 14 (:210), REVEAL_FRAMES 60 (:176).

  RING (HOLD only, on this rail). 256 headings at the rest scale. The saucer's
  FIGHT does NOT rotate — `stz b_angle` at the HOLD exit (:566, "rotation OFF
  in the fight (scaling is the motion)") holds the angle at 0 for the whole
  fight, which is why every fight-side ramp below bakes ABSOLUTELY and this
  rail needs no ring-capture beat. The ring
  serves HOLD's +1/frame idle spin and supplies the reference entry the four
  seam asserts compare against.

  REVEAL (su_reveal :425-455, armed by battle_init :360-362 with b_angle=0).
  Reference, per frame f=1..60: scale -= 14, angle = f. That truncated step
  leaves scale at $01B8 when the timer expires and the terminal
  a bare `lda #INIT_SCALE` snap closes the last $38 in ONE frame — a
  5x-normal jump, an ~18% size pop on the reveal's final frame. The constants
  are identical to the boss's own reveal, so this file resolves it the same
  way the boss does: interpolate ENDPOINT-EXACT,
  entry f = round(REVEAL + (INIT - REVEAL) * f / 60), so the ramp lands on
  $0180 at f=60 with no pop. Entry 0 is the PRE-reveal pose (angle 0, scale
  $0500) — the matrix battle_init shows before the fade lifts.

  THE LUNGE. This is the rail's headline and it is a
  pure SCALE axis: angle is 0 throughout. The ramp runs by COMPARISON, not
  by counting — `sbc #LUNGE_STEP / cmp #LUNGE_NEAR_SCALE / bcs store` — so
  LUNGE_RAMP_FRAMES (40) sets only the STEP; the realized approach is
  384 -> 384-5f (f=1..44) -> a final clamp to 160, i.e. FORTY-FIVE frames with
  a terminal step of -4. Retreat is the mirror: 160 -> 160+5f (f=1..44) -> a
  final clamp to 384, again 45 frames, terminal step +4.
  BOTH realized sequences are baked EXACTLY, and they are NOT each
  other's reverse (reversed-approach frame 1 is 164, retreat frame 1 is 165),
  which is why there are two blobs rather than one walked both ways. Unlike
  the reveal's terminal step, these terminal steps are SMALLER than a normal
  step (4 vs 5), so they cannot pop — the rendered sequence is already the
  linear one, so it is kept exactly.

  DEATH. Per frame f=1..60: scale += 14
  (REVEAL_STEP again), angle += 3. The $0700 clamp (:488-490) NEVER fires:
  $0180 + 60*14 = $04C8 < $0700. The bake reproduces the REALIZED sequence
  because the pixels are the contract. Entry 0 is (angle 0, scale $0180) ==
  ring[0] == appr[0]: the fight->death seam, which is EXACT here rather than
  captured, because the fight's angle is 0 by construction.

SEAM ASSERTS — the four handovers cannot drift
----------------------------------------------
  reveal[60] == ring[60]   reveal -> hold (the spin continues at rest scale)
  appr[0]    == ring[0]    hold -> fight (the FAR/rest pose, angle snapped to 0)
  retr[0]    == appr[45]   near -> retreat (the apex pose is one pose)
  retr[45]   == appr[0]    retreat -> far (the cycle closes on the rest pose)
  death[0]   == ring[0]    fight -> death (angle 0, exact, no capture beat)
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

INIT_SCALE = 0x0180         # rest: whole saucer visible
REVEAL_SCALE = 0x0500       # reveal start: tiny/far
NEAR_SCALE = 0x00A0         # the lunge apex: fills the view
REVEAL_FRAMES = 60          # reveal/death ramp length
REVEAL_STEP = (REVEAL_SCALE - INIT_SCALE) // REVEAL_FRAMES  # = 14
LUNGE_STEP = (INIT_SCALE - NEAR_SCALE) // 40                # = 5
DEATH_SPIN = 3              # su_death's per-frame angle add

# The realized lunge ramp length: the walk stops on a COMPARISON, so this is
# derived here exactly as the ASM derives it, never narrated.
LUNGE_FRAMES = 1 + (INIT_SCALE - NEAR_SCALE - 1) // LUNGE_STEP      # = 45


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
    # the realized lunge length is the ASM's, not a narrated 40
    assert LUNGE_FRAMES == 45, LUNGE_FRAMES
    assert len(appr) == len(retr) == LUNGE_FRAMES + 1
    # the four seams (every handover the state machine performs)
    assert reveal[REVEAL_FRAMES] == ring[REVEAL_FRAMES], "reveal->hold seam"
    assert appr[0] == ring[0], "hold->fight seam (the FAR rest pose)"
    assert retr[0] == appr[LUNGE_FRAMES], "near->retreat seam (the apex pose)"
    assert retr[LUNGE_FRAMES] == appr[0], "retreat->far seam (cycle closes)"
    assert death[0] == ring[0], "fight->death seam (angle 0, exact)"
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
                                ("sau_appr", appr, 186),
                                ("sau_retr", retr, 186),
                                ("sau_death", death, 246)):
        data = blob(entries)
        assert len(data) == want, (name, len(data), want)  # == the rom claim
        (outdir / f"{name}.bin").write_bytes(data)
        print(f"wrote {outdir / name}.bin ({len(data)} B, "
              f"{len(entries)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
