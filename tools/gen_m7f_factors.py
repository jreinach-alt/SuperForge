#!/usr/bin/env python3
"""gen_m7f_factors.py — mode7_flight: the TWO POSE FACTORS, baked separately.

THE DESIGN THIS IMPLEMENTS: separate the two axes and bake them apart.

A per-scanline Mode 7 pose factors exactly:

    pose(h, a)[k] = S_a(k) * R(h)

    A = S*cos   B = S*sin   C = -S*sin = -B   D = S*cos = A      (8.8 signed)

which is how tools/gen_pose_tables.py already writes it (:11). Heading enters
ONLY through (cos, sin); altitude enters ONLY through the per-scanline scale
profile. The PRODUCT of the two axes is 256 headings x 81 altitudes x 640 B =
12.7 MB and fits no cartridge at any quantisation-free granularity;
the two FACTORS are ~28 KB and are EXACT on both axes. This script
bakes the factors; engine/features/m7f_cam joins them per frame through the
hardware multiplier.

--- factor 1: the altitude axis, m7f_prof.bin -------------------------------

81 reachable altitudes {0, 3, ..., 240} — MEASURED on the rail rather than
assumed: ALT_STEP is 3, both clamps are multiples of 3 and
spawn is 120, so no value off the x3 lattice is reachable. Indexed by
ALTITUDE INDEX 0..80 (the rail stores the index, not the altitude — a divide
by 3 in the join's addressing would be a per-frame cost for nothing).

Per altitude, two scale endpoints:

    s0 = S0_LOW + ((alt * S0_SPAN) >> 8)      the FAR/horizon coefficient
    s1 = S1_LOW + ((alt * S1_SPAN) >> 8)      the NEAR/bottom coefficient

and the band-local profile is gen_pose_tables.py's hyperbola through them:

    k0 = s1*(L-1)/(s0-s1)     K = s0*k0     S(k) = round(K/(k+k0))

STORED AS ONE BYTE PER SCANLINE, pre-shifted into the HIGH half of a word:

    p(k) = min(255, round(S(k) / 4))          entry = p(k) << 8

One byte is not a compromise chosen here — it is the precision a per-scanline
reciprocal LUT of this shape carries anyway. A `pv_ztable`-style table returns
an 8-bit value (`vendor/probe_ref/inc/mode7_diz_ztable.inc`) and therefore
CLAMPS, measured as the horizon coefficient saturating above s0 = 1020, i.e.
above alt ~= 213 of 240. `min(255, S/4)` clamps at S = 1020 EXACTLY, so the
same flat top falls out of this representation by construction rather than by
a special case.

p<<8 (not p) because the join stages the multiply operands with ONE 16-bit
store: A = (p << 8) | mag, `sta $4202` writes $4202 = mag and $4203 = p, and
the multiply starts on the $4203 write. See m7f_cam.asm.

STRIDE 2 B/line -> 320 B/profile -> 25,920 B total, which fits ONE 32 KB LoROM
window with 6,848 B spare. That is the reason for the stride: a 4 B stride
would be 51,840 B, span two windows, and put a bank boundary in the middle of
a profile — where `lda f:base,x` cannot reach, since X wraps inside its bank.

--- factor 2: the heading axis, m7f_trig.bin --------------------------------

256 headings (MEASURED: one unit of 256 per frame held, masked `and #$00FF`).
Per heading, four words:

    +0  cmag   min(255, round(256*|cos|))     the 8-bit multiplier operand
    +2  smag   min(255, round(256*|sin|))
    +4  cneg   $0000 if cos >= 0 else $FFFF   two's-complement sign mask
    +6  sneg   $0000 if sin >= 0 else $FFFF

The magnitude CLAMP at 255 is required, not cosmetic: round(256*|cos|) is 256
at the four cardinal headings, and both a byte operand and the 16-bit product
(p*mag <= 255*255 = 65025) need it to be <= 255. It costs one part in 256 at
exactly those four headings.

Signs are masks rather than flags because the join hoists them OUT of the
per-scanline loop entirely (four loop variants, chosen once per frame), and a
mask is what a variant selector reads.

--- the arithmetic the join must reproduce EXACTLY --------------------------

    P     = p * mag                    (hardware multiply, $4202/$4203/$4216)
    |A|   = P >> 6
    A     = (|A| ^ cneg) - cneg        two's complement under the mask

and P>>6 is the whole reason for these units: p = S/4 and mag = 256*|trig|, so
P = 64*S*|trig| = 64*|A|. tests/test_mode7_flight.py mirrors this in Python and
compares the WHOLE composed band table, every entry, against it.

Deterministic: pure math.cos/round from these constants — byte-identical on
re-run, which is what `make falsify`'s md5 arm and the rebuild proof rest on.

Usage: gen_m7f_factors.py OUTDIR
"""
import argparse
import math
import sys
from pathlib import Path

# --- the band, measured on the rail ----------------------------------------
# PV_L0_FLIGHT = 64, PV_L1_FLIGHT = 224
BAND_BOT = 224                              # the band's bottom, FIXED
BAND_TOP_DECK = 64                          # ...and its top at DECK level
LINES = BAND_BOT - BAND_TOP_DECK            # 160 — the LONGEST band

# --- the moving horizon -----------------------------------------------------
# The band's TOP is a function of altitude, on the classic form
# `pv_l0 = 32 + height/2`, solved against this rail's own domain:
#
#     horizon(a) = 64 + 2*(a >> 2)      band(a) = 224 - horizon(a)
#
# so the deck keeps 160 lines from scanline 64 and the ceiling gets 120 lines
# from scanline 104 — the sky grows from 29% of the screen to 46% as the
# airship climbs, which is the observation this exists to answer.
#
# DECK LEVEL IS TODAY'S EXACT GEOMETRY, BY CONSTRUCTION. Every number already
# measured against this rail -- the worst-case join cost, the skip cost, the
# oracle's line count -- was taken at the deck, so preserving a = 0 exactly is
# what keeps them true rather than merely close. Climbing only ever SHORTENS
# the band, so the worst case cannot move.
BAND_STEP = 2                               # scanlines per altitude quantum
BAND_QUANT = 4                              # ...one quantum per 4 altitude idx


def band_top(alt_idx: int) -> int:
    return BAND_TOP_DECK + BAND_STEP * (alt_idx // BAND_QUANT)


def band_lines(alt_idx: int) -> int:
    return BAND_BOT - band_top(alt_idx)

# --- the altitude axis, measured -------------------------------------------
ALT_MIN, ALT_MAX, ALT_STEP = 0, 240, 3
ALT_SPAWN = 120
ALTS = list(range(ALT_MIN, ALT_MAX + 1, ALT_STEP))          # 81 values
ALT_LEVELS = len(ALTS)
ALT_SPAWN_IDX = ALTS.index(ALT_SPAWN)                       # 40

# --- the scale endpoints ---------------------------------------------------
S0_LOW, S1_LOW = 220, 40
S1_SPAN = 240
# --- the far-scale span is capped so the profile NEVER clamps ---------------
# A span of 960 would take s0 to 1120; 853 tops it out at 1019, so
# `min(255, S/4)` never saturates.
#
# THIS REVERSES AN EARLIER CHOICE, and the earlier one was wrong. It
# reproduced a `pv_ztable`-style 8-bit clamp on the belief that the clamp
# applied to the scale profile. It does not: that clamp sits on a RUNTIME Z
# accumulator, at a different point in the pipeline. Reproducing it here gave
# FOUR identical coefficients at the top of the band at max altitude — a flat,
# face-on far region. On screen that reads as the horizon turning to face the
# camera instead of receding, which is the opposite of what altitude is
# supposed to do.
#
# Checked rather than argued: a correct profile is STRICTLY DECREASING from
# the near row to the far row at every altitude — e.g. (1120, 1098, 1076,
# 1056, ...) rather than a repeated value. Ours now is, at every altitude.
S0_SPAN = 853

# --- the join's fixed units -------------------------------------------------
PROF_SHIFT = 2          # p = S >> PROF_SHIFT   (S clamps at 255*4 = 1020)
MAG_BITS = 8            # mag = 2^MAG_BITS * |trig|, clamped to 255
JOIN_SHIFT = MAG_BITS - PROF_SHIFT          # 6: |A| = (p*mag) >> 6

HEADINGS = 256
PROF_STRIDE = LINES * 2                     # 320 B per altitude
# The join is software-pipelined: each line stages the NEXT line's operand
# inside the multiplier's latency window, so the LAST line of the LAST group
# reads one group-stride past the last altitude's profile. Eight bytes of guard
# make that read land inside the claim instead of on whatever the allocator
# placed next -- a read of uninitialised ROM is still a read of something this
# rail does not own (rule 5). The value is discarded; only its ADDRESS matters.
PROF_GUARD = 8
TRIG_STRIDE = 8                             # 4 words per heading

# The FORMAT VERSION of the two blobs' record layout, emitted beside them in
# m7f_factors.inc so the consumer can pin the shape it reads. BUMP IT whenever
# the LAYOUT changes -- a different stride, a different record order, a
# different number of words per heading, a different profile quantisation. Do
# NOT bump it when only the VALUES move (a retuned scale span, a new horizon
# curve): those are the same shape and the consumer's offsets still hold.
#
# WHY IT EXISTS. The consumer used to state it checked exactly this, and did
# not: m7f_cam.asm re-narrated LINES / ALT_LEVELS / HEADINGS / the two strides
# and asserted their PRODUCT against the allocator's claim size. A layout
# refactor that preserves the product -- 80 lines at 4 B per entry instead of
# 160 at 2, say -- passes that assert and shifts every offset the join reads.
FACTORS_FORMAT = 1


def endpoints(alt: int) -> tuple[int, int]:
    """The two scale endpoints for an altitude."""
    return (S0_LOW + ((alt * S0_SPAN) >> 8),
            S1_LOW + ((alt * S1_SPAN) >> 8))


def scale_profile(alt: int, n_lines: int | None = None) -> list[int]:
    """gen_pose_tables.py's hyperbola, solved over THIS altitude's band.

    The band shortens as the airship climbs, so the hyperbola is solved through
    (s0 at k = 0, s1 at k = n-1) for THAT n — not over a fixed 160 and then
    truncated. Truncating would leave the near end of a short band holding a
    coefficient meant for a row that is no longer on screen, which reads as the
    ground running out before the bottom of the picture.
    """
    n = LINES if n_lines is None else n_lines
    s0, s1 = endpoints(alt)
    k0 = s1 * (n - 1) / (s0 - s1)
    k = s0 * k0
    prof = [round(k / (i + k0)) for i in range(n)]
    assert prof[0] == s0 and prof[-1] == s1, (alt, prof[0], prof[-1], s0, s1)
    return prof


def quantise(s: int) -> int:
    """S -> the 8-bit profile byte. The clamp is the reciprocal LUT's own."""
    return min(255, (s + (1 << (PROF_SHIFT - 1))) >> PROF_SHIFT)


def trig_entry(h: int) -> tuple[int, int, int, int]:
    """(cmag, smag, cneg, sneg) for heading h of HEADINGS."""
    th = 2 * math.pi * h / HEADINGS
    c, s = math.cos(th), math.sin(th)
    cmag = min(255, round((1 << MAG_BITS) * abs(c)))
    smag = min(255, round((1 << MAG_BITS) * abs(s)))
    return cmag, smag, 0xFFFF if c < 0 else 0, 0xFFFF if s < 0 else 0


def coeff(p: int, mag: int, neg: int) -> int:
    """The JOIN's arithmetic, in Python. The ASM must match this exactly."""
    a = (p * mag) >> JOIN_SHIFT
    return ((a ^ neg) - neg) & 0xFFFF


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    # ---- factor 1: the altitude profiles -----------------------------------
    prof = bytearray()
    clamped_levels = 0
    for alt_idx, alt in enumerate(ALTS):
        n = band_lines(alt_idx)
        raw = scale_profile(alt, n)
        # The hyperbola is strictly decreasing from the horizon to the bottom
        # of the band; a profile that is not is a generator defect, not art.
        assert all(x >= y for x, y in zip(raw, raw[1:])), alt
        row = [quantise(s) for s in raw]
        if row[0] == 255:
            clamped_levels += 1
        for p in row:
            assert 0 <= p <= 255, (alt, p)
            prof += bytes((0, p))           # little-endian p<<8
        # Every altitude occupies the SAME stride whatever its band length, so
        # the join's `index * stride` addressing stays a shift-and-add. The
        # tail past band_lines(a) is never read: the segment limits are derived
        # from the same band_lines().
        prof += bytes(2 * (LINES - n))
        assert len(prof) % PROF_STRIDE == 0
    prof += bytes(PROF_GUARD)               # the pipeline's read-ahead guard
    assert len(prof) == ALT_LEVELS * PROF_STRIDE + PROF_GUARD, len(prof)

    # ---- factor 2: the heading trig ----------------------------------------
    trig = bytearray()
    for h in range(HEADINGS):
        cmag, smag, cneg, sneg = trig_entry(h)
        for w in (cmag, smag, cneg, sneg):
            trig += int(w).to_bytes(2, "little")
    assert len(trig) == HEADINGS * TRIG_STRIDE, len(trig)

    # ---- the identity the CD channel rests on, asserted at BAKE time -------
    # C = -B and D = A holds by construction here (the join computes exactly
    # two products per scanline and derives the other two words), so the
    # assertion is that the JOIN's own arithmetic honours it: composing
    # heading h must give CD(h) == AB(h + HEADINGS/4) byte-for-byte, which is
    # the quarter-turn identity, re-verified against THIS quantisation rather
    # than against gen_pose_tables.py's float one.
    quarter = HEADINGS // 4
    for alt_idx in (0, ALT_SPAWN_IDX, ALT_LEVELS - 1):
        n = band_lines(alt_idx)
        row = [quantise(s) for s in scale_profile(ALTS[alt_idx], n)]
        for h in (0, 1, 37, 64, 129, 200, 255):
            cm, sm, cn, sn = trig_entry(h)
            qm, qs, qn, qsn = trig_entry((h + quarter) % HEADINGS)
            for p in (row[0], row[n // 2], row[-1]):
                bb = coeff(p, sm, sn)                     # B at h
                aa = coeff(p, cm, cn)                     # A at h
                # CD(h) = (-B, A); AB(h+90deg) = (A', B')
                assert (-bb) & 0xFFFF == coeff(p, qm, qn), (alt_idx, h, p)
                assert aa == coeff(p, qs, qsn), (alt_idx, h, p)

    (out / "m7f_prof.bin").write_bytes(prof)
    (out / "m7f_trig.bin").write_bytes(trig)

    # ---- the layout, emitted beside the bytes it describes -----------------
    # So the consumer PINS the shape it reads instead of re-narrating it. The
    # allocator's claim sizes say how BIG each blob is; nothing said how it was
    # divided up, which is the half the join's offsets actually depend on.
    (out / "m7f_factors.inc").write_text("\n".join([
        "; m7f_factors.inc — GENERATED by superforge/tools/gen_m7f_factors.py",
        "; Do not edit. The RECORD LAYOUT of m7f_prof.bin and m7f_trig.bin.",
        ";",
        "; M7F_FACTORS_FORMAT is the version of that layout. A consumer pins it",
        "; with `.assert M7F_FACTORS_FORMAT = N` and re-derives its own offsets",
        "; when the number moves; the constants below are what those offsets",
        "; are made of, so pinning them too makes the check exact rather than",
        "; ceremonial.",
        f"M7F_FACTORS_FORMAT = {FACTORS_FORMAT}",
        "",
        "; m7f_prof.bin: ALT_LEVELS profiles of LINES entries, 2 B each, then",
        "; GUARD bytes for the join's read-ahead past the last altitude.",
        f"M7F_FACTORS_LINES = {LINES}",
        f"M7F_FACTORS_ALT_LEVELS = {ALT_LEVELS}",
        f"M7F_FACTORS_ALT_SPAWN = {ALT_SPAWN_IDX}",
        f"M7F_FACTORS_PROF_STRIDE = {PROF_STRIDE}",
        f"M7F_FACTORS_PROF_GUARD = {PROF_GUARD}",
        "",
        "; m7f_trig.bin: HEADINGS records of (cmag, smag, cneg, sneg), 2 B each.",
        f"M7F_FACTORS_HEADINGS = {HEADINGS}",
        f"M7F_FACTORS_TRIG_STRIDE = {TRIG_STRIDE}",
        "",
        "; the join's fixed shift: |A| = (p * mag) >> JOIN_SHIFT",
        f"M7F_FACTORS_JOIN_SHIFT = {JOIN_SHIFT}",
        "",
    ]))

    print(f"m7f_prof: bands {band_lines(ALT_LEVELS - 1)}..{band_lines(0)} lines "
          f"(horizon {band_top(0)}..{band_top(ALT_LEVELS - 1)}); "
          f"{ALT_LEVELS} altitudes x {LINES} stride x 2 B "
          f"+ {PROF_GUARD} B pipeline guard = {len(prof)} B "
          f"({clamped_levels} levels clamped at the horizon)")
    print(f"m7f_trig: {HEADINGS} headings x {TRIG_STRIDE} B = {len(trig)} B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
