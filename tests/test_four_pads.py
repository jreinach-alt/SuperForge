"""four_pads — four players, four pads, one screen (docs/102 FP-1..FP-3).

Lockstep-native: `Machine` only, every read from a parked exact frame.

WHAT THE DEMO CLAIMS, and the output region each claim is read from:

  * the art arrived — OBJ VRAM and CGRAM 128..191 against the blobs, byte for
    byte (FP-3, the destination regions);
  * each player's token moves with ITS OWN pad and no other — both directions
    on both axes, and the play-field clamp holds (FP-1, the OAM low table);
  * the lamps say which pads are connected and which are pressed — players
    3-4 have no token and no lamp without the adapter; a lamp shows the LIT
    tile only while its pad holds a button (FP-2, OAM tile / Y bytes);
  * A flips a token once per PRESS, not per held frame — the demo's use of the
    edge query `pad_btnp` (OAM attr bit 6);
  * and the composited picture: each token and lamp is drawn in its player's
    colour over the backdrop (screenshot pixels).

`advance` has a one-frame presentation lag: a press moves WRAM in the same
call and OAM one advance later (the park point). Every OAM read below follows
an idle `advance(1)` for that reason.
"""
import json
import sys
from pathlib import Path

import pytest

from conftest import run_make

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine, MemoryType  # noqa: E402
import mesen_runner as mr  # noqa: E402

BUILD = SUPERFORGE / "build"
ROM = BUILD / "four_pads.sfc"
ASSETS = BUILD / "assets"
_JMAP = json.loads((SUPERFORGE / "build" / "fp" / "symbol_map.json").read_text())

W, V, C, O = (MemoryType.SnesWorkRam, MemoryType.SnesVideoRam,
              MemoryType.SnesCgRam, MemoryType.SnesSpriteRam)


def _sym(name, scene="play"):
    pool = _JMAP["scenes"][scene]["placements"] if scene else _JMAP["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} is not in the emitted map")


V_OBJ = _sym("ES_V_OBJ_CHR")["start"]
C_OBJ = _sym("ES_C_OBJ_PAL")["start"]
OAM_TOKENS = _sym("ES_O_TOKENS")["start"]
OAM_LAMPS = _sym("ES_O_LAMPS")["start"]
OAM_HI_BASE = 512

# The rail's vocabulary, from game/four_pads/fp.inc (written out here so the
# assertions are not a function of the source they test).
HOME = [(64, 80), (184, 80), (64, 160), (184, 160)]
SPEED = 2                                   # px per NTSC frame
X_MIN, X_MAX, Y_MIN, Y_MAX = 8, 240, 40, 200
LAMP_Y, LAMP_X = 16, [40, 96, 152, 208]
TILE_TOKEN, TILE_RING, TILE_LIT = 0, 1, 2
PARK_Y = 240
ATTR = [0x30 | (p << 1) for p in range(4)]  # priority 3, palette p
FLIP = 0x40
BUTTONS = ["b", "y", "select", "start", "up", "down", "left", "right",
           "a", "x", "l", "r"]

BOOT = 60


@pytest.fixture(scope="module", autouse=True)
def rom_built():
    r = run_make("four_pads")
    assert r.returncode == 0, f"make four_pads failed:\n{r.stdout}\n{r.stderr}"
    yield


@pytest.fixture(autouse=True)
def hand_back_the_core():
    yield
    Machine.close_current()


@pytest.fixture
def tap():
    return Machine(str(ROM), port2=mr.PORT2_MULTITAP).advance(BOOT)


@pytest.fixture
def plain():
    return Machine(str(ROM)).advance(BOOT)


def _oam(m, slot):
    x, y, tile, attr = m.read_bytes(O, slot * 4, 4)
    hi = (m.read_byte(O, OAM_HI_BASE + slot // 4) >> ((slot % 4) * 2)) & 3
    return {"x": x, "y": y, "tile": tile, "attr": attr, "x9": hi & 1,
            "large": hi >> 1}


def _token(m, p):
    return _oam(m, OAM_TOKENS + p)


def _lamp(m, p):
    return _oam(m, OAM_LAMPS + p)


def _xy(m):
    return [(_token(m, p)["x"], _token(m, p)["y"]) for p in range(4)]


def _hold(m, player, frames, **buttons):
    m.advance(frames, **{f"pad{player + 1}": buttons})
    m.advance(1)                                # the OAM presentation lag


# =============================================================================
# FP-3 — the uploads, at their destinations
# =============================================================================
def test_the_obj_tiles_are_the_blob_in_obj_vram(tap):
    want = (ASSETS / "fp_obj_chr.bin").read_bytes()
    assert len(want) == 96 and _sym("ES_V_OBJ_CHR")["size"] * 2 == 96
    got = tap.read_bytes(V, V_OBJ * 2, len(want))
    assert got == want, f"OBJ CHR differs:\n  got  {got.hex()}\n  want {want.hex()}"


def test_the_four_obj_palettes_are_the_blob_in_cgram(tap):
    want = (ASSETS / "fp_obj_pal.bin").read_bytes()
    assert len(want) == 128 and C_OBJ == 128
    assert tap.read_bytes(C, C_OBJ * 2, len(want)) == want


# =============================================================================
# FP-2 — connection: who is on screen, with and without the adapter
# =============================================================================
def test_with_the_adapter_all_four_players_have_a_token_and_a_lamp(tap):
    tap.advance(1)
    for p in range(4):
        t, l = _token(tap, p), _lamp(tap, p)
        assert (t["x"], t["y"], t["tile"], t["attr"]) == (*HOME[p], TILE_TOKEN, ATTR[p]), t
        assert (l["x"], l["y"], l["tile"], l["attr"]) == (LAMP_X[p], LAMP_Y, TILE_RING, ATTR[p]), l
        assert (t["x9"], t["large"], l["x9"], l["large"]) == (0, 0, 0, 0)


def test_without_the_adapter_players_3_and_4_are_absent(plain):
    plain.advance(1)
    for p in (0, 1):
        assert (_token(plain, p)["x"], _token(plain, p)["y"]) == HOME[p]
        assert _lamp(plain, p)["y"] == LAMP_Y
    for p in (2, 3):
        assert _token(plain, p)["y"] == PARK_Y, f"player {p + 1}'s token is drawn"
        assert _lamp(plain, p)["y"] == PARK_Y, f"player {p + 1}'s lamp is drawn"
    # ...and their pads, latched, change nothing on screen
    before = plain.read_bytes(O, 0, 32)
    plain.advance(10, pad3={"right": True, "a": True},
                  pad4={"down": True, "b": True})
    plain.advance(1)
    assert plain.read_bytes(O, 0, 32) == before


# =============================================================================
# FP-1 — each token moves with its own pad, both ways on both axes
# =============================================================================
@pytest.mark.parametrize("player", [0, 1, 2, 3])
def test_each_token_moves_with_its_own_pad_and_no_other(tap, player):
    tap.advance(1)
    start = _xy(tap)
    n = 10
    for button, (dx, dy) in (("right", (1, 0)), ("left", (-1, 0)),
                             ("down", (0, 1)), ("up", (0, -1))):
        before = _xy(tap)
        _hold(tap, player, n, **{button: True})
        after = _xy(tap)
        for p in range(4):
            want = ((before[p][0] + dx * n * SPEED, before[p][1] + dy * n * SPEED)
                    if p == player else before[p])
            assert after[p] == want, (
                f"pad {player + 1} {button}: token {p + 1} at {after[p]}, "
                f"want {want}")
    assert _xy(tap) == start, "the four holds should bring the token home"


def test_the_play_field_clamps_every_edge(tap):
    _hold(tap, 0, 60, left=True, up=True)
    assert _xy(tap)[0] == (X_MIN, Y_MIN)
    _hold(tap, 3, 60, right=True, down=True)
    assert _xy(tap)[3] == (X_MAX, Y_MAX)
    _hold(tap, 3, 5, right=True, down=True)       # pinned, not wrapping
    t = _token(tap, 3)
    assert (t["x"], t["y"], t["x9"]) == (X_MAX, Y_MAX, 0)


# =============================================================================
# FP-2 — pressed: a lamp is LIT while its pad holds any button
# =============================================================================
@pytest.mark.parametrize("player", [0, 1, 2, 3])
def test_a_lamp_lights_for_every_button_of_its_own_pad_only(tap, player):
    for b in BUTTONS:
        tap.advance(2, **{f"pad{player + 1}": {b: True}})
        tap.advance(1, **{f"pad{player + 1}": {b: True}})   # held across the lag
        tiles = [_lamp(tap, p)["tile"] for p in range(4)]
        want = [TILE_LIT if p == player else TILE_RING for p in range(4)]
        assert tiles == want, f"pad {player + 1} '{b}': lamp tiles {tiles}"
        tap.advance(2)
        assert _lamp(tap, player)["tile"] == TILE_RING, f"'{b}' released, still lit"


# =============================================================================
# the edge query, in the demo: A flips a token once per PRESS
# =============================================================================
@pytest.mark.parametrize("player", [0, 1, 2, 3])
def test_a_flips_the_token_once_per_press_not_per_frame(tap, player):
    flips = []
    for held in (12, 1, 7):                       # three presses of different length
        _hold(tap, player, held, a=True)
        tap.advance(2)
        flips.append(_token(tap, player)["attr"] & FLIP)
    assert flips == [FLIP, 0, FLIP], (
        f"player {player + 1}: h-flip after each press {flips} — one toggle "
        f"per press, whatever its length")
    assert [_token(tap, p)["attr"] & FLIP for p in range(4) if p != player] \
        == [0, 0, 0], "another player's token flipped"


# =============================================================================
# the composited picture
# =============================================================================
# Mesen's screenshot of a non-overscan frame puts scanline s at PNG row s + 6,
# and an OBJ at OAM Y = v occupies scanlines v+1 .. v+8 — so its art row r is
# PNG row v + 7 + r; OAM X = h is PNG column h (test_sprite_game's SHOT_DY
# derivation, reused).
SHOT_DY = 6


def _px(img, oam_x, oam_y, col, row):
    """The screenshot pixel showing art (col, row) of the OBJ at (oam_x, oam_y)."""
    return img.getpixel((oam_x + col, oam_y + 1 + SHOT_DY + row))[:3]


def test_the_screen_shows_four_tokens_and_four_lamps_in_their_colours(tap, tmp_path):
    """Every token's body, every lamp's ring, and the ONE lit lamp's white
    core, at the pixels the art puts them, in the colour the player's palette
    gives them — the composited picture, OBJ over the backdrop."""
    from PIL import Image
    tap.advance(1, pad2={"x": True})
    tap.advance(1, pad2={"x": True})              # held across the OAM lag
    img = Image.open(tap.screenshot(str(tmp_path / "fp.png"))).convert("RGB")
    assert img.size[0] == 256, img.size
    pal = (ASSETS / "fp_obj_pal.bin").read_bytes()

    def colour(p, idx):                           # BGR555 -> 8-bit RGB
        o = (p * 16 + idx) * 2
        w = pal[o] | (pal[o + 1] << 8)
        return tuple(((c << 3) | (c >> 2))
                     for c in (w & 31, (w >> 5) & 31, (w >> 10) & 31))

    backdrop = _px(img, 0, 0, 0, 100)             # an empty column
    for p in range(4):
        x, y = HOME[p]
        # token art row 3 is "#XXXXXX#": body from column 1 to 6
        for c in range(1, 7):
            assert _px(img, x, y, c, 3) == colour(p, 1), f"token {p + 1} col {c}"
        assert _px(img, x, y, 0, 3) == colour(p, 3), f"token {p + 1} outline"
        # lamp row 3: ring "#X....X#" idle, lit "#XooooX#"
        lx = LAMP_X[p]
        assert _px(img, lx, LAMP_Y, 1, 3) == colour(p, 1), f"lamp {p + 1} ring"
        centre = _px(img, lx, LAMP_Y, 3, 3)
        if p == 1:
            assert centre == colour(p, 2), f"lamp 2 is held but not lit: {centre}"
        else:
            assert centre == backdrop, f"lamp {p + 1} idle but its centre is {centre}"
