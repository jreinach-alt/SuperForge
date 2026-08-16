"""brawler — two knights out of TWO OBJ name tables, proven in pixels.

LOCKSTEP-NATIVE: `Machine` only, no MesenRunner
import, no wall-clock surface. Every boot is `Machine(rom).advance(N)` — an
absolute frame by construction — and every scripted drive is a fixed
per-frame input list, so the whole trajectory is a pure function of the
replay triple.

WHAT THIS RAIL IS (its done-condition list, templates/brawler/main.asm:70-76):

    - boots; floor + both knights + "HP 3  FOE 3  WINS 0"-style HUD render
    - Arthur walks all 4 directions inside the arena, faces his travel
      direction (OAM H-flip), and ANIMATES (idle<->run tile cycling)
    - Mordred walks toward Arthur and faces him
    - a swing in range: FOE hp ticks down on the HUD; 3 hits -> WINS +1,
      respawn; contact: HP ticks down + knockback; HP 0 -> GAME OVER freeze

THE HEADLINE PROPERTY, AND HOW IT IS PROVEN. Arthur fills OBJ
name table 0 (tiles 0..255) exactly, so Mordred lives at the SECOND base,
reached through OBSEL's name-select gap and the OAM attribute's 9th tile bit.
Asserting "the attribute bit is set" would be indirect evidence of the worst
kind: the bit is set in a byte this repo wrote, and it says nothing about
whether the PPU fetched from the right place. So the proof is a PIXEL
PREDICTION — `_predict_sprite` decodes the CHR blob and the palette blob in
Python and renders what a 32x32 sprite at that OAM entry MUST look like, and
the test compares it to the screenshot. If OBSEL's gap field were wrong, or
the name bit clear, or the two claims collapsed onto one base, the PPU would
fetch Arthur's tiles (or the hole between the tables) and the comparison
would fail. Both knights are predicted in the SAME frame, from their own
blob and their own palette, which is what "two name tables at once" means.

THE ART IS GROUND-TRUTHED TWICE, per the asset-import rule:
  * every blob is compared to the vendored `ref_*.inc` fixtures — png2snes
    output for the same PNGs, an INDEPENDENT derivation (shared code with
    tools/gen_brawler_assets.py: none);
  * every blob is then compared to the DESTINATION region it was uploaded to
    (VRAM words, CGRAM words), because a converter that is right and an
    upload that silently no-ops look identical from the source side — a
    `[sprites]` section that was never parsed cost exactly that once.

FRAME ACCOUNTING (measured here, the convention every rail shares): hardware OAM and the
committed text cells after advance(N) reflect the state after tick N - 1 —
the constant one-commit presentation lag of the park point. OAM is read
BEFORE each screenshot: a parked OAM read and the NEXT shot describe the same
committed frame, while a read AFTER a shot is one commit ahead.

THE HEARTBEAT WORD IS NOT READ HERE. Five sibling rails declare a
free-running `blink` *so that a test can read it* — and that reading is
exactly the proxy-variable move rule 2 forbids. The word ships (it is the
tree's convention) and nothing in this module touches it, because the rail
renders two better liveness signals: the idle animation cycles the OAM tile
byte every eight frames, and the GAME OVER banner pumps one VRAM cell per
frame for nine frames AFTER the freeze begins. The freeze case uses the
second, which is what lets it tell a frozen tick from a dead one without
reading a variable.
"""
import json
import re
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine, MemoryType  # noqa: E402

BUILD = SUPERFORGE / "build"
ROM = BUILD / "brawler.sfc"
ASSETS = BUILD / "assets"
ART = SUPERFORGE / "vendor" / "art"
MAP = json.loads((BUILD / "br" / "symbol_map.json").read_text())

V = MemoryType.SnesVideoRam
C = MemoryType.SnesCgRam
O = MemoryType.SnesSpriteRam


# --- the allocator's answers, read from the emitted map ----------------------
def _sym(name, scene="fight"):
    pool = MAP["scenes"][scene]["placements"] if scene else MAP["globals"]
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


V_ART = _sym("ES_V_BR_ART_CHR")["start"]       # OBJ name table 0, VRAM words
V_MOR = _sym("ES_V_BR_MOR_CHR")["start"]       # OBJ name table 1, VRAM words
V_CHR = _sym("ES_V_BR_CHR")["start"]           # BG1 CHR page
V_MAP = _sym("ES_V_BR_MAP")["start"]           # BG1 tilemap base
V_TEXT = _sym("ES_V_TEXT_MAP")["start"]        # BG3 text map base
C_ART = _sym("ES_C_BR_ART_PAL")["start"]       # OBJ palette 0, CGRAM words
C_MOR = _sym("ES_C_BR_MOR_PAL")["start"]       # OBJ palette 1
C_BG = _sym("ES_C_BR_BG_PAL")["start"]         # BG group 0 (word 0 = backdrop)
O_KNIGHTS = _sym("ES_O_KNIGHTS")["start"]      # Arthur, Mordred, two pads

# The name-select relationship brawler_obj.asm derives and asserts, restated
# here from the SAME emitted symbols so a test failure names the packing.
OBJ_SPAN = V_MOR - V_ART
OBJ_GAP = (OBJ_SPAN >> 12) - 1

# --- the rail's geometry (game/brawler/brawler.inc, re-derived) --------------
WALK, ENEMY_SPEED = 2, 1
ARENA_L, ARENA_R = 8, 216
LANE_TOP, LANE_BOT = 132, 136
SPAWN_P, SPAWN_E = (60, 134), (180, 134)
CONTENT_BOTTOM, SURFACE_TOP = 28, 160
FLOOR_ROW, FLOOR_END = 20, 28
PATCH_W, PATCH_TOP, PATCH_FILL = 8, 1, 2
MAP_W = 32
PARK_Y = 224
ATTACK_LEN, FOE_HP, PLAYER_HP, RESPAWN_T = 16, 3, 3, 90
PRI = 2 << 4
ATTR_ARTHUR, ATTR_MORDRED, HFLIP = PRI, PRI | 2 | 1, 0x40

A, RIGHT, LEFT, DOWN, UP = 1 << 7, 1 << 8, 1 << 9, 1 << 10, 1 << 11

TXT_ATTR = (7 << 10) | (1 << 13)
HUD_ROW = 1
HP_VAL_C, FOE_VAL_C, WINS_VAL_C = 4, 15, 26
HP_LABEL_C, FOE_LABEL_C, WINS_LABEL_C = 1, 11, 21
OVER_ROW, OVER_C, OVER_LEN = 13, 12, 9

BOOT = 90                       # the module's absolute boot frame
# Hardware OAM and the committed text cells after advance(N) reflect the state
# after tick N - 1: the constant one-commit presentation lag of the park point
# (the shared convention). Every incremental-motion expectation below is
# indexed by it; saturated expectations (a clamp) are lag-independent.
OAM_LAG = 1

# --- the picture -------------------------------------------------------------
# Mesen hands back 256x239. The active 224 scanlines start at PNG row 7, so a
# scanline S is PNG row S + 6. BG1 runs VOFS = -1, which puts tilemap line L on
# scanline L + 1 = PNG row L + 7; an OBJ at OAM y Y starts on scanline Y + 1 =
# PNG row Y + 7 (the OBJ +1 scanline rule). BG3 runs VOFS = 0, so its line L is
# on scanline L = PNG row L + 6. All three are re-verified by the boot test.
PIC_Y0 = 7
OBJ_ROW0 = 7                    # PNG row of OAM y 0
BG1_ROW0 = 7                    # PNG row of BG1 tilemap line 0
BG3_ROW0 = 6                    # PNG row of BG3 tilemap line 0
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)


def _rgb(word):
    """BGR555 -> Mesen's 8-bit RGB (5-bit channel c -> (c<<3)|(c>>2))."""
    r, g, b = word & 31, (word >> 5) & 31, (word >> 10) & 31
    return tuple((c << 3) | (c >> 2) for c in (r, g, b))


def _blob(name):
    return (ASSETS / name).read_bytes()


def _words(blob):
    return [blob[i] | (blob[i + 1] << 8) for i in range(0, len(blob), 2)]


# --- the reference fixtures: an INDEPENDENT derivation of the same PNGs -----
def _inc_bytes(text, label):
    m = re.search(rf"^{label}:[ \t]*\n?((?:\s*\.byte .*\n)+)", text, re.M)
    assert m, f"{label} not found in the fixture"
    out = bytearray()
    for line in m.group(1).splitlines():
        for tok in line.split(".byte", 1)[1].split(","):
            out.append(int(tok.strip().lstrip("$"), 16))
    return bytes(out)


def _inc_words(text, label):
    m = re.search(rf"^{label}:\n((?:\s*\.word .*\n)+)", text, re.M)
    assert m, f"{label} not found in the fixture"
    out = []
    for line in m.group(1).splitlines():
        for tok in line.split(".word", 1)[1].split(","):
            out.append(int(tok.strip().lstrip("$"), 16))
    return out


REFERENCE_ARTHUR = (ART / "camelot" / "ref_arthur.inc").read_text()
REFERENCE_MORDRED = (ART / "camelot" / "ref_mordred.inc").read_text()
REFERENCE_TERRAIN = (ART / "four_seasons_tileset" / "ref_terrain.inc").read_text()


# --- 4bpp decoding + the sprite prediction ----------------------------------
def _decode_tile(chunk):
    """32 B SNES 4bpp planar -> 8 rows of 8 palette indices."""
    rows = []
    for y in range(8):
        b0, b1 = chunk[y * 2], chunk[y * 2 + 1]
        b2, b3 = chunk[16 + y * 2], chunk[16 + y * 2 + 1]
        row = []
        for x in range(8):
            bit = 7 - x
            row.append(((b0 >> bit) & 1) | (((b1 >> bit) & 1) << 1)
                       | (((b2 >> bit) & 1) << 2) | (((b3 >> bit) & 1) << 3))
        rows.append(row)
    return rows


def _predict_sprite(chr_blob, pal_words, tile_off, hflip):
    """What a 32x32 OBJ at this entry MUST look like, as 32 rows of RGB|None.

    The PPU reads a 32x32 sprite as a 4x4 block of 8x8 tiles whose ROWS sit
    +16 tile numbers apart within the 256-tile name table — hardware, and the
    reason the blob is laid out on a 16-wide grid (Mesen2 SnesPpu.cpp:739,
    `tileIndex = (row << 4) | ((tileColumn + columnOffset) & 0x0F)`, both
    nibbles wrapping inside the table). Palette index 0 is transparent.
    """
    out = [[None] * 32 for _ in range(32)]
    for ty in range(4):
        for tx in range(4):
            row_nib = ((tile_off >> 4) + ty) & 0x0F
            col_nib = ((tile_off & 0x0F) + tx) & 0x0F
            n = (row_nib << 4) | col_nib
            tile = _decode_tile(chr_blob[n * 32:(n + 1) * 32])
            for y in range(8):
                for x in range(8):
                    idx = tile[y][x]
                    if idx:
                        out[ty * 8 + y][tx * 8 + x] = _rgb(pal_words[idx])
    if hflip:
        out = [list(reversed(r)) for r in out]
    return out


# --- reading the machine -----------------------------------------------------
def _entry(m, slot):
    """One OAM entry as the hardware holds it, X9 and SIZE from the hi table."""
    b = m.read_bytes(O, (O_KNIGHTS + slot) * 4, 4)
    hi = m.read_bytes(O, 512 + (O_KNIGHTS + slot) // 4, 1)[0]
    pos = ((O_KNIGHTS + slot) % 4) * 2
    return {"x": b[0] | (((hi >> pos) & 1) << 8), "y": b[1],
            "tile": b[2], "attr": b[3], "size": (hi >> (pos + 1)) & 1}


def _vram_words(m, word_addr, count):
    b = m.read_bytes(V, word_addr * 2, count * 2)
    return _words(b)


def _cgram_words(m, word_addr, count):
    return _words(m.read_bytes(C, word_addr * 2, count * 2))


def _cell(m, row, col):
    """One BG3 text cell as its ASCII character (glyph 0 is space)."""
    w = _vram_words(m, V_TEXT + row * MAP_W + col, 1)[0]
    return chr((w & 0x3FF) + 0x20)


def _text(m, row, col, n):
    return "".join(_cell(m, row, col + i) for i in range(n))


def _hud(m):
    return (_text(m, HUD_ROW, HP_VAL_C, 4),
            _text(m, HUD_ROW, FOE_VAL_C, 4),
            _text(m, HUD_ROW, WINS_VAL_C, 4))


def _shot(m, name):
    p = f"/tmp/brawler_{name}.png"
    m.take_screenshot(p)
    return Image.open(p).convert("RGB")


def _pad(mask):
    d = {}
    for bit, key in ((A, "a"), (RIGHT, "right"), (LEFT, "left"),
                     (DOWN, "down"), (UP, "up")):
        if mask & bit:
            d[key] = True
    return d


def _groups(seq):
    """Consecutive runs of equal values (itertools.groupby without the import)."""
    out, cur = [], None
    for v in seq:
        if cur is None or v != cur[0]:
            cur = [v]
            out.append(cur)
        else:
            cur.append(v)
    return out


def _swing_script(n, gap=20):
    """`n` swings: one rising-edge A press, then `gap` frames of nothing.

    The gap is what lets the swing run its 16 frames, the hitbox open in its
    4..12 window, and Mordred walk back into range for the next one. Written
    as a fixed script so the trajectory is a pure function of the replay
    triple.
    """
    return ([A] + [0] * gap) * n


def _drive(m, script):
    """Advance one frame per entry of a fixed input script."""
    for mask in script:
        m.advance(1, pad1=_pad(mask))
    return m


# --- fixtures ----------------------------------------------------------------
@pytest.fixture(scope="module")
def boot():
    """The module's hand-back contract, not a shared driving handle."""
    if not ROM.exists():
        pytest.fail(f"{ROM} missing — run `make brawler` first")

    def _boot(frames=BOOT):
        return Machine(str(ROM)).advance(frames)

    yield _boot
    Machine.close_current()


@pytest.fixture
def fresh(boot):
    return boot()


# =============================================================================
# A. the art — an independent source ground truth, then the destination region
# =============================================================================

def test_every_blob_equals_an_independent_conversion():
    """The converter, ground-truthed against a derivation that shares no code.

    `tools/gen_brawler_assets.py` reads the ORIGINAL pack PNGs; `png2snes.py`
    read the same PNGs by a different route and its output is vendored beside
    them. Nothing in this repo produced the fixtures, so agreement is evidence
    rather than a tautology (the asset-import rule — self-validating a
    converter against your own re-rendering of its source is exactly the trap
    sub-rule 7 names).
    """
    assert _blob("br_art_chr.bin") == _inc_bytes(REFERENCE_ARTHUR, "arthur_chr")
    assert _words(_blob("br_art_pal.bin")) == _inc_words(REFERENCE_ARTHUR, "arthur_pal")
    assert _blob("br_mor_chr.bin") == _inc_bytes(REFERENCE_MORDRED, "mordred_chr")
    assert _words(_blob("br_mor_pal.bin")) == _inc_words(REFERENCE_MORDRED, "mordred_pal")
    assert _blob("br_bg_chr.bin") == _inc_bytes(REFERENCE_TERRAIN, "terrain_chr")
    assert _words(_blob("br_bg_pal.bin")) == _inc_words(REFERENCE_TERRAIN, "terrain_pal")
    assert _words(_blob("br_bg_map.bin")) == _inc_words(REFERENCE_TERRAIN, "terrain_map")


def test_animation_tables_are_the_reference_tables_on_a_fixed_stride():
    """The same per-step tile offsets, indexed instead of named.

    The reference emits five separate `.byte` tables and names one at assemble
    time per call site. This build packs them on an 8-byte stride so the
    anim-state word indexes them — so the bytes have to be the SAME bytes, in
    the same order, with the padding never reachable (each table's length ships
    beside it in br_anim_meta and bounds the wrap).
    """
    anim, meta = _blob("br_anim.bin"), _blob("br_anim_meta.bin")
    expect = [
        (_inc_bytes(REFERENCE_ARTHUR, "arthur_anim_idle"), 4, 8),
        (_inc_bytes(REFERENCE_ARTHUR, "arthur_anim_run"), 8, 6),
        (_inc_bytes(REFERENCE_ARTHUR, "arthur_anim_hit"), 4, 4),
        (_inc_bytes(REFERENCE_MORDRED, "mordred_anim_idle"), 4, 8),
        (_inc_bytes(REFERENCE_MORDRED, "mordred_anim_run"), 4, 8),
    ]
    for i, (table, length, rate) in enumerate(expect):
        got = anim[i * 8:i * 8 + 8]
        assert list(got[:len(table)]) == list(table), f"table {i} frames"
        assert all(b == table[0] for b in got[len(table):]), f"table {i} padding"
        assert meta[i * 2] == length, f"table {i} length"
        assert meta[i * 2 + 1] == rate, f"table {i} rate"
    # Mordred's run table is 8 steps stepped at length 4 — a deliberate
    # one-clock choice, not a copying slip.
    assert len(_inc_bytes(REFERENCE_MORDRED, "mordred_anim_run")) == 8
    assert meta[4 * 2] == 4


def test_arthur_reaches_obj_name_table_0_and_mordred_the_second(fresh):
    """The DESTINATION regions, byte for byte — both of them.

    A converter that is right and an upload that silently no-ops look
    identical from the source side. This reads the VRAM words the two claims
    name and requires the blobs to be there, which is also the only way to
    tell "two name tables" from "one claim written twice".
    """
    art, mor = _blob("br_art_chr.bin"), _blob("br_mor_chr.bin")
    assert bytes(fresh.read_bytes(V, V_ART * 2, len(art))) == art
    assert bytes(fresh.read_bytes(V, V_MOR * 2, len(mor))) == mor
    # ...and they are DIFFERENT art at DIFFERENT bases: a build that collapsed
    # the two claims onto one base would pass the two reads above only if the
    # blobs were equal, and they are not.
    assert art[:len(mor)] != mor
    assert V_MOR != V_ART


def test_the_name_select_gap_is_legal_and_the_hole_is_someone_elses(fresh):
    """the spec, as the allocator actually packed it.

    OBSEL reaches tiles 256..511 at `base + (gap + 1) * 0x1000` words with gap
    in 0..3 (Mesen2 SnesPpu.cpp:1902). The ASM derives that gap from the two
    emitted bases and refuses to assemble if it is not whole or not
    expressible; this restates the arithmetic from the map, and then checks
    the thing the ASM cannot: that the 4 K-word hole between the two tables
    was PACKED rather than wasted.
    """
    assert OBJ_SPAN == (OBJ_GAP + 1) << 12, f"span {OBJ_SPAN:#x} is not whole"
    assert 0 <= OBJ_GAP <= 3, f"gap {OBJ_GAP} does not fit OBSEL's two bits"
    assert V_ART % 0x2000 == 0, "name table 0 is not on an OBSEL base step"
    # Arthur's blob fills his table exactly — which is WHY there is a second.
    assert len(_blob("br_art_chr.bin")) // 2 == 0x1000
    # The hole: name table 0 ends at V_ART + 0x1000 and table 1 starts at
    # V_MOR. Something else must live in between, or the gap is dead space.
    hole = (V_ART + 0x1000, V_MOR)
    assert hole[1] > hole[0]
    occupants = [p for p in MAP["scenes"]["fight"]["placements"] + MAP["globals"]
                 if p.get("class") == "vram" and hole[0] <= p["start"] < hole[1]]
    assert occupants, f"the {hole[1]-hole[0]:#x}-word name-select hole is empty"


def test_both_obj_palettes_reach_their_claimed_cgram_words(fresh):
    """Two claims, two CGADDs, two blobs — and OBJ palettes start at 128."""
    assert C_ART == 128 and C_MOR == 144
    assert _cgram_words(fresh, C_ART, 16) == _words(_blob("br_art_pal.bin"))
    assert _cgram_words(fresh, C_MOR, 16) == _words(_blob("br_mor_pal.bin"))
    # The two knights do not share a palette: that is what makes the second
    # name table legible on screen rather than merely correct in VRAM.
    assert _cgram_words(fresh, C_ART, 16) != _cgram_words(fresh, C_MOR, 16)


def test_terrain_chr_and_palette_reach_their_claimed_regions(fresh):
    """The floor's destination regions, including CGRAM word 0 (the backdrop)."""
    chr_blob = _blob("br_bg_chr.bin")
    assert bytes(fresh.read_bytes(V, V_CHR * 2, len(chr_blob))) == chr_blob
    assert _cgram_words(fresh, C_BG, 16) == _words(_blob("br_bg_pal.bin"))
    assert C_BG == 0, "the BG group 0 claim must own CGRAM word 0"
    assert _cgram_words(fresh, 0, 1)[0] == 0, "the backdrop is not black"


# =============================================================================
# B. THE HEADLINE — two name tables, live in one frame, proven in pixels
# =============================================================================

def _crop(img, x, y, w=32, h=32):
    return [[img.getpixel((x + dx, y + dy)) for dx in range(w)] for dy in range(h)]


def _compare(pred, got, label):
    """Every OPAQUE predicted pixel must be on screen where it was predicted.

    Transparent predicted pixels are skipped: what shows through them is the
    floor or the backdrop, which other tests own.
    """
    checked = mismatched = 0
    first = None
    for dy in range(32):
        for dx in range(32):
            want = pred[dy][dx]
            if want is None:
                continue
            checked += 1
            if got[dy][dx] != want:
                mismatched += 1
                if first is None:
                    first = (dx, dy, want, got[dy][dx])
    # A knight's silhouette inside its 32x32 box is 164 (Arthur, idle step 3)
    # to 192 (Mordred, run step 3) opaque pixels — measured. The floor is a
    # guard against comparing an empty prediction and calling it a match.
    assert checked > 120, f"{label}: only {checked} opaque pixels — wrong frame?"
    assert mismatched == 0, (
        f"{label}: {mismatched}/{checked} pixels wrong, first at "
        f"{first[:2]} want {first[2]} got {first[3]}")
    return checked


def test_both_knights_draw_from_their_own_name_table_in_one_frame(fresh):
    """the spec, as pixels — the reason this rail was sequenced last.

    Arthur's OAM entry names a tile with the attribute's name bit CLEAR, so
    the PPU must fetch it from `V_ART`; Mordred's names the SAME 8-bit tile
    field with the bit SET, so the PPU must add OBSEL's name-select gap and
    fetch from `V_MOR`. Both are predicted from their own blob and their own
    palette and both must match IN THE SAME FRAME.

    The last assertion is the one that makes this sensitive rather than
    decorative: with the name bit clear, Mordred's tile byte would address
    ARTHUR's table, and that prediction must NOT match what is on screen.
    """
    art, mor = _entry(fresh, 0), _entry(fresh, 1)
    img = _shot(fresh, "name_tables")
    assert art["size"] == 1 and mor["size"] == 1, "both knights are the large half"
    assert art["attr"] & 1 == 0, "Arthur must NOT carry the name bit"
    assert mor["attr"] & 1 == 1, "Mordred must carry the name bit"
    assert (art["attr"] >> 1) & 7 == 0 and (mor["attr"] >> 1) & 7 == 1

    art_pal = _words(_blob("br_art_pal.bin"))
    mor_pal = _words(_blob("br_mor_pal.bin"))
    a_pred = _predict_sprite(_blob("br_art_chr.bin"), art_pal,
                             art["tile"], art["attr"] & HFLIP)
    m_pred = _predict_sprite(_blob("br_mor_chr.bin"), mor_pal,
                             mor["tile"], mor["attr"] & HFLIP)
    _compare(a_pred, _crop(img, art["x"], art["y"] + OBJ_ROW0), "arthur")
    _compare(m_pred, _crop(img, mor["x"], mor["y"] + OBJ_ROW0), "mordred")

    # The counterfactual: the same tile byte read out of the WRONG table.
    wrong = _predict_sprite(_blob("br_art_chr.bin"), mor_pal,
                            mor["tile"], mor["attr"] & HFLIP)
    got = _crop(img, mor["x"], mor["y"] + OBJ_ROW0)
    same = sum(1 for dy in range(32) for dx in range(32)
               if wrong[dy][dx] is not None and got[dy][dx] == wrong[dy][dx])
    total = sum(1 for r in wrong for p in r if p is not None)
    assert not (total and same == total), (
        "Mordred's pixels also match name table 0 — the name-select gap is "
        "not routing him anywhere")


def test_the_parked_knight_leaves_no_pixels_on_screen(fresh):
    """PARK_Y = 224, not oam_park_all's 240 — and the difference is visible.

    OAM y wraps mod 256, so a 32-tall sprite parked at 240 shows rows 16..31
    on screen lines 0..15. The reference hit that and left the note. This drives
    Mordred to a KO, waits for the park, and requires NO pixel anywhere in the
    frame to be one of his palette's colours (they are disjoint from Arthur's
    and from the floor's, asserted here rather than assumed).
    """
    m = fresh
    _drive(m, _swing_script(3))
    assert _hud(m)[2] == "0001", "three swings did not bank the win"
    mor = _entry(m, 1)
    assert mor["y"] == PARK_Y, f"parked at {mor['y']}, not {PARK_Y}"
    img = _shot(m, "parked")

    mor_pal = _words(_blob("br_mor_pal.bin"))
    art_pal = _words(_blob("br_art_pal.bin"))
    bg_pal = _words(_blob("br_bg_pal.bin"))
    his = {_rgb(w) for w in mor_pal[1:8]} - {_rgb(w) for w in art_pal[1:9]} \
        - {_rgb(w) for w in bg_pal} - {WHITE, BLACK}
    assert len(his) >= 2, "Mordred's palette is not distinguishable enough to test"
    seen = [(x, y) for y in range(img.size[1]) for x in range(img.size[0])
            if img.getpixel((x, y)) in his]
    assert not seen, f"the parked knight is on screen at {seen[:4]}"
    # ...and the specific wrap this park value exists to avoid: a 32-tall
    # sprite at 240 puts its rows 16..31 on screen lines 0..15. The band above
    # the HUD's own first line is the part of that no other layer can occupy.
    band = [(x, y) for y in range(PIC_Y0, BG3_ROW0 + HUD_ROW * 8)
            for x in range(img.size[0]) if img.getpixel((x, y)) != BLACK]
    assert not band, f"something wrapped onto the top scanlines at {band[:4]}"


# =============================================================================
# C. the floor and the HUD — the scene's two static surfaces
# =============================================================================

def test_the_tilemap_tiles_the_patch_and_blanks_everything_else(fresh):
    """The floor's 1,024 cells, predicted from the patch blob.

    The reference builds this with two nested `mset` loops — patch row 1 across
    the surface row, patch row 2 down the body, `col mod 8` across — and
    inherits a cleared shadow above and below. Power-on VRAM is random here
    (rule 5), so this build writes the blank rows explicitly, and this reads
    every word back.
    """
    patch = _words(_blob("br_bg_map.bin"))
    got = _vram_words(fresh, V_MAP, MAP_W * MAP_W)
    want = []
    for row in range(MAP_W):
        for col in range(MAP_W):
            if row < FLOOR_ROW or row >= FLOOR_END:
                want.append(0)
            else:
                prow = PATCH_TOP if row == FLOOR_ROW else PATCH_FILL
                want.append(patch[prow * PATCH_W + (col % PATCH_W)])
    assert got == want
    # The two patch rows are DIFFERENT art — grass tops over dirt fill. A
    # build that picked one row for both would satisfy a "the floor is not
    # blank" test and lose the surface.
    assert (patch[PATCH_TOP * PATCH_W:(PATCH_TOP + 1) * PATCH_W]
            != patch[PATCH_FILL * PATCH_W:(PATCH_FILL + 1) * PATCH_W])


def test_the_floor_starts_exactly_at_the_surface_the_lane_band_anchors_to(fresh):
    """The pixel identity the whole rail's geometry hangs off.

    BR_LANE_TOP + BR_CONTENT_BOTTOM = BR_SURFACE_TOP = tilemap row 20 x 8. If
    BG1's VOFS pin were off by one, or the floor row moved, the knights' feet
    would hang in the air or sink — which is measurable on screen, and is what
    this checks. So: the scanline above the surface is backdrop everywhere,
    and the surface scanline itself is not.
    """
    img = _shot(fresh, "floor")
    above = BG1_ROW0 + SURFACE_TOP - 1
    at = BG1_ROW0 + SURFACE_TOP
    # x 128..255 is clear of both knights at boot (they spawn at 60 and 180 —
    # and by this frame Mordred has closed to ~92), so only the floor is here.
    assert all(img.getpixel((x, above)) == BLACK for x in range(200, 256)), \
        "something renders on the scanline above the floor's surface"
    assert all(img.getpixel((x, at)) != BLACK for x in range(200, 256)), \
        "the floor's surface scanline is empty"
    # ...and it runs to the bottom of the ACTIVE display. Mesen hands back
    # 256x239; the 224 active scanlines are PNG rows 7..230 and the rest is
    # border, so the last floor row is the last active one, not the last PNG
    # one (the floor's own rows 20..27 are y 160..223 = PNG 167..230).
    last_active = PIC_Y0 + 223
    assert (FLOOR_END - 1) * 8 + 7 + BG1_ROW0 == last_active
    assert all(img.getpixel((x, last_active)) != BLACK for x in range(200, 256))


def test_the_hud_labels_and_boot_counters_are_on_bg3(fresh):
    """The three labels and their three counters, read as glyphs from VRAM."""
    assert _text(fresh, HUD_ROW, HP_LABEL_C, 2) == "HP"
    assert _text(fresh, HUD_ROW, FOE_LABEL_C, 3) == "FOE"
    assert _text(fresh, HUD_ROW, WINS_LABEL_C, 4) == "WINS"
    assert _hud(fresh) == ("%04X" % PLAYER_HP, "%04X" % FOE_HP, "0000")
    # The cells carry the text palette + priority attr, not bare tile ids —
    # a glyph in palette 0 would render in the floor's colours.
    w = _vram_words(fresh, V_TEXT + HUD_ROW * MAP_W + HP_LABEL_C, 1)[0]
    assert w & ~0x3FF == TXT_ATTR


def test_the_hud_renders_white_where_its_cells_say(fresh):
    """...and the picture agrees: glyph ink is CGRAM word 31, pure white.

    The scroll_run catch in this rail's shape: the font's strokes
    author colour index 3, so a scene that wrote only the "obvious" two text
    palette words leaves ink on power-on RNG.
    """
    assert _cgram_words(fresh, 28, 4) == [0, 0x2952, 0x56B5, 0x7FFF]
    img = _shot(fresh, "hud")
    rows = range(BG3_ROW0 + HUD_ROW * 8, BG3_ROW0 + HUD_ROW * 8 + 8)
    cols = range(HP_LABEL_C * 8, (HP_LABEL_C + 2) * 8)
    ink = [(x, y) for y in rows for x in cols if img.getpixel((x, y)) == WHITE]
    assert len(ink) > 20, f"the HP label has {len(ink)} white pixels"


# =============================================================================
# D. movement, facing and animation — every transition, both directions
# =============================================================================

def test_walking_right_then_back_left_moves_and_clamps_both_ends(fresh):
    """All four horizontal transitions: right, the right clamp, left, the left
    clamp — and the idle in between. A single-axis drive is the recorded
    failure class , and this rail's clamps are asymmetric in the
    ASM (`bcc` vs `bcs`), so one direction proves nothing about the other.
    """
    m = fresh
    x0 = _entry(m, 0)["x"]
    assert x0 == SPAWN_P[0]
    # Walk AWAY from Mordred first: he spawns to Arthur's right and closes at
    # 1 px/frame, so the only contact-free window for an incremental-motion
    # assertion is the leftward one. (Walking right into him is a knockback,
    # which the contact test owns.)
    _drive(m, [LEFT] * 10)
    assert _entry(m, 0)["x"] == x0 - (10 - OAM_LAG) * WALK
    # Idle: the last scripted step commits (the lag resolving), and then the
    # position stops moving — which is the transition a walk-only drive never
    # exercises, and the reason the settled value is one step further left.
    # The idle window is deliberately SHORT: Mordred closes at 1 px/frame and
    # a longer stand-still would be a knockback, not a drift (that is the
    # contact test's subject, and it would read here as a false failure).
    _drive(m, [0] * 3)
    settled = x0 - 10 * WALK
    assert _entry(m, 0)["x"] == settled
    _drive(m, [0] * 3)
    assert _entry(m, 0)["x"] == settled, "he drifts while idle"
    # Both clamps, in one live game. The drive lengths are MEASURED rather
    # than generous: Mordred lands contacts en route (that is the rail), and
    # an over-long drive would reach HP 0 and freeze — at which point a clamp
    # assertion measures a frozen frame instead of a clamp. The HP guard below
    # is what makes the difference visible instead of silent.
    _drive(m, [RIGHT] * 115)
    assert _entry(m, 0)["x"] == ARENA_R, "the right clamp did not hold"
    _drive(m, [LEFT] * 145)
    assert _entry(m, 0)["x"] == ARENA_L, "the left clamp did not hold"
    assert _hud(m)[0] != "0000", "the game froze — the clamps above proved nothing"


def test_walking_up_and_down_clamps_to_the_lane_band(fresh):
    """The vertical axis, both directions, both clamps.

    The band is in CONTENT terms: the drawn feet (y + 28) span the surface top
    to 4 px below it. Asserted as the identity the .inc derives it from, so a
    test failure names which end moved.
    """
    m = fresh
    assert _entry(m, 0)["y"] == SPAWN_P[1]
    _drive(m, [UP] * 20)
    assert _entry(m, 0)["y"] == LANE_TOP
    assert LANE_TOP + CONTENT_BOTTOM == SURFACE_TOP, "feet no longer on the surface"
    _drive(m, [DOWN] * 20)
    assert _entry(m, 0)["y"] == LANE_BOT
    assert LANE_BOT + CONTENT_BOTTOM == SURFACE_TOP + 4
    _drive(m, [UP] * 3)                          # back off the clamp again
    assert _entry(m, 0)["y"] == LANE_BOT - (3 - OAM_LAG) * WALK


def test_facing_follows_travel_and_the_hardware_mirrors_the_art(fresh):
    """The H-flip idiom, as pixels.

    Only the right-facing frames are stored; walking left sets OAM attribute
    bit 6 and the PPU mirrors the whole sprite. Asserting the BIT would be
    indirect evidence — this predicts the MIRRORED art and matches it against
    the screen, and then requires the unmirrored prediction to disagree.
    """
    m = fresh
    _drive(m, [RIGHT] * 12)
    right = _entry(m, 0)
    img_r = _shot(m, "face_right")
    assert right["attr"] & HFLIP == 0
    _drive(m, [LEFT] * 12)
    left = _entry(m, 0)
    img_l = _shot(m, "face_left")
    assert left["attr"] & HFLIP == HFLIP, "walking left did not set the flip"

    chr_blob, pal = _blob("br_art_chr.bin"), _words(_blob("br_art_pal.bin"))
    _compare(_predict_sprite(chr_blob, pal, right["tile"], 0),
             _crop(img_r, right["x"], right["y"] + OBJ_ROW0), "facing right")
    _compare(_predict_sprite(chr_blob, pal, left["tile"], HFLIP),
             _crop(img_l, left["x"], left["y"] + OBJ_ROW0), "facing left")
    # The counterfactual: the SAME tile drawn unmirrored is a different
    # picture, so the match above is the flip and not a coincidence.
    unflipped = _predict_sprite(chr_blob, pal, left["tile"], 0)
    got = _crop(img_l, left["x"], left["y"] + OBJ_ROW0)
    same = sum(1 for dy in range(32) for dx in range(32)
               if unflipped[dy][dx] is not None and got[dy][dx] == unflipped[dy][dx])
    total = sum(1 for r in unflipped for p in r if p is not None)
    assert same != total, "the left-facing sprite is not actually mirrored"


def test_idle_and_run_cycle_their_own_tables_and_reset_on_the_change(fresh):
    """The rail's stated animation lesson, read off the OAM tile byte.

    Idle is a 4-step table at rate 8; run is an 8-step table at rate 6. The
    clock is reset on EVERY state change, or a 4-step table gets indexed at
    step 7 by a stale 8-step counter and reads past its end — which is why the
    first RUN tile after an idle stretch must be the run table's step 0, not
    whatever index the idle clock had reached.
    """
    m = fresh
    idle_t = _blob("br_anim.bin")[0:4]
    run_t = _blob("br_anim.bin")[8:16]
    # ---- idle: four distinct steps, each held 8 frames -------------------
    seen = []
    for _ in range(32):
        _drive(m, [0])
        seen.append(_entry(m, 0)["tile"])
    assert set(seen) == set(idle_t), f"idle cycled {sorted(set(seen))}"
    runs = [len(list(g)) for g in _groups(seen)]
    assert all(n == 8 for n in runs[1:-1]), f"idle step lengths {runs}"
    # ---- the transition: run starts at step 0 ----------------------------
    # Two frames, not one: the committed OAM lags the tick by one, so a single
    # frame still shows the last IDLE step.
    _drive(m, [RIGHT])
    assert _entry(m, 0)["tile"] in idle_t, "the lag convention moved"
    _drive(m, [RIGHT])
    assert _entry(m, 0)["tile"] == run_t[0], "the run table did not restart"
    seen = []
    for _ in range(48):
        _drive(m, [RIGHT])
        seen.append(_entry(m, 0)["tile"])
    assert set(seen) == set(run_t), f"run cycled {sorted(set(seen))}"
    runs = [len(list(g)) for g in _groups(seen)]
    assert all(n == 6 for n in runs[1:-1]), f"run step lengths {runs}"
    # ---- and back: idle restarts at ITS step 0 ---------------------------
    _drive(m, [0] * 2)
    assert _entry(m, 0)["tile"] == idle_t[0], "the idle table did not restart"


def test_mordred_closes_on_the_player_and_faces_him(fresh):
    """The chase, driven in BOTH directions by moving the player past him.

    He walks one pixel per frame toward the player on each axis and his facing
    is recomputed from the sign of the difference — so putting the player on
    his other side must flip his OAM attribute and reverse his travel.
    """
    m = fresh
    a0, m0 = _entry(m, 0), _entry(m, 1)
    assert m0["x"] < SPAWN_E[0], "he has not started closing"
    assert m0["x"] > a0["x"] and m0["attr"] & HFLIP, "he should face left at him"
    before = _entry(m, 1)["x"]
    _drive(m, [0] * 10)
    assert _entry(m, 1)["x"] == before - 10 * ENEMY_SPEED
    # Put Arthur on his RIGHT: the chase must reverse and so must the facing.
    _drive(m, [RIGHT] * 120)
    assert _entry(m, 0)["x"] == ARENA_R
    right_of_him = _entry(m, 1)
    assert right_of_him["x"] < _entry(m, 0)["x"]
    assert right_of_him["attr"] & HFLIP == 0, "he did not turn to face right"
    now = _entry(m, 1)["x"]
    _drive(m, [0] * 10)
    assert _entry(m, 1)["x"] == now + 10 * ENEMY_SPEED, "he did not reverse"


# =============================================================================
# E. combat — the timed hitbox, the latch, the round, and the freeze
# =============================================================================

def test_a_swing_in_range_ticks_the_foe_counter(fresh):
    """One landed swing, read off the HUD cells it reprints."""
    m = fresh
    assert _hud(m)[1] == "%04X" % FOE_HP
    _drive(m, _swing_script(1))
    assert _hud(m)[1] == "%04X" % (FOE_HP - 1)


def test_a_swing_lands_at_most_one_hit_however_long_it_overlaps(fresh):
    """The latch — the half of "active frames" that a window alone is not.

    A is HELD for the whole swing while Mordred stands inside the hitbox, so
    the box overlaps on every live frame of the window. Exactly one point of
    FOE may come off: `ahit` is set by the first overlap and only cleared by
    the NEXT rising edge.
    """
    m = fresh
    _drive(m, [0] * 20)                          # let him walk into range
    before = _hud(m)[1]
    _drive(m, [A] * (ATTACK_LEN + 4))            # held across the whole swing
    assert _hud(m)[1] == "%04X" % (int(before, 16) - 1), "the latch let through more than one hit"
    # ...and the swing is over: the same held button starts nothing new,
    # because btnp is a rising edge and A never went up.
    _drive(m, [A] * 40)
    assert _hud(m)[1] == "%04X" % (int(before, 16) - 1), "a held button re-swung"


def test_a_swing_facing_away_lands_nothing(fresh):
    """The hitbox is placed IN FRONT of Arthur — so facing decides.

    Same swing, same distance, opposite facing: the box moves to his other
    side and the overlap disappears. That is the placement half of the
    pattern, and it is invisible to any test that only ever swings toward the
    enemy (the single-axis failure class, one axis being "which way I face").
    """
    m = fresh
    _drive(m, [0] * 20)
    assert _entry(m, 1)["x"] > _entry(m, 0)["x"], "he is not on Arthur's right"
    before = _hud(m)[1]
    _drive(m, [LEFT])                            # turn away without moving far
    assert _entry(m, 0)["attr"] & HFLIP == 0     # (the lag: not committed yet)
    _drive(m, [LEFT])
    assert _entry(m, 0)["attr"] & HFLIP == HFLIP, "he did not turn"
    _drive(m, [A] + [0] * ATTACK_LEN)
    assert _hud(m)[1] == before, "a swing facing away still landed"
    # ...and turning back lands it, so the miss above was the FACING and not
    # the distance drifting out of range.
    _drive(m, [RIGHT] * 2)
    _drive(m, [A] + [0] * ATTACK_LEN)
    assert _hud(m)[1] == "%04X" % (int(before, 16) - 1)


def test_three_hits_bank_a_win_and_respawn_him_at_full_health(fresh):
    """The whole round: FOE 3->2->1->0, WINS +1, park, respawn, FOE back to 3."""
    m = fresh
    seen = []
    for _ in range(FOE_HP):
        _drive(m, _swing_script(1))
        seen.append(_hud(m)[1])
    assert seen == ["0002", "0001", "0000"], f"FOE ticked {seen}"
    assert _hud(m)[2] == "0001", "the win was not banked"
    assert _entry(m, 1)["y"] == PARK_Y, "he did not park while respawning"
    # The respawn: at the arena's right edge, at the spawn lane, full health.
    _drive(m, [0] * (RESPAWN_T + 4))
    back = _entry(m, 1)
    assert back["x"] == ARENA_R and back["y"] == SPAWN_E[1], f"respawned at {back}"
    assert _hud(m)[1] == "%04X" % FOE_HP, "he came back damaged"
    assert _hud(m)[2] == "0001", "the win did not stick"


def test_contact_ticks_hp_and_knocks_arthur_away(fresh):
    """Walking into him costs a point and SHOVES Arthur, in OAM pixels.

    The contact frame is found rather than guessed — the drive steps one frame
    at a time until the HP cell changes — so the knockback displacement and
    the i-frame window are both measured from it. The knockback direction is
    computed from the sign of the difference; the spawn geometry reaches the
    "he is on my right, shove me left" arm, which is the one `bcc kb_left`
    takes.
    """
    m = fresh
    assert _hud(m)[0] == "%04X" % PLAYER_HP
    assert _entry(m, 1)["x"] > _entry(m, 0)["x"], "he is to Arthur's right at boot"
    prev_x, hit_at = _entry(m, 0)["x"], None
    for f in range(60):
        _drive(m, [RIGHT])
        if _hud(m)[0] != "%04X" % PLAYER_HP:
            hit_at = f
            break
        prev_x = _entry(m, 0)["x"]
    assert hit_at is not None, "he never landed a contact"
    assert _hud(m)[0] == "%04X" % (PLAYER_HP - 1), "contact cost the wrong amount"
    # Walking right adds +WALK; the shove subtracts BR_KNOCKBACK. The commit
    # lag means the knockback shows one frame after the HP cell, so step once.
    _drive(m, [0])
    shoved = _entry(m, 0)["x"]
    assert shoved <= prev_x - 20, (
        f"x went {prev_x} -> {shoved}: that is not a knockback away from him")
    # The i-frames: standing inside him costs nothing for the rest of the
    # window. Measured from the contact frame, with margin — 45 frames is the
    # window and the next contact can only land after it.
    hp_now = _hud(m)[0]
    _drive(m, [0] * 20)
    assert _hud(m)[0] == hp_now, "the i-frames did not hold"


def test_zero_hp_prints_game_over_one_cell_per_frame_then_freezes(fresh):
    """The lockout, and the proof the tick is still RUNNING inside it.

    A frozen game and a dead CPU look identical in a single frame, so the
    banner is the discriminator: bg_text's queue commits ONE cell per frame,
    so "GAME OVER" appears letter by letter over nine frames AFTER the KO —
    something only a live tick can do. Then, with the banner complete, held
    input must change nothing at all: the whole frame is byte-identical.
    """
    m = fresh
    blank = " " * OVER_LEN
    assert _text(m, OVER_ROW, OVER_C, OVER_LEN) == blank
    # Stand still and let him land three contacts (45 i-frames apart).
    for _ in range(20):
        _drive(m, [0] * 30)
        if _hud(m)[0] == "0000":
            break
    assert _hud(m)[0] == "0000", "he never went down"
    # The banner pumps in, one cell per frame, in order.
    widths = []
    for _ in range(OVER_LEN + 3):
        _drive(m, [0])
        widths.append(len(_text(m, OVER_ROW, OVER_C, OVER_LEN).rstrip()))
    assert widths == sorted(widths), f"the banner did not fill in order: {widths}"
    assert widths[-1] == OVER_LEN, f"the banner stalled at {widths[-1]} cells"
    assert _text(m, OVER_ROW, OVER_C, OVER_LEN) == "GAME OVER"
    # ...and now nothing moves, whatever is held.
    before = _shot(m, "over_a").tobytes()
    _drive(m, [RIGHT | A] * 30)
    assert _shot(m, "over_b").tobytes() == before, "the freeze let input through"
    _drive(m, [LEFT | UP | DOWN] * 30)
    assert _shot(m, "over_c").tobytes() == before, "the freeze let input through"
