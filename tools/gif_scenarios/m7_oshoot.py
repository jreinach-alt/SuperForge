"""m7_oshoot — the rotating Mode 7 arena shooter.

The beats, and each is one claim the rail makes:

    walk        the floor ROTATES so the facing reads "up" and the pivot is
                re-pinned to the hero every frame — so walking is the arena
                sliding under a hero who never leaves the centre
    volley      A tapped on its EDGE while walking, so bolts climb the screen
                in a train rather than one at a time
    kill        driven, not waited for: the outbound leg does not end until
                the ROM shows a chaser wearing the score palette, which is
                what a dying one wears. A fixed frame count that happened to
                connect today would photograph a miss tomorrow
    turn        a 45-degree sweep off the walking heading. NOT 90: the arena is
                a square pillar lattice over a square checker, so a quarter
                turn maps it almost onto itself and would read as unchanged.
                And the heading STEPS (3 units a frame) rather than snapping —
                a sweep shows that, a snap would not
    walk back   the same axis reversed, which is the second half of the loop
                and reads as the arena sliding the other way

WHY THE TAP CADENCE IS 2-ON / 4-OFF. A is an edge, and this is the fire rate
the rail's own renders use (tools/shot_m7_oshoot.py). At STEP=2 frames a
capture that is A held for one capture in three — full gameplay speed, which
is the format rule, and a bolt train rather than a polite single shot.

WALKING THROUGH THE VOLLEY IS DELIBERATE. Standing still is the wrong drive
here: chasers converge on a stationary hero, the first to touch knocks him
back to the arena centre and the rest follow, so the picture ends with one
chaser and a hero who has teleported. Walking keeps the field spread.

THE LOOP POINT IS AN OUT-AND-BACK, because this rail has no scene edge to fade
on — one scene, one arena, no state that reaches black. What it has instead is
a pad that is exactly reversible, and that is measured rather than assumed:
ten captures of Right move the heading 0 -> 196 and ten of Left put it back on
0 to the unit, while Up and Down walk US_POSX/US_POSY out and back to the same
32-bit values. So the take walks out under the volley, sweeps the heading and
sweeps it back, then walks home, and closes when the heading AND both position
words are exactly what they were at the opening capture — read off the ROM, not
counted to.

THE TURN IS TAKEN STANDING, and that is what keeps the circuit exact. Motion is
along the facing, so a turn taken while walking curves the path and no amount
of walking back down the final heading unwinds it. The sweep is short and the
volley continues through it, which is what keeps the converging chasers off.
"""
import json
from pathlib import Path

from tools.record_gallery_clip import STEP
from vendor.mesen_runner import MemoryType

ROOT = Path(__file__).resolve().parent.parent.parent

ROM = "m7_oshoot"
CAPTURES = 260                  # a CEILING: the circuit closes the take
SETTLE = 40                     # past the fade-in, before the first wave beat

OAM = MemoryType.SnesSpriteRam
W = MemoryType.SnesWorkRam
_J = json.loads((ROOT / "build" / "mo" / "symbol_map.json").read_text())
_S = {p["sym"]: p["start"] for p in _J["scenes"]["arena"]["placements"]}
PX, PY, HEADING = _S["US_POSX"], _S["US_POSY"], _S["US_HEADING"]

HERO_SLOT = 0
ENEMY_SLOTS = range(1, 7)
PARK_Y = 0xF0                   # mo_park_slot's "not drawn this frame"
ATTR_SCORE = 0x36               # priority 3 | OBJ palette 3 — worn only by a
                                #   dying chaser and the HUD digits
OUT_CAPTURES = 70               # the outbound leg; the return matches it
SWEEP = 48                      # heading units off the walk — the 45-degree cut


def _oam(r):
    return r.read_bytes(OAM, 0, 32)


def _kill_flash(r):
    o = _oam(r)
    return any(o[s * 4 + 3] == ATTR_SCORE for s in ENEMY_SLOTS)


def _p32(r, off):
    b = r.read_bytes(W, off, 4)
    return b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24)


def _pose(r):
    return (_p32(r, PX), _p32(r, PY), r.read_u16(W, HEADING))


class Arena:
    """One capture per call; the beat decides the pad, the ROM decides when."""

    def __init__(self):
        self.phase = 0
        self.n = 0
        self.open_pose = None
        self.mark = None
        self.done = False
        self.saw_kill = False

    def _next(self):
        self.phase += 1
        self.n = 0
        self.mark = None

    def _fire(self, i):
        return i % 3 == 0       # A on one capture in three — 2 on, 4 off

    def __call__(self, r, i):
        p, self.n = self.phase, self.n + 1
        if self.open_pose is None:
            self.open_pose = _pose(r)

        # THE PHASE ADVANCES BEFORE THE PAD IS CHOSEN. The heading steps 6 units
        # a capture, so a beat that picked its pad first and only then noticed
        # it had arrived would hold the stick one capture too long and leave the
        # sweep 6 units past where it started — and the walk home runs ALONG THE
        # FACING, so 6 units of error turns the return leg into a diagonal that
        # never reaches the spawn at all. Measured that way, the circuit missed
        # by four million position units and the take ran to its ceiling.
        head = r.read_u16(W, HEADING)
        if _kill_flash(r):
            self.saw_kill = True
        if p == 0 and self.n > OUT_CAPTURES and self.saw_kill:
            self._next()
        elif p == 1:
            if self.mark is None:
                self.mark = head
            if (self.mark - head) % 256 >= SWEEP:
                self._next()
        elif p == 2 and head == self.open_pose[2]:
            self._next()

        pad = ({0: dict(up=True),       # walk out under the volley
                1: dict(right=True),    # the sweep, taken standing
                2: dict(left=True)}     # ...and swept back, exactly
               .get(self.phase, dict(down=True)))    # 3: walk home

        r.frame_step(STEP, a=self._fire(i), **pad)
        if self.phase >= 3 and _pose(r) == self.open_pose:
            self.done = True


def make_drive():
    return Arena()
