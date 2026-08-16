"""meteor_event — the Mode1 <-> Mode7 cutscene, whole.

THE ENTIRE EVENT IN ONE TAKE, which is the only way this rail can be shown:
its claim is that a Mode-1 side-scrolling level hands over to a Mode-7 scene
and back with a ONE-FRAME CUT and no visible seam, and a still cannot carry a
cut. Measured timeline on this binary, walking right: PLAY from the boot,
FREEZE at frame 120, CAPTURE at 160, the Mode-7 SCENE at 191, RESTORE at 371,
and control back at 372.

The beats a viewer gets, in order:

    walk        the Mode-1 level scrolling under a held Right
    freeze      input gated, the BG still up
    captured    TM = OBJ only — the SAME picture, now made of sprites. If
                those two beats look different the capture's whole claim is
                wrong, and the test asserts them pixel-identical; here they
                are simply consecutive frames of the clip
    approach    the far speck over the frozen ground
    crossover   the plane revealed at the sprite's own apparent size
    grow        growing IN PLACE about the pivot
    glow        the red impact wash at full, the captured sprites untinted
    recede      the meteor gone, the glow receding
    restored    a walkable level again, under the same held Right

THE DRIVE IS ONE HELD DIRECTION, and that is the honest one rather than a
lazy one: the rail gates input for the whole event, so anything else would be
pressing buttons at a cutscene. What makes it state-driven rather than
scheduled is that Right is held only while the ROM reports PLAY — so if the
trigger moves, the walk moves with it instead of the clip photographing an
empty stretch of level.
"""
import json
from pathlib import Path

from tools.record_gallery_clip import STEP
from vendor.mesen_runner import MemoryType

ROOT = Path(__file__).resolve().parent.parent.parent

ROM = "meteor_event"
CAPTURES = 200
WINDOW = 160                    # 8.0 s at 1:1, kept from a 200-capture take
WINDOW_START = 24               # PINNED, and this rail is why the pin exists.
                                #   densest_window's own answer is 24 — but
                                #   starts 24..40 all score exactly 28881
                                #   (the dead opening contributes nothing to
                                #   any of them), so the argmax sits on a
                                #   17-wide tie and one changed sample moves
                                #   it. Measured over 14 recordings: 3 distinct
                                #   files. The same take unwindowed: one file,
                                #   12 times out of 12. So the tool's own
                                #   choice is recorded here rather than
                                #   re-derived on every run.
SETTLE = 96                     # EMULATED frames, and NOT just the fade-in.
                                #   level.asm clamps `camera = worldx -
                                #   MET_PLAYER_SCRN_X` at 0 and draws the
                                #   player at a FIXED screen x, so for the
                                #   first ~96 world px the picture is pixel-
                                #   identical frame to frame even though the
                                #   walk is running. Measured: 24 captures of
                                #   a frozen opening at SETTLE=24. Starting
                                #   here opens the clip on a moving level.

W = MemoryType.SnesWorkRam
_J = json.loads((ROOT / "build" / "met" / "symbol_map.json").read_text())
ST = next(p for p in _J["globals"] if p["sym"] == "US_G_STATE")["start"]
PLAY = 0                        # the phase machine's own enum


def _drive(r, i):
    b = r.read_bytes(W, ST, 2)
    playing = (b[0] | (b[1] << 8)) == PLAY
    return r.frame_step(STEP, right=playing)


def make_drive():
    return _drive
