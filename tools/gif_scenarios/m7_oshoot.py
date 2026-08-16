"""m7_oshoot — the rotating Mode 7 arena shooter.

The beats, and each is one claim the rail makes:

    walk        the floor ROTATES so the facing reads "up" and the pivot is
                re-pinned to the hero every frame — so walking is the arena
                sliding under a hero who never leaves the centre
    turn        a 45-degree sweep off the boot heading. NOT 90: the arena is a
                square pillar lattice over a square checker, so a quarter turn
                maps it almost onto itself and would read as unchanged. And
                the heading STEPS (3 units a frame) rather than snapping,
                which is the whole of — a sweep shows that, a snap
                would not
    volley      A tapped on its EDGE while walking, so bolts climb the screen
                in a train rather than one at a time
    kill        driven, not waited for: the clip runs its volley until the ROM
                shows a chaser wearing the score palette, which is what a
                dying one wears. A fixed frame count that happened to connect
                today would photograph a miss tomorrow
    hit         walked into, the same way: hold into the pillar face until the
                hero's own OAM slot parks, which is the invulnerability blink

WHY THE TAP CADENCE IS 2-ON / 4-OFF. A is an edge, and this is the fire rate
the rail's own renders use (tools/shot_m7_oshoot.py). At STEP=2 frames a
capture that is A held for one capture in three — full gameplay speed, which
is the format rule, and a bolt train rather than a polite single shot.

WALKING THROUGH THE VOLLEY IS DELIBERATE. Standing still is the wrong drive
here: chasers converge on a stationary hero, the first to touch knocks him
back to the arena centre and the rest follow, so the picture ends with one
chaser and a hero who has teleported. Walking keeps the field spread.
"""
from tools.record_gallery_clip import STEP
from vendor.mesen_runner import MemoryType

ROM = "m7_oshoot"
CAPTURES = 150                  # 7.5 s at 1:1
SETTLE = 40                     # past the fade-in, before the first wave beat

OAM = MemoryType.SnesSpriteRam
HERO_SLOT = 0
ENEMY_SLOTS = range(1, 7)
PARK_Y = 0xF0                   # mo_park_slot's "not drawn this frame"
ATTR_SCORE = 0x36               # priority 3 | OBJ palette 3 — worn only by a
                                #   dying chaser and the HUD digits


def _oam(r):
    return r.read_bytes(OAM, 0, 32)


def _hero_parked(r):
    return _oam(r)[HERO_SLOT * 4 + 1] == PARK_Y


def _kill_flash(r):
    o = _oam(r)
    return any(o[s * 4 + 3] == ATTR_SCORE for s in ENEMY_SLOTS)


class Arena:
    """One capture per call; the beat decides the pad, the ROM decides when."""

    def __init__(self):
        self.phase = 0
        self.n = 0
        self.saw_kill = False
        self.saw_hit = False

    def _next(self):
        self.phase += 1
        self.n = 0

    def _fire(self, i):
        return i % 3 == 0       # A on one capture in three — 2 on, 4 off

    def __call__(self, r, i):
        p, self.n = self.phase, self.n + 1

        if p == 0:                                  # establishing walk
            if self.n > 12:
                self._next()
            return r.frame_step(STEP, right=True)

        if p == 1:                                  # the 45-degree sweep
            if self.n > 12:
                self._next()
            return r.frame_step(STEP, up=True, left=True)

        if p == 2:                                  # volley until one dies
            if _kill_flash(r):
                self.saw_kill = True
            if self.saw_kill and self.n > 4:
                self._next()
            if self.n > 60:                         # the wave ring is timed;
                self._next()                        #   do not stall the take
            return r.frame_step(STEP, right=True, a=self._fire(i))

        if p == 3:                                  # keep the field working
            if self.n > 24:
                self._next()
            return r.frame_step(STEP, up=True, a=self._fire(i))

        # ...and walk hard into the pillar face until a chaser lands a hit,
        # then keep going: the blink is the cue and it wants a few captures
        # either side of it to read as a blink rather than a dropped sprite.
        if _hero_parked(r):
            self.saw_hit = True
        return r.frame_step(STEP, right=True, a=self._fire(i))


def make_drive():
    return Arena()
