"""railshooter — the on-rails shooter, flown by an autopilot.

THE DRIVE IS A PILOT LOOP, NOT AN INPUT SCRIPT. Each capture reads OAM, finds
the nearest live hazard, steers the reticle onto it and fires when it is on.
That is the same closed loop tools/shot_railshooter.py uses to photograph its
kill frame, and it is here for the same reason: a fixed pad script that
happened to connect today would photograph a miss tomorrow, because the rail's
S-curve and its spawn ring are on their own clock, not the recorder's.

What a viewer gets out of it, without being told:

    the rail      the S-curve carrying the ship, the field spread in depth
    the drag      the swing drags the reticle off centre; the autopilot is
                  fighting it the whole clip, which is what flying this rail
                  actually feels like
    kills         hazards acquired, centred and shot — the flash, the score
                  digits moving
    the pylons    the obstacle column the curve bends around, at close range
    the life bar  spending down as the ones that get through connect

FULL SPEED, WHICH HERE MEANS FIRING ON COOLDOWN. A is pressed on the capture
the reticle is on target and released the next, so it is a real edge and the
volley is as fast as the rail allows. A politely-spaced shot would read as
hesitation at 1:1 playback (the split_h lesson).

The OAM window is NAMED, not spelled `20 + i` inline: an OAM reorder once
walked straight into that in the shot script, and two committed renders
quietly showed the wrong moment with no error anywhere.
"""
from tools.record_gallery_clip import STEP
from vendor.mesen_runner import MemoryType

ROM = "railshooter"
CAPTURES = 160                  # 8.0 s at 1:1
SETTLE = 150                    # EMULATED frames — the fade-in is done and
                                #   the hazard field has spread in depth

OAM = MemoryType.SnesSpriteRam
RET_SLOT = 0                    # game/railshooter/railshooter.inc, front to back
HAZ_SLOT0, HAZ_N = 3, 4
T_HAZ = (8, 12, 164, 166)       # nearest-first tile order
LARGE = (8, 12)                 # ...the two that are 16x16


def _entry(o, s):
    x, y, tile, _attr = o[s * 4:s * 4 + 4]
    x9 = (o[512 + (s >> 2)] >> ((s & 3) * 2)) & 1
    v = x + 256 * x9
    return (v - 512 if v >= 256 else v), y, tile


def _nearest(o):
    live = [_entry(o, s) for s in range(HAZ_SLOT0, HAZ_SLOT0 + HAZ_N)
            if o[s * 4 + 2] != 0]
    return min(live, key=lambda h: T_HAZ.index(h[2])) if live else None


class Pilot:
    """One capture per call: look, steer, and fire on the cooldown."""

    def __call__(self, r, i):
        o = r.read_bytes(OAM, 0, 544)
        tgt = _nearest(o)
        pad = {}
        if tgt is not None:
            tx, ty, tile = tgt
            half = 16 if tile in LARGE else 8
            rx, ry, _ = _entry(o, RET_SLOT)
            rcx, rcy = rx + 8, ry + 8
            if tx + half - rcx > 4:
                pad["right"] = True
            elif rcx - (tx + half) > 4:
                pad["left"] = True
            if ty + half - rcy > 4:
                pad["down"] = True
            elif rcy - (ty + half) > 4:
                pad["up"] = True
        # FIRE ON THE COOLDOWN, NOT ONLY WHEN PERFECTLY CENTRED. Waiting for
        # a clean lock spends the whole clip aiming: measured, a fire-when-
        # locked pilot scored 1 and lost every life in 8 s, because the swing
        # drags the reticle off the target between the lock and the shot.
        # Every other capture is A on its edge, which is the rail's own rate.
        pad["a"] = (i % 2 == 0)
        return r.frame_step(STEP, **pad)


def make_drive():
    return Pilot()
