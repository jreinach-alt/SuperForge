#!/usr/bin/env python3
"""gen_move_lut.py — microzero heading LUT + the race physics oracle.

Emits move_lut.inc:
  * `move_lut`: 64 x [.word ux, uy] — the UNIT forward direction per pose
    heading in 8.8 fixed point (+-256 = +-1.0), two's complement.
  * the physics equates (MZ_VEL_MAX/ACCEL/BRAKE/...) the ROM assembles
    against, so the constants have exactly ONE source of truth.

Direction convention (unchanged from the flat-step LUT this replaces, and
locked by the rotation tests): it matches tools/gen_pose_tables.py's matrix
(A=S cos, B=S sin, C=-S sin, D=S cos, theta = 2*pi*h/64) — screen-forward at
heading h is world (-sin theta, -cos theta), so h=0 north, h=16 west,
h=32 south, h=48 east (h increases counterclockwise on the map; steering
LEFT increments h).

The physics (race_logic.asm implements exactly this, integer-for-integer):

    vel is signed 8.8 px/frame.  B accelerates toward MZ_VEL_MAX, Down
    brakes to a stop and then reverses toward MZ_VEL_MIN, and coasting
    decays toward 0 by MZ_FRICTION.  The per-axis step is

        step = sign(u)*sign(vel) * ((|u| * |vel|) >> 8)        [8.8 px]

    (magnitude-then-sign, NOT an arithmetic shift of a signed product —
    the ROM computes the magnitude with the hardware multiplier and applies
    the sign afterwards, so the oracle must do the same).  Position keeps a
    per-axis 8-bit sub-pixel accumulator:

        t   = sub + step ;  sub = t & 255 ;  pos = (pos + (t >> 8)) & 4095

    with `>>` FLOOR semantics (the ROM sign-extends the high byte).

Tests import Sim as the movement oracle — it is bit-exact against the ROM.
"""
import math
import sys
from pathlib import Path

POSES = 64
UNIT = 256                          # 8.8 one

# --- physics constants (8.8 px/frame, 8.8 px/frame^2) ----------------------
VEL_MAX = 0x3000                    # +48.0 px/f — the declared max
VEL_MIN = -0x1000                   # -16.0 px/f — reverse cap
ACCEL = 0x0100                      # 1.0   — B held: 48 frames to top speed
BRAKE = 0x0180                      # 1.5   — Down held while moving forward
REVERSE = 0x0080                    # 0.5   — Down held at or below a stop
FRICTION = 0x0040                   # 0.25  — coasting decay toward 0

# --- world/lap geometry (tools/gen_m7_assets.py's ring, in world pixels) ---
WORLD_PX = 4096
CENTER_PX = 2048                    # the ring's centre (tile 256 * 8)
CKPT_ALL = 0x0F                     # all four sectors visited


def unit(h: int) -> tuple[int, int]:
    """Forward direction at pose heading h as an 8.8 unit vector."""
    th = 2 * math.pi * (h % POSES) / POSES
    return (round(-UNIT * math.sin(th)), round(-UNIT * math.cos(th)))


def scale(u: int, vel: int) -> int:
    """One axis of the per-frame step: magnitude via the hardware multiplier,
    sign applied afterwards (exactly what race_logic.asm does)."""
    mag = (abs(u) * abs(vel)) >> 8
    return -mag if (u < 0) != (vel < 0) else mag


def sector(x: int, y: int) -> int:
    """Quadrant of the world centre: 0 NE, 1 NW, 2 SW, 3 SE (y grows south).
    The start/finish spoke runs due east, so it is exactly the 3->0 edge."""
    east = ((x - CENTER_PX) & 0x8000) == 0      # dx >= 0 (signed 16-bit)
    north = ((y - CENTER_PX) & 0x8000) != 0     # dy <  0
    if north:
        return 0 if east else 1
    return 3 if east else 2


class Sim:
    """Bit-exact mirror of race::tick — the tests' movement/lap oracle."""

    def __init__(self, x, y, h=0, vel=0, sub_x=0, sub_y=0,
                 lap=0, sect=None, ckpt=None):
        self.x, self.y, self.h, self.vel = x, y, h, vel
        self.sub_x, self.sub_y = sub_x, sub_y
        self.lap = lap
        self.sector = sector(x, y) if sect is None else sect
        self.ckpt = (1 << self.sector) if ckpt is None else ckpt

    def frame(self, *, left=False, right=False, b=False, down=False):
        # 1. steer (1 pose step/frame — the declared max turn)
        if left:
            self.h = (self.h + 1) & (POSES - 1)
        if right:
            self.h = (self.h - 1) & (POSES - 1)
        # 2. velocity: accelerate / brake+reverse / coast
        if b:
            self.vel = min(self.vel + ACCEL, VEL_MAX)
        elif down:
            if self.vel > 0:
                self.vel = max(self.vel - BRAKE, 0)
            else:
                self.vel = max(self.vel - REVERSE, VEL_MIN)
        elif self.vel > 0:
            self.vel = max(self.vel - FRICTION, 0)
        elif self.vel < 0:
            self.vel = min(self.vel + FRICTION, 0)
        # 3. integrate position through the sub-pixel accumulators
        ux, uy = unit(self.h)
        t = self.sub_x + scale(ux, self.vel)
        self.sub_x = t & 255
        self.x = (self.x + (t >> 8)) & (WORLD_PX - 1)
        t = self.sub_y + scale(uy, self.vel)
        self.sub_y = t & 255
        self.y = (self.y + (t >> 8)) & (WORLD_PX - 1)
        # 4. lap: a full sector circuit closed by the east-spoke 3->0 crossing
        s = sector(self.x, self.y)
        if self.sector == 3 and s == 0 and self.ckpt == CKPT_ALL:
            self.lap += 1
            self.ckpt = 0
        self.ckpt |= 1 << s
        self.sector = s
        return self

    @property
    def pos(self):
        return (self.x, self.y)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: gen_move_lut.py <outdir>", file=sys.stderr)
        return 2
    outdir = Path(sys.argv[1])
    outdir.mkdir(parents=True, exist_ok=True)
    lines = ["; GENERATED by tools/gen_move_lut.py — do not edit.",
             "; 64 x [.word ux, uy]: the forward direction per pose heading",
             "; as an 8.8 unit vector (+-256 = +-1.0). race_logic scales it by",
             "; the signed 8.8 velocity; the generator is the tests' oracle.",
             "",
             "; ---- race physics constants (the ONE source of truth) --------",
             f"MZ_VEL_MAX  = ${VEL_MAX:04X}         ; +48.0 px/f",
             f"MZ_VEL_MIN  = ${VEL_MIN & 0xFFFF:04X}         ; -16.0 px/f",
             f"MZ_ACCEL    = ${ACCEL:04X}",
             f"MZ_BRAKE    = ${BRAKE:04X}",
             f"MZ_REVERSE  = ${REVERSE:04X}",
             f"MZ_FRICTION = ${FRICTION:04X}",
             f"MZ_CENTER_PX = {CENTER_PX}",
             f"MZ_CKPT_ALL  = {CKPT_ALL}",
             "",
             "move_lut:"]
    for h in range(POSES):
        ux, uy = unit(h)
        lines.append(f"    .word ${ux & 0xFFFF:04X}, ${uy & 0xFFFF:04X}"
                     f"    ; h={h:2d} ({ux:+4d},{uy:+4d})")
    (outdir / "move_lut.inc").write_text("\n".join(lines) + "\n")
    print(f"move_lut.inc: {POSES} unit headings, vel cap ${VEL_MAX:04X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
