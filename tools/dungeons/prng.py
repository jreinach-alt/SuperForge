"""prng.py — the ONE random source of SuperForge Dungeons, as a reference model.

The ROM's generator, loot roller and enemy AI all draw from this stream; the
ASM implementation must match this function BIT FOR BIT, because the tests use
this model as their oracle (a generated level read out of WRAM/VRAM is compared
against what this file says that seed produces).

Algorithm: 16-bit xorshift, triple (7, 9, 8). Period 65,535 over every nonzero
state; zero is a fixed point and is therefore never a legal state. It is the
cheapest full-period generator a 65816 runs in A16: three shift-and-EOR steps,
no multiply, no table. The ROM spec's measured target is <= 60 cycles a draw
(docs/dungeons/03 §2.2 says how that is measured, not estimated).

    x ^= x << 7
    x ^= x >> 9
    x ^= x << 8       (all & 0xFFFF)

Seeding: a level's stream is seeded from (run_seed, floor_index) through
`level_seed`, so a floor can be regenerated without replaying every draw that
came before it (needed for "retry this floor" and for the tests).
"""

MASK = 0xFFFF


def step(x: int) -> int:
    """Advance one xorshift16 state. `x` must be nonzero."""
    if not 0 < x <= MASK:
        raise ValueError(f"xorshift16 state must be 1..0xFFFF, got {x:#x}")
    x ^= (x << 7) & MASK
    x ^= x >> 9
    x ^= (x << 8) & MASK
    return x


def level_seed(run_seed: int, floor_index: int) -> int:
    """Derive a floor's starting state. Never returns 0.

    Mixes the floor index in with a multiply-free scramble the ROM can do in a
    few instructions: EOR with the index times an odd constant, then step twice
    so adjacent floors do not start on adjacent states.
    """
    x = (run_seed ^ ((floor_index * 0x9E37) & MASK)) & MASK
    if x == 0:
        x = 0xACE1
    return step(step(x))


class Stream:
    """A draw stream. Every consumer that must stay deterministic owns one.

    The ROM keeps exactly two live states (spec §2.3): GEN (level generation
    and loot, deterministic from the seed) and FX (cosmetic + AI jitter, may
    diverge freely). Only GEN is modelled here because only GEN is asserted.
    """

    def __init__(self, state: int):
        if not 0 < state <= MASK:
            raise ValueError("stream state must be nonzero")
        self.state = state
        self.draws = 0

    def next16(self) -> int:
        self.state = step(self.state)
        self.draws += 1
        return self.state

    def below(self, n: int) -> int:
        """Uniform-ish value in [0, n) for 1 <= n <= 256.

        Spec: high byte of the next state, times n, high byte of the product —
        one 8x8 hardware multiply (WRMPYA/WRMPYB) on the SNES, no division, no
        rejection loop (so the draw count per call is always exactly 1, which
        keeps the stream's position predictable). Bias is < 1/256, accepted.
        """
        if not 1 <= n <= 256:
            raise ValueError("below(n) supports 1..256")
        return ((self.next16() >> 8) * n) >> 8

    def chance(self, num: int, den: int = 256) -> bool:
        """True with probability num/den (den must be 256 in ROM terms)."""
        if den != 256:
            raise ValueError("ROM chance() is out of 256")
        return (self.next16() >> 8) < num

    def weighted(self, weights) -> int:
        """Index chosen with probability proportional to weights (sum <= 256).

        One draw. Weights tables are authored so they sum to exactly 256
        wherever possible; the tool that emits them checks the sum.
        """
        total = sum(weights)
        if not 1 <= total <= 256:
            raise ValueError(f"weight sum must be 1..256, got {total}")
        r = self.below(total)
        for i, w in enumerate(weights):
            if r < w:
                return i
            r -= w
        raise AssertionError("unreachable")
