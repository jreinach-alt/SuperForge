"""mode7_explore — the streaming Mode 7 overworld.

A 512x512-tile world — sixteen times the area the Mode 7 VRAM window holds —
walked on a tile grid by an avatar pinned at the affine pivot, with the leading
edge streamed in as the camera moves and water and mountains refusing the step.

WHAT EVERY TEST HERE READS. The rendered output region the feature produces:
the Mode 7 tilemap's VRAM bytes, hardware OAM, CGRAM, or the screenshot's
pixels. Never a game variable standing in for one. Where a camera word IS read
it is only to say WHICH world window to compare against — the assertion is
always the VRAM-versus-blob comparison, so a camera word that lied would make
the comparison fail rather than pass. (CLAUDE.md rule 2.)

THE ORACLES ARE INDEPENDENT OF THE ROM in the two places it matters:

  * the world window is rebuilt HERE from `m7x_map.bin` with the wrapped
    placement recomputed from (wx, wy), so it cannot agree with the streamer by
    sharing its arithmetic;
  * the boot frame is compared against A SECOND IMPLEMENTATION'S RENDER of the
    same scene — frame 5 of the recorded walk in its published GIF, the last
    frame before motion starts. That picture was produced by a program sharing
    no code with this one, which is what makes agreement evidence. CLAUDE.md's
    asset-import rule asks exactly for that: a converter validated against the
    auditor's own rendering of its own source agrees only with itself. The GIF
    lives outside this tree and is named by `SF_REFERENCE_TREE`, so these cases
    SKIP — loudly — wherever it is unset, as the three reference-gated cases in
    `test_split_v_fight.py` do.

NO WALL CLOCK ANYWHERE. Every capture lands on an ABSOLUTE emulated frame via
`boot_to_frame`, and every driven frame is a `frame_step` on a parked core, so
a loaded host changes how long a test takes and never what it sees.

STATE CYCLES, NOT SNAPSHOTS. The streaming test walks EAST, WEST, NORTH, SOUTH
and then idles, asserting the full window at rest after each leg. A ring-buffer
whose left edge held stale forward-pass data is exactly the bug a one-direction
test ships (AGENTS.md, test discipline).
"""
import os
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from mesen_runner import MesenRunner, MemoryType  # noqa: E402

BUILD = SUPERFORGE / "build"
ROM = BUILD / "mode7_explore.sfc"
ASSETS = BUILD / "assets"
# One expression on purpose: conftest resolves the map a module reads at
# COLLECTION time from exactly this shape, and refuses a module whose map it
# cannot see.
_JMAP = json.loads((SUPERFORGE / "build" / "m7x" / "symbol_map.json").read_text())

W, V, C, O = (MemoryType.SnesWorkRam, MemoryType.SnesVideoRam,
              MemoryType.SnesCgRam, MemoryType.SnesSpriteRam)


def _sym(name, scene="overworld"):
    """Addresses are ASKED FOR, never hardcoded — this reads the same map the
    ROM was assembled against, so an allocator move breaks the test loudly
    instead of silently reading the wrong bytes."""
    pool = (_JMAP["scenes"][scene]["placements"] if scene else _JMAP["globals"])
    for p in pool:
        if p["sym"] == name:
            return p
    raise KeyError(f"{name} not in the emitted map — did the allocator move it?")


# VRAM symbols are WORD addresses (the allocator's convention, and VMADD's);
# MesenRunner reads VRAM by BYTE, so every read below doubles. Written as the
# doubling rather than as a second constant so the two cannot drift.
V_M7 = _sym("ES_V_M7")["start"]                 # word address (0, pinned)
V_OBJ_CHR = _sym("ES_V_OBJ_CHR")["start"]       # word address
C_PAL = _sym("ES_C_M7X_PAL")["start"]           # word index (0, pinned)
C_OBJ_PAL = _sym("ES_C_MXO_PAL")["start"]       # word index (128, pinned)
O_AVATAR = _sym("ES_O_AVATAR")["start"]         # OAM slot

# DP is the low page of WRAM, so MemoryType.SnesWorkRam reads these where they
# are. Read to SELECT the oracle window, never asserted as the feature's output.
DP_CAM_PX = _sym("US_CAM_PX")["start"]
DP_CAM_PY = _sym("US_CAM_PY")["start"]

# The world's own geometry, from the generator's emitted .inc rather than
# transcribed — one author for the numbers the ROM and the oracle share.
_INC = (ASSETS / "m7x_world.inc").read_text() if (ASSETS / "m7x_world.inc").exists() else ""
_WORLD = {}
for _line in _INC.splitlines():
    if "=" in _line and not _line.lstrip().startswith(";"):
        _k, _v = (t.strip() for t in _line.split("=", 1))
        _v = _v.split(";")[0].strip()
        if _v.isdigit():
            _WORLD[_k] = int(_v)

# The screenshot is 256x239; the ACTIVE PICTURE is rows 7..230 (224 lines).
ACTIVE_TOP, ACTIVE_H = 7, 224

# An OPTIONAL external tree holding a second, independent implementation of
# this scene, named by `SF_REFERENCE_TREE`. It is read-only and never a build
# dependency: the variable is unset on an ordinary runner, which is why the two
# cases below SKIP rather than fail. Building green with nothing else on disk
# is a property this suite exists to prove, so "absent" is the normal state.
_REFERENCE_TREE = Path(os.environ.get("SF_REFERENCE_TREE",
                                      "/nonexistent/reference-tree"))
REFERENCE_GIF = _REFERENCE_TREE / "docs" / "screenshots" / "gifs" / "mode7_explore.gif"
REF_AT_REST_FRAME = 5    # the last frame before the recorded walk begins


@pytest.fixture(scope="module")
def runner():
    if not ROM.exists():
        pytest.fail(f"{ROM} missing — run `make mode7_explore` first")
    r = MesenRunner()
    yield r
    r.stop()               # resumes the core first: the module-boundary contract


def _blob(name):
    p = ASSETS / name
    if not p.exists():
        pytest.fail(f"{p} missing — run `make m7x-assets` first")
    return p.read_bytes()


def _shot(runner, tmp_path, tag):
    p = tmp_path / f"{tag}.png"
    runner.take_screenshot(str(p))
    img = Image.open(p).convert("RGB")
    return img.crop((0, ACTIVE_TOP, 256, ACTIVE_TOP + ACTIVE_H))


def _cam_tile(runner):
    return (runner.read_u16(W, DP_CAM_PX) // 8, runner.read_u16(W, DP_CAM_PY) // 8)


def _expected_window(ctx, cty):
    """The 128x128 tilemap the VRAM window must hold with the camera on tile
    (ctx, cty) — built from the world BLOB, with the wrapped placement
    recomputed here.

    THE WRAP IS THE WHOLE POINT and it is why this cannot be a sequential
    crop: the Mode 7 tilemap is a 128x128 torus and world tile (wx, wy) lives
    at word (wy & 127) * 128 + (wx & 127). A sequentially-built oracle would
    agree with a sequentially-built streamer and both would tear.
    """
    world_t = _WORLD["M7X_WORLD_T"]
    win = _WORLD["M7X_VRAM_WIN"]
    tilemap = _blob("m7x_map.bin")
    out = bytearray(win * win)
    x0, y0 = ctx - win // 2, cty - win // 2
    for dy in range(win):
        wy = (y0 + dy) % world_t
        for dx in range(win):
            wx = (x0 + dx) % world_t
            out[(wy & (win - 1)) * win + (wx & (win - 1))] = tilemap[wy * world_t + wx]
    return bytes(out)


def _vram_window(runner):
    """The tilemap the PPU is actually reading: the EVEN bytes of the Mode 7
    region. The odd bytes are the 8bpp CHR, which never streams."""
    win = _WORLD["M7X_VRAM_WIN"]
    raw = runner.read_bytes(V, V_M7 * 2, win * win * 2)
    return bytes(raw[0::2])


def _assert_window_exact(runner, tag):
    """The full-window invariant — a STOPPED-CAMERA claim.

    While the camera moves, VRAM trails it by the staging + VBlank-drain lag
    BY DESIGN, so every caller comes to rest first (AGENTS.md).
    """
    ctx, cty = _cam_tile(runner)
    got, want = _vram_window(runner), _expected_window(ctx, cty)
    if got != want:
        bad = [i for i in range(len(want)) if got[i] != want[i]]
        cols = sorted({i % 128 for i in bad})
        rows = sorted({i // 128 for i in bad})
        pytest.fail(
            f"{tag}: {len(bad)} of {len(want)} window words differ from the "
            f"world blob at camera tile ({ctx},{cty}); bad cols {cols[:8]} "
            f"({len(cols)}), bad rows {rows[:8]} ({len(rows)})")


def _walk_to(runner, target, **buttons):
    """Hold a direction until the camera reaches a tile, then come to REST.

    Bounded in EMULATED frames on a parked core, so host load cannot change
    what this does. The trailing steps release the pad and let the in-flight
    slide land: a step is atomic and the window is only complete at rest.
    """
    for _ in range(1200):
        if _cam_tile(runner) == target:
            break
        runner.frame_step(1, **buttons)
    else:
        pytest.fail(f"never reached tile {target}; stopped at {_cam_tile(runner)}")
    runner.frame_step(12)          # release, land the slide, drain the queue
    return _cam_tile(runner)


# =============================================================================
# BOOT — the picture, and the three uploads that make it
# =============================================================================
def test_boot_places_the_avatar_at_the_pivot(runner):
    """The avatar's placement, byte for byte: OAM slot 0 = tile 16 (the DOWN
    facing) at x=120, y=104, attr=$20.

    The x and y are not a preference — m7a_set_center pins the affine pivot at
    screen centre for every heading, so 120,104 is centre minus half a 16x16
    body and the avatar's placement is a CONSTANT by construction. The SIZE bit
    in the hi table is what makes her 16x16 rather than her own top-left
    quarter, and it is read here because that is a bug the picture hides at a
    glance.
    """
    runner.boot_to_frame(str(ROM), 90)
    entry = list(runner.read_bytes(O, O_AVATAR * 4, 4))
    assert entry == [120, 104, 16, 0x20], (
        f"OAM slot {O_AVATAR} is {entry}, not the required [120, 104, 16, 32]")
    hi = runner.read_bytes(O, 512 + O_AVATAR // 4, 1)[0]
    assert hi & 0x02, f"hi-table byte {hi:#04x}: the SIZE bit is clear — she renders 8x8"
    assert not hi & 0x01, f"hi-table byte {hi:#04x}: X9 is set — she is 256 px to the right"


def test_the_world_palette_reaches_cgram(runner):
    """The DESTINATION region of the floor's palette upload, byte for byte.

    A test that only asserted "the picture has colours" passes while the upload
    silently no-ops and the picture shows power-on CGRAM noise — which is a
    plausible-looking world (AGENTS.md sub-rule 3: asset upload paths require
    destination-region byte tests).

    WORD 0 IS INCLUDED DELIBERATELY. In Mode 7 an 8bpp pixel value is an
    ABSOLUTE CGRAM index, so entry 0 is both palette index 0 and the backdrop
    slot; the generator puts opaque grass there and this is where that contract
    is checked rather than described.
    """
    runner.boot_to_frame(str(ROM), 90)
    want = _blob("m7x_pal.bin")
    got = runner.read_bytes(C, C_PAL * 2, len(want))
    assert bytes(got) == want, "CGRAM does not hold m7x_pal.bin"


def test_the_avatar_sheet_and_palette_reach_their_allocated_bases(runner):
    """The other two destination regions: the OBJ CHR at the base the ALLOCATOR
    chose (floored above the pinned Mode 7 region), and OBJ palette 0."""
    runner.boot_to_frame(str(ROM), 90)
    chr_want = _blob("m7x_obj_chr.bin")
    chr_got = runner.read_bytes(V, V_OBJ_CHR * 2, len(chr_want))
    assert bytes(chr_got) == chr_want, (
        f"OBJ CHR at word {V_OBJ_CHR:#06x} does not hold m7x_obj_chr.bin")
    pal_want = _blob("m7x_obj_pal.bin")
    pal_got = runner.read_bytes(C, C_OBJ_PAL * 2, len(pal_want))
    assert bytes(pal_got) == pal_want, "OBJ palette 0 does not hold m7x_obj_pal.bin"


def test_the_seed_is_the_world_around_spawn(runner):
    """The floor's one enter-time DMA, checked as TWO separable claims.

    (1) THE DESTINATION REGION, BOTH HALVES. All 32,768 bytes of the Mode 7
        region must equal `m7x_seed.bin`. The interleave is the transfer's
        whole mechanism — mode 1 alternates VMDATAL/VMDATAH and VMAIN $80 makes
        the pair land as one word — and the EVEN half alone cannot see it going
        wrong. Measured: with VMAIN left at its power-on $00 the tilemap bytes
        still land correctly and only the CHR half shifts a word, so an
        even-bytes-only test reads GREEN against a scrambled picture. That was
        a real finding from `tools/plants/m7x_rail.py::seed-vmain`, and this
        assertion is what closes it.

    (2) THE PLACEMENT IS THE WORLD, derived independently. The even bytes must
        be the wrapped 128x128 window around spawn, rebuilt here from the world
        blob. A sequentially-built seed renders a perfectly plausible frame 0
        and tears at the first step, because the streamer writes
        position-wrapped and the two would disagree the first time a row was
        rewritten.
    """
    runner.boot_to_frame(str(ROM), 90)
    want = _blob("m7x_seed.bin")
    got = bytes(runner.read_bytes(V, V_M7 * 2, len(want)))
    if got != want:
        bad = [i for i in range(len(want)) if got[i] != want[i]]
        halves = ("tilemap (even)" if all(i % 2 == 0 for i in bad)
                  else "CHR (odd)" if all(i % 2 for i in bad) else "both halves")
        pytest.fail(f"the Mode 7 region differs from m7x_seed.bin in "
                    f"{len(bad)} of {len(want)} bytes — {halves}; "
                    f"first at byte {bad[0]}")
    assert _cam_tile(runner) == (_WORLD["M7X_SPAWN_TX"], _WORLD["M7X_SPAWN_TY"])
    _assert_window_exact(runner, "the seed")


def test_the_boot_frame_is_a_world_and_not_a_wash(runner, tmp_path):
    """A rendered-pixel floor under the byte tests above: the active picture
    carries the world's texture rather than one flat colour.

    Deliberately weak on its own — its job is to catch the class where every
    byte assertion passes and the screen still shows nothing (TM's layer bit
    clear, brightness stuck at 0). Four distinct colours would already prove
    that much; the authored world has eleven tiles over twelve, so the bound
    below is deliberately loose.
    """
    runner.boot_to_frame(str(ROM), 90)
    img = _shot(runner, tmp_path, "boot")
    colours = set(img.getdata())
    assert len(colours) >= 8, f"the active picture has {len(colours)} colours: {colours}"


@pytest.mark.skipif(not REFERENCE_GIF.exists(),
                    reason="SF_REFERENCE_TREE is unset or the GIF is missing — "
                           "an optional read-only tree, never a build dependency")
def test_the_boot_frame_matches_the_reference_render(runner, tmp_path):
    """THE GROUND TRUTH, and the reason it is a different program's picture.

    Everything else here checks this ROM against oracles built from the blobs
    this repo's own generator emitted. That is necessary and it is not
    sufficient: a converter validated against the auditor's rendering of its
    own source agrees with itself (the asset-import rule, sub-rule 7).
    The reference GIF is a hardware render by a program that shares no code
    with this one, so agreement is real evidence — and it is what settles the
    sixteen-pixel framing pivot, which is a question the render answers and no
    amount of reading the source does.

    Frame 5 is the recording's last AT-REST frame; frame 6 is already mid
    walk-bob.
    """
    runner.boot_to_frame(str(ROM), 90)
    mine = _shot(runner, tmp_path, "vs_ref")
    gif = Image.open(REFERENCE_GIF)
    gif.seek(REF_AT_REST_FRAME)
    theirs = gif.convert("RGB").crop((0, ACTIVE_TOP, 256, ACTIVE_TOP + ACTIVE_H))
    a, b = mine.load(), theirs.load()
    bad = [(x, y) for y in range(ACTIVE_H) for x in range(256) if a[x, y] != b[x, y]]
    assert not bad, (
        f"{len(bad)} of {256 * ACTIVE_H} pixels differ from the reference "
        f"render; first at {bad[0]} (mine {a[bad[0]]}, theirs {b[bad[0]]})")


def test_the_overworld_dawns_in_from_black(runner, tmp_path):
    """The brightness ramp, read off the PICTURE.

    A test on the fade's level byte would pass while INIDISP was never
    committed — which is the documented enter-time-INIDISP hazard, and the
    exact shape of a defect this engine has already paid for once: a `.a8`
    routine called from A16, the ramp never arming, and a black screen over
    perfectly correct VRAM. So this reads the brightest channel the frame
    actually renders.

    ABSOLUTE frames, because the claim is about WHEN: a boot bounded at ">= N"
    lands two frames apart under load and this is a ramp.
    """
    seen = []
    for frame in (2, 5, 9, 13, 21, 40):
        runner.boot_to_frame(str(ROM), frame, margin=min(20, frame - 1))
        img = _shot(runner, tmp_path, f"dawn{frame}")
        seen.append((frame, max(max(px) for px in img.getdata())))
    levels = [v for _, v in seen]
    assert levels[0] < 24, f"frame 2 is not near-black: {seen}"
    assert levels[0] < levels[1] < levels[2] < levels[3], (
        f"the ramp is not monotonic over frames 2..13: {seen}")
    assert levels[-1] == levels[-2], f"the ramp had not settled by frame 21: {seen}"
    assert levels[-1] > 150, f"the settled picture is dim: {seen}"


# =============================================================================
# WALKING — the whole state cycle, and the window at rest after each leg
# =============================================================================
def test_walking_streams_the_window_in_every_direction(runner):
    """EAST, WEST, NORTH, SOUTH and then idle, with the full 16,384-word
    window asserted against the world blob at rest after every leg.

    ONE DIRECTION IS NOT A TEST. A streaming engine walked only forward locks
    the forward pass and ships the reverse broken — the ring-buffer left edge
    holding stale data is precisely the bug a user finds by turning round
    (AGENTS.md state-cycle rule). Each leg here is more than sixteen tiles, so
    every leading edge fires many times over.

    The legs are asserted AT REST because the full-window invariant is a
    stopped-camera claim: in flight, VRAM trails the camera by the staging and
    VBlank-drain lag by design.
    """
    runner.boot_to_frame(str(ROM), 60)
    sx, sy = _WORLD["M7X_SPAWN_TX"], _WORLD["M7X_SPAWN_TY"]
    assert _cam_tile(runner) == (sx, sy)
    # EVERY LEG STAYS ON THE GENERATOR'S EXPLORER CORRIDOR — the row and column
    # through spawn that it carves open across the whole clamp box on purpose,
    # "so the proof can walk all four ways". Leaving it and turning is how the
    # first draft of this test walked into a mountain and read as a harness
    # failure rather than as terrain.
    R = 16
    with runner.frame_stepping():
        _assert_window_exact(runner, "at spawn")
        _walk_to(runner, (sx + R, sy), right=True)
        _assert_window_exact(runner, f"{R} tiles EAST")
        # PAST the start, not back to it: the reverse pass has to stream ground
        # the forward pass never staged, or it only re-walks its own footprint.
        _walk_to(runner, (sx - R, sy), left=True)
        _assert_window_exact(runner, f"{2 * R} tiles WEST — the reverse pass")
        _walk_to(runner, (sx, sy), right=True)
        _assert_window_exact(runner, "back at spawn")
        _walk_to(runner, (sx, sy - R), up=True)
        _assert_window_exact(runner, f"{R} tiles NORTH")
        _walk_to(runner, (sx, sy + R), down=True)
        _assert_window_exact(runner, f"{2 * R} tiles SOUTH — the reverse pass")
        _walk_to(runner, (sx, sy), up=True)
        _assert_window_exact(runner, "back at spawn again")
        runner.frame_step(30)
        _assert_window_exact(runner, "idle")


def test_the_facing_follows_the_last_direction_pushed(runner):
    """The rendered avatar, per direction, read out of hardware OAM.

    LEFT is the SIDE sprite H-FLIPPED through the attribute bit — no fourth
    facing is authored or shipped — so the LEFT case is what proves the flip
    rather than a fourth tile, and the DOWN/UP/RIGHT cases are what prove the
    LUT is not returning one constant.
    """
    runner.boot_to_frame(str(ROM), 60)
    want = {"right": (20, 0x20), "left": (20, 0x60),
            "up": (18, 0x20), "down": (16, 0x20)}
    with runner.frame_stepping():
        for name, (tile, attr) in want.items():
            runner.frame_step(20, **{name: True})
            runner.frame_step(2)
            entry = list(runner.read_bytes(O, O_AVATAR * 4, 4))
            assert entry[2:] == [tile, attr], (
                f"holding {name.upper()}: OAM slot {O_AVATAR} is {entry}, "
                f"want tile {tile} attr {attr:#04x}")
            assert entry[0] == 120, f"holding {name.upper()}: she left the pivot"


# =============================================================================
# COLLISION — and the diagonal that survives it
# =============================================================================
#
# WHERE THE WALL IS, from the world blob rather than from a remembered
# coordinate. The tests below need two staging tiles and the geometry that
# makes each one interesting; deriving them means a re-themed world moves the
# test instead of breaking it.
def _terrain(tx, ty):
    tilemap, terr = _blob("m7x_map.bin"), _blob("m7x_terr.bin")
    return terr[tilemap[ty * _WORLD["M7X_WORLD_T"] + tx]]


def _is_blocked(tx, ty):
    if not (_WORLD["M7X_CLAMP_MIN"] <= tx <= _WORLD["M7X_CLAMP_MAX"]
            and _WORLD["M7X_CLAMP_MIN"] <= ty <= _WORLD["M7X_CLAMP_MAX"]):
        return True
    return _WORLD["M7X_TERR_BLOCKED_MIN"] <= _terrain(tx, ty) <= _WORLD["M7X_TERR_BLOCKED_MAX"]


def _find_wall_east_of_spawn():
    """The first tile on the spawn row whose EAST neighbour blocks while its
    SOUTH neighbour is open — the shape both collision tests need."""
    ty = _WORLD["M7X_SPAWN_TY"] - 1
    for tx in range(_WORLD["M7X_SPAWN_TX"], _WORLD["M7X_CLAMP_MAX"]):
        if _is_blocked(tx + 1, ty) and not _is_blocked(tx, ty) \
                and not _is_blocked(tx, ty + 1):
            return tx, ty
    pytest.fail("no east-blocked / south-open tile on the row above spawn")


def test_a_blocked_step_does_not_move_the_world(runner, tmp_path):
    """BLOCKED means THE PICTURE DOES NOT MOVE — not "a variable stayed put".

    The facing is latched FIRST so the avatar has already turned; from there the
    two captures must be pixel-identical, which is the user-visible invariant
    the word "blocked" actually names. A camera-word assertion would pass while
    the streamer scrolled VRAM underneath it.
    """
    wall_tx, wall_ty = _find_wall_east_of_spawn()
    runner.boot_to_frame(str(ROM), 60)
    with runner.frame_stepping():
        _walk_to(runner, (wall_tx, _WORLD["M7X_SPAWN_TY"]), right=True)
        _walk_to(runner, (wall_tx, wall_ty), up=True)
        runner.frame_step(20, right=True)      # latch the facing into the wall
        runner.frame_step(4)
        before = _shot(runner, tmp_path, "wall_before")
        runner.frame_step(120, right=True)     # ...and keep pushing
        runner.frame_step(4)
        after = _shot(runner, tmp_path, "wall_after")
        entry = list(runner.read_bytes(O, O_AVATAR * 4, 4))
    a, b = before.load(), after.load()
    bad = [(x, y) for y in range(ACTIVE_H) for x in range(256) if a[x, y] != b[x, y]]
    assert not bad, (
        f"120 frames of held RIGHT into a wall moved {len(bad)} pixels; "
        f"first at {bad[0]}")
    assert entry[2] == 20, (
        f"she did not turn to face the wall: OAM slot {O_AVATAR} is {entry}")


def test_a_held_diagonal_keeps_moving_along_the_open_axis(runner, tmp_path):
    """The fall-through, asserted as what the player SEES.

    Input priority is LEFT -> RIGHT -> UP -> DOWN, and a blocked direction falls
    through to the next held axis. Without it a blocked higher-priority axis
    eats the whole diagonal and the avatar freezes against the wall — which
    reads as dropped input, not as collision.

    So: RIGHT alone at this tile leaves the frame pixel-identical (the control
    arm, which is what makes the second half mean anything); RIGHT+DOWN from
    the same tile must move the world, and the window it arrives at must still
    be the world's.
    """
    wall_tx, wall_ty = _find_wall_east_of_spawn()
    runner.boot_to_frame(str(ROM), 60)
    with runner.frame_stepping():
        _walk_to(runner, (wall_tx, _WORLD["M7X_SPAWN_TY"]), right=True)
        _walk_to(runner, (wall_tx, wall_ty), up=True)
        runner.frame_step(20, right=True)
        runner.frame_step(4)
        control = _shot(runner, tmp_path, "diag_control")
        runner.frame_step(40, right=True)
        runner.frame_step(4)
        still = _shot(runner, tmp_path, "diag_still")
        runner.frame_step(40, right=True, down=True)
        runner.frame_step(12)
        moved = _shot(runner, tmp_path, "diag_moved")
        _assert_window_exact(runner, "after the diagonal")
    ca, sa, ma = control.load(), still.load(), moved.load()
    frozen = [1 for y in range(ACTIVE_H) for x in range(256) if ca[x, y] != sa[x, y]]
    assert not frozen, (
        f"the control arm is not a control: RIGHT alone moved {len(frozen)} "
        f"pixels, so this tile's east neighbour does not block")
    shifted = [1 for y in range(ACTIVE_H) for x in range(256) if ca[x, y] != ma[x, y]]
    assert shifted, (
        "holding RIGHT+DOWN against an east wall left the picture unchanged — "
        "the blocked axis ate the diagonal and she froze")


# =============================================================================
# THE TOWN VISIT — the mosaic wipe, the interior, and the way back
# =============================================================================
#
# WHAT THESE READ. The dissolve is read off the PICTURE, because it has to be:
# $2106 is write-only (the PPU ports read zeros), so "the mosaic is coarsening"
# has no register to interrogate and a shadow-byte assertion would be a proxy
# for the one thing this rail's gallery row actually promises. `_mosaic_block`
# recovers the block size from the rendered frame instead.
#
# The interior is read three ways, and the third is the one that is not a
# tautology: its destination VRAM/CGRAM regions against the blobs (sub-rule 3),
# its tilemap against a Python re-implementation of the room, and the settled
# frame against THE SECOND IMPLEMENTATION'S RENDER — a hardware picture by a
# program that shares no code with this one (the asset-import rule,
# sub-rule 7).

TOWN = "town"
V_TOWN_CHR = _sym("ES_V_TOWN_CHR", TOWN)["start"]     # word address (pinned)
V_TOWN_MAP = _sym("ES_V_TOWN_MAP", TOWN)["start"]     # word address (pinned)
C_TOWN_PAL = _sym("ES_C_TOWN_PAL", TOWN)["start"]     # word index (0, pinned)
O_TOWN_AVATAR = _sym("ES_O_TOWN_AVATAR", TOWN)["start"]
DP_TOWN_TX = _sym("US_TOWN_TX", TOWN)["start"]
DP_TOWN_TY = _sym("US_TOWN_TY", TOWN)["start"]

# The room, re-implemented here rather than read out of the ROM. Same numbers,
# independent arithmetic: the oracle below walks 32x32 and answers each cell
# from these bounds, so a classifier that got its ORDER wrong (the door sits IN
# the bottom wall and must be tested first) produces a tilemap this disagrees
# with.
ROOM_X0, ROOM_X1, ROOM_Y0, ROOM_Y1 = 2, 29, 1, 26
DOOR_TX, DOOR_TY = 15, 26
TABLE_X0, TABLE_X1, TABLE_Y0, TABLE_Y1 = 13, 14, 10, 11
TOWN_SPAWN = (15, 22)
CLS_FLOOR, CLS_WALL, CLS_DOOR, CLS_TABLE = 0, 1, 2, 3

# The reference render of the INTERIOR. Frame 59 of the published GIF is the
# settled room with the avatar at her spawn tile — the same picture this rail's
# swap builds. Found by scanning the recording, not guessed: frames 52..74 are
# the visit and 59 is the one whose avatar has not yet stepped.
REF_TOWN_FRAME = 59

# The avatar's 16x16 body, in ACTIVE-PICTURE coordinates. She is pinned at the
# affine pivot on the overworld, so this box is a constant — masking it compares
# the PLANE's scroll position and nothing else.
AVATAR_BOX = (120, 104, 136, 120)


def _room_class(tx, ty):
    """The oracle: what the interior must render at (tx, ty)."""
    if (tx, ty) == (DOOR_TX, DOOR_TY):
        return CLS_DOOR
    if not (ROOM_X0 <= tx <= ROOM_X1 and ROOM_Y0 <= ty <= ROOM_Y1):
        return CLS_WALL
    if tx in (ROOM_X0, ROOM_X1) or ty in (ROOM_Y0, ROOM_Y1):
        return CLS_WALL
    if TABLE_X0 <= tx <= TABLE_X1 and TABLE_Y0 <= ty <= TABLE_Y1:
        return CLS_TABLE
    return CLS_FLOOR


def _mosaic_block(img):
    """The mosaic's block size, RECOVERED FROM THE RENDERED FRAME.

    $2106 is write-only and the PPU ports read zeros, so the size cannot be
    read back — and reading the engine's shadow byte would assert that the
    feature wrote what it meant to write, which is the proxy this repo's rule 2
    exists to refuse. A mosaic of size s renders the plane as s-aligned s x s
    blocks of one colour, so the size is recoverable: return the largest k in
    1..16 for which every k-aligned k x k block of the active picture is
    uniform.

    Alignment starts at active scanline 0, which is why the caller passes the
    ALREADY-CROPPED picture.
    """
    px = img.load()
    w, h = img.size
    best = 1
    for k in range(2, 17):
        ok = True
        for by in range(0, h - k + 1, k):
            for bx in range(0, w - k + 1, k):
                c = px[bx, by]
                if any(px[bx + dx, by + dy] != c
                       for dy in range(k) for dx in range(k)):
                    ok = False
                    break
            if not ok:
                break
        if ok:
            best = k
    return best


def _walk_to_the_doorstep(runner):
    """Walk from spawn to the tile immediately SOUTH of the enterable house —
    one step short of the trigger, facing UP, at rest.

    Split out from `_step_onto_the_house` because the return test needs a
    reading of the avatar from HERE: the landing frame parks her for the
    dissolve, so an OAM read taken after it compares a parked entry against a
    live one and says nothing about where she came back facing.
    """
    house = (_WORLD["M7X_DEMO_HOUSE_TX"], _WORLD["M7X_DEMO_HOUSE_TY"])
    _walk_to(runner, (house[0], _WORLD["M7X_SPAWN_TY"]), left=True)
    _walk_to(runner, (house[0], house[1] + 1), up=True)


def _step_onto_the_house(runner):
    """Walk from spawn to the ONE enterable house and land on it.

    The route is the generator's own forced-grass approach: west along the
    spawn row to the house column, then north up the approach. The last step is
    the landing that arms the wipe.
    """
    _walk_to_the_doorstep(runner)
    return _land_on_the_house(runner)


def _land_on_the_house(runner):
    """The single step from the doorstep onto the house — the LANDING that arms
    the wipe, and the settle the picture needs after it."""
    house = (_WORLD["M7X_DEMO_HOUSE_TX"], _WORLD["M7X_DEMO_HOUSE_TY"])
    runner.frame_step(1, up=True)      # the step that lands ON it
    runner.frame_step(8)               # ...lands, and arms the wipe
    # ...and TWO MORE, because the park point is one frame ahead of the picture.
    # The landing frame writes the final camera into the affine shadow and the
    # NMI at its end commits it, so the frame ON SCREEN at this instant is still
    # the one BEFORE the landing — one world pixel short, which under Mode 7's
    # identity matrix is one scanline of vertical shift. Reading WRAM here would
    # never notice; a test that compares the PICTURE has to wait for it. The
    # dissolve is unaffected: the OUT curve opens with four frames at brightness
    # 15 and mosaic size 0, so the two frames spent are still a clean image.
    runner.frame_step(2)
    return house


def _run_the_wipe_out(runner):
    """Advance to the far side of a dissolve: past the swap, past the IN ramp,
    to the first settled frame. Bounded in EMULATED frames."""
    runner.frame_step(60)


def test_stepping_onto_the_house_pixelates_the_world(runner, tmp_path):
    """THE HEADLINE, read off the picture: the plane coarsens into blocks.

    The mosaic size is recovered from the rendered frame (see `_mosaic_block`)
    because $2106 cannot be read back and the shadow byte is a proxy. The OUT
    ramp locks size to `15 - brightness` over twenty frames, so the block size
    must GROW across the ramp — a single snapshot would pass on a wipe that
    pixelated once and stuck.
    """
    runner.boot_to_frame(str(ROM), 60)
    with runner.frame_stepping():
        _step_onto_the_house(runner)
        clean = _mosaic_block(_shot(runner, tmp_path, "wipe_clean"))
        seen = [clean]
        for i in range(4):
            runner.frame_step(4)
            seen.append(_mosaic_block(_shot(runner, tmp_path, f"wipe_out{i}")))
    assert seen[0] == 1, (
        f"the frame the wipe armed on is already blocky (block {seen[0]}) — "
        f"the OUT curve is meant to open at a clean image")
    assert seen == sorted(seen), f"the dissolve did not coarsen monotonically: {seen}"
    assert seen[-1] >= 8, (
        f"the dissolve only reached block {seen[-1]} across the OUT ramp: {seen}")


def test_the_avatar_is_hidden_while_the_wipe_runs(runner, tmp_path):
    """OBJ HAS NO HARDWARE MOSAIC, so she has to be parked or she floats
    un-dissolved over a dissolving plane.

    `mosaic` cannot do this itself — TM has one owner per scene and it is the
    scene's BG feature — so it is a stated caller contract, and a contract with
    no gate behind it is exactly the kind that rots. Read from HARDWARE OAM (the
    region the sprite is drawn from), across the OUT ramp and again once the
    wipe has settled, so the RESTORE is tested as well as the park.
    """
    runner.boot_to_frame(str(ROM), 60)
    with runner.frame_stepping():
        _step_onto_the_house(runner)
        during = []
        for _ in range(4):
            runner.frame_step(4)
            during.append(list(runner.read_bytes(O, O_AVATAR * 4, 4)))
        _run_the_wipe_out(runner)
        after = list(runner.read_bytes(O, O_TOWN_AVATAR * 4, 4))
    for i, entry in enumerate(during):
        assert entry[1] >= 0xF0, (
            f"OUT frame group {i}: OAM slot {O_AVATAR} is {entry} — she is on "
            f"screen at y={entry[1]} while the plane dissolves under her")
    assert after[1] < 0xF0, (
        f"she never came back: OAM slot {O_TOWN_AVATAR} is {after} after the wipe")


def test_the_interior_reaches_its_allocated_vram_and_cgram(runner):
    """The DESTINATION regions, byte for byte (test-surface sub-rule 3).

    An upload path is exactly where a downstream-effects test passes over a
    silent no-op, so this reads the three regions the swap writes rather than
    what they make happen: the CHR at the pinned word $5000, the palette at
    CGRAM 0, and the 32x32 tilemap at word $5800 against a Python
    re-implementation of the room.

    The tilemap oracle is the one that carries weight. `town_classify` is the
    room's single source of truth — the same routine draws it and blocks the
    walk — so a classifier whose test ORDER was wrong (the door sits IN the
    bottom wall and must be tested first) renders a room with no exit, and this
    comparison is what sees it.
    """
    runner.boot_to_frame(str(ROM), 60)
    with runner.frame_stepping():
        _step_onto_the_house(runner)
        _run_the_wipe_out(runner)
        chr_got = bytes(runner.read_bytes(V, V_TOWN_CHR * 2, len(_blob("m7x_town_chr.bin"))))
        pal_got = bytes(runner.read_bytes(C, C_TOWN_PAL * 2, len(_blob("m7x_town_pal.bin"))))
        map_got = bytes(runner.read_bytes(V, V_TOWN_MAP * 2, 32 * 32 * 2))
    assert chr_got == _blob("m7x_town_chr.bin"), (
        f"the interior's CHR at VRAM word {V_TOWN_CHR:#06x} is not the blob")
    assert pal_got == _blob("m7x_town_pal.bin"), (
        f"the interior's palette at CGRAM word {C_TOWN_PAL} is not the blob")
    want = bytearray()
    for ty in range(32):
        for tx in range(32):
            want += bytes((_room_class(tx, ty), 0))   # palette 0, prio 0, no flip
    bad = [i // 2 for i in range(0, len(want), 2) if map_got[i:i + 2] != want[i:i + 2]]
    assert not bad, (
        f"{len(bad)} of 1024 interior tilemap cells differ from the room; "
        f"first at cell {bad[0]} = ({bad[0] % 32},{bad[0] // 32}) — VRAM says "
        f"{map_got[bad[0] * 2]}, the room says {want[bad[0] * 2]}")


@pytest.mark.skipif(not REFERENCE_GIF.exists(),
                    reason="SF_REFERENCE_TREE is unset or the GIF is missing — "
                           "an optional read-only tree, never a build dependency")
def test_the_interior_matches_the_reference_render(runner, tmp_path):
    """THE GROUND TRUTH FOR THE INTERIOR, and the same argument as the boot
    frame's: everything else here compares this ROM against oracles built from
    blobs this repo's own generator emitted, and a converter validated against
    the auditor's rendering of its own source agrees with itself.

    Frame 59 of the reference GIF is the settled room with the avatar at her
    spawn tile — a hardware render by a program that shares no code with
    this one. It settles the whole interior at once: the four tiles, the
    sixteen-word palette, the room's geometry, BG1's base registers, the fixed
    scroll, and the avatar's placement in a scene where she is NOT pinned at
    the pivot.
    """
    runner.boot_to_frame(str(ROM), 60)
    with runner.frame_stepping():
        _step_onto_the_house(runner)
        _run_the_wipe_out(runner)
        mine = _shot(runner, tmp_path, "town_vs_ref")
    gif = Image.open(REFERENCE_GIF)
    gif.seek(REF_TOWN_FRAME)
    theirs = gif.convert("RGB").crop((0, ACTIVE_TOP, 256, ACTIVE_TOP + ACTIVE_H))
    a, b = mine.load(), theirs.load()
    bad = [(x, y) for y in range(ACTIVE_H) for x in range(256) if a[x, y] != b[x, y]]
    assert not bad, (
        f"{len(bad)} of {256 * ACTIVE_H} interior pixels differ from the "
        f"reference render; first at {bad[0]} (mine {a[bad[0]]}, theirs {b[bad[0]]})")


def test_the_town_walk_steps_one_tile_per_press_and_the_room_refuses(runner, tmp_path):
    """THE WHOLE STATE CYCLE of the interior walk, read from hardware OAM.

    Four things, and the first three are what a snapshot test would miss:

      * ONE TILE PER PRESS. Town input is EDGE-triggered where the overworld's
        is level, so holding a direction for many frames must move her exactly
        eight pixels once — a level read would cross the room in half a second.
      * ALL FOUR DIRECTIONS, forward and back on both axes, because a walk
        tested one way locks that way and ships the other broken.
      * THE WALL REFUSES, and the TABLE refuses by the same test — the room has
        one kind of obstacle, not two.
      * She is drawn where she stands: the OAM entry is tile * 8 on both axes,
        which is the whole camera model of a scene where the camera is fixed.
    """
    runner.boot_to_frame(str(ROM), 60)
    with runner.frame_stepping():
        _step_onto_the_house(runner)
        _run_the_wipe_out(runner)

        def entry():
            return list(runner.read_bytes(O, O_TOWN_AVATAR * 4, 4))

        def press(**b):
            runner.frame_step(1, **b)     # the edge
            runner.frame_step(3)          # release, and let the draw present
            return entry()

        start = entry()
        assert start[:2] == [TOWN_SPAWN[0] * 8, TOWN_SPAWN[1] * 8], (
            f"she did not arrive at the spawn tile: OAM {start}")

        # ---- one tile per press, and a HELD direction is STILL one tile ----
        # Thirty frames of one continuous hold. At LEVEL that is three tiles
        # (the overworld's slide is eight frames); on the EDGE it is one, and
        # one is what the interior must do.
        runner.frame_step(30, left=True)
        runner.frame_step(3)
        held = entry()
        assert held[0] == start[0] - 8 and held[1] == start[1], (
            f"30 held frames of LEFT walked her from {start[:2]} to {held[:2]} "
            f"— one continuous hold must be exactly one tile")

        # ---- back the other way, then both ends of the vertical axis -------
        back = press(right=True)
        assert back[:2] == start[:2], f"LEFT then RIGHT did not return: {back[:2]}"
        up1 = press(up=True)
        assert up1[1] == start[1] - 8 and up1[0] == start[0], f"UP: {up1[:2]}"
        down1 = press(down=True)
        assert down1[:2] == start[:2], f"UP then DOWN did not return: {down1[:2]}"

        # ---- the wall refuses: walk west to it and keep pressing -----------
        for _ in range(TOWN_SPAWN[0] - ROOM_X0):
            press(left=True)
        at_wall = entry()
        assert at_wall[0] == (ROOM_X0 + 1) * 8, (
            f"she did not come to rest against the west wall: OAM {at_wall}")
        refused = press(left=True)
        assert refused[:2] == at_wall[:2], (
            f"the wall let her through: {at_wall[:2]} -> {refused[:2]}")

        # ---- the table refuses, and it is a different obstacle -------------
        for _ in range(TABLE_X0 - (ROOM_X0 + 1)):
            press(right=True)
        for _ in range(TOWN_SPAWN[1] - (TABLE_Y1 + 1)):
            press(up=True)
        below_table = entry()
        assert below_table[:2] == [TABLE_X0 * 8, (TABLE_Y1 + 1) * 8], (
            f"the approach to the table ended at {below_table[:2]}, not "
            f"{[TABLE_X0 * 8, (TABLE_Y1 + 1) * 8]}")
        into_table = press(up=True)
        assert into_table[:2] == below_table[:2], (
            f"the table let her through: {below_table[:2]} -> {into_table[:2]}")


def test_the_mode7_image_survives_the_visit(runner):
    """THE PROPERTY THE WHOLE DESIGN RESTS ON: the interior writes UPPER VRAM,
    so the 32 KB Mode 7 region comes back byte-identical and the return needs
    no re-stream.

    Both halves are compared — the tilemap in the even bytes AND the 8bpp CHR
    in the odd ones. A town whose claims had been PACKED rather than pinned
    would first-fit from word 0 and land squarely on this, and the symptom
    would be a plausible-looking world made of the interior's four tiles.
    """
    runner.boot_to_frame(str(ROM), 60)
    with runner.frame_stepping():
        _step_onto_the_house(runner)
        before = bytes(runner.read_bytes(V, V_M7 * 2, 128 * 128 * 2))
        _run_the_wipe_out(runner)
        during = bytes(runner.read_bytes(V, V_M7 * 2, 128 * 128 * 2))
        _walk_town_to_the_door(runner)
        _run_the_wipe_out(runner)
        after = bytes(runner.read_bytes(V, V_M7 * 2, 128 * 128 * 2))
    for tag, got in (("while she is indoors", during), ("after the return", after)):
        if got == before:
            continue
        bad = [i for i in range(len(before)) if before[i] != got[i]]
        pytest.fail(
            f"{len(bad)} of {len(before)} Mode 7 bytes changed {tag}; first at "
            f"byte {bad[0]} (word {bad[0] // 2}, "
            f"{'tilemap' if bad[0] % 2 == 0 else 'CHR'} half)")


def _walk_town_to_the_door(runner):
    """From the interior's spawn tile, straight down onto the exit door."""
    for _ in range(DOOR_TY - TOWN_SPAWN[1]):
        runner.frame_step(1, down=True)
        runner.frame_step(3)


def test_the_return_lands_on_the_same_picture(runner, tmp_path):
    """"BACK OUT AT THE SAME SPOT", asserted as the PICTURE and not as the
    camera word.

    A camera word that round-tripped correctly while the plane scrolled
    underneath it is exactly the indirect-evidence failure rule 2 names — and
    on this rail it is a live risk rather than a hypothetical, because the
    camera lives in SCENE DP that the interior's own state reuses while she is
    indoors.

    So: capture the overworld at the house with the wipe armed but before the
    dissolve has touched anything (the OUT curve opens with four frames at full
    brightness and size 0), then capture again once the return has settled, and
    require the two to be pixel-identical.

    THE AVATAR'S 16x16 BOX IS MASKED, and masking it removes nothing about the
    camera: she is pinned at the affine pivot, so her screen position is a
    constant in every overworld frame. What differs there is only that the
    "before" frame has her parked for the dissolve. Her OAM entry is compared
    separately, which covers the sprite the mask excludes.
    """
    runner.boot_to_frame(str(ROM), 60)
    with runner.frame_stepping():
        # Read her BEFORE the landing frame, which parks her for the dissolve:
        # she is one tile south of the house, at rest, already facing UP.
        _walk_to_the_doorstep(runner)
        before_oam = list(runner.read_bytes(O, O_AVATAR * 4, 4))
        _land_on_the_house(runner)
        before = _shot(runner, tmp_path, "return_before")
        before_cam = _cam_tile(runner)
        _run_the_wipe_out(runner)
        _walk_town_to_the_door(runner)
        _run_the_wipe_out(runner)
        after = _shot(runner, tmp_path, "return_after")
        after_oam = list(runner.read_bytes(O, O_AVATAR * 4, 4))
        after_cam = _cam_tile(runner)
        _assert_window_exact(runner, "after the return")
    x0, y0, x1, y1 = AVATAR_BOX
    a, b = before.load(), after.load()
    bad = [(x, y) for y in range(ACTIVE_H) for x in range(256)
           if not (x0 <= x < x1 and y0 <= y < y1) and a[x, y] != b[x, y]]
    assert not bad, (
        f"the plane came back {len(bad)} pixels away from where she left it "
        f"(camera tile {before_cam} -> {after_cam}); first at {bad[0]} "
        f"(before {a[bad[0]]}, after {b[bad[0]]})")
    assert after_oam == before_oam, (
        f"she came back facing differently: OAM {before_oam} -> {after_oam}")


def test_a_decorative_lattice_house_does_not_warp(runner, tmp_path):
    """THE DISTINCTION THE GENERATOR EXISTS TO MAKE, exercised.

    One tile in 262,144 carries TERR_TOWN_ENTER; the 190 lattice houses carry
    TERR_TOWN, one class below it. Without that distinction a streaming sweep
    across any decorative house warps the player indoors — and the two classes
    are adjacent integers, so an off-by-one in the compare is a live and
    entirely plausible defect.

    Read as the picture plus the region the visit would have destroyed: the
    interior overwrites CGRAM 0..15, so an unwanted warp shows up as the world
    palette being the town's. Both are output regions; neither is a scene id.
    """
    lattice = _find_lattice_house()
    runner.boot_to_frame(str(ROM), 60)
    with runner.frame_stepping():
        _walk_to(runner, (_WORLD["M7X_SPAWN_TX"], lattice[1]), down=True)
        _walk_to(runner, lattice, left=True)
        runner.frame_step(60)          # a wipe, had one armed, is long over
        pal = bytes(runner.read_bytes(C, C_PAL * 2, len(_blob("m7x_pal.bin"))))
        img = _shot(runner, tmp_path, "lattice")
        _assert_window_exact(runner, "standing on a decorative house")
    assert _terrain(*lattice) == _WORLD["M7X_TERR_TOWN"], (
        f"tile {lattice} is class {_terrain(*lattice)}, not the decorative "
        f"TERR_TOWN this test needs")
    assert pal == _blob("m7x_pal.bin"), (
        f"standing on a decorative house replaced the world palette with the "
        f"interior's — the lattice warped")
    assert _mosaic_block(img) == 1, (
        "the picture is pixelated on a decorative house — a wipe was armed")


def _find_lattice_house():
    """A TERR_TOWN tile reachable from spawn by walking straight down then
    straight left, derived from the world blob rather than remembered."""
    sx, sy = _WORLD["M7X_SPAWN_TX"], _WORLD["M7X_SPAWN_TY"]
    step = _WORLD["M7X_LANDMARK_STEP"]
    # The lattice sits on MULTIPLES of the step, not on offsets from spawn —
    # spawn is 258 and the row below it is 288, not 290.
    for ty in range(((sy // step) + 1) * step, _WORLD["M7X_CLAMP_MAX"], step):
        if any(_is_blocked(sx, y) for y in range(sy, ty + 1)):
            continue
        for tx in range(sx, sx - step, -1):
            if _is_blocked(tx, ty):
                break
            if _terrain(tx, ty) == _WORLD["M7X_TERR_TOWN"]:
                return tx, ty
    pytest.fail("no decorative lattice house reachable by down-then-left from spawn")


def test_the_streamer_still_works_after_the_return(runner):
    """THE STATE CYCLE THE RETURN OPENS, and the reason it is not covered by
    the walk tests above.

    The streamer's tracking — its camera tile, its LAST staged-through tile and
    its pending row/column counts — lives in SCENE DP, and the interior reuses
    those exact bytes for its own state while she is indoors. So coming back is
    not "resume what was paused": the tracking has been overwritten by the town,
    and the return has to re-seed it AT THE RESTORED CAMERA (`stream_resync`).
    Everything else about the return can be right and this still be wrong, and
    the symptom would not appear until the FIRST STEP after coming out — the
    leading edge staged from a stale LAST, walking rows into the window that
    belong somewhere else entirely.

    IT ASSERTS OVER A SPAN OF FRAMES AND NOT AT ONE SETTLED POINT, and that is
    the difference between seeing this defect and not. Without the re-seed the
    tracking's LAST tile is the interior's leftovers, so the streamer walks it
    toward the true camera at its eight-tiles-a-frame clamp and stages the
    columns in between — MEASURED on the emulator: 8,054 of 16,384 window words
    wrong at the worst frame, healing to zero after about thirty. Half a second
    of visibly wrong world, and then it looks right again. A test that read the
    window once, late, calls that a pass; this one holds the invariant across
    the whole span, because "the picture never goes wrong" is the claim, not
    "the picture is right eventually".

    It then walks in BOTH directions on one axis, so a streamer that came back
    frozen rather than wrong is caught too.
    """
    runner.boot_to_frame(str(ROM), 60)
    with runner.frame_stepping():
        _step_onto_the_house(runner)
        _run_the_wipe_out(runner)
        _walk_town_to_the_door(runner)
        # 20 OUT + the blank-phase rebuild + 15 IN — the wipe is over, and the
        # overworld's tick has been live for a frame or two.
        runner.frame_step(40)
        for i in range(5):
            _assert_window_exact(runner, f"{40 + i * 5} frames after the exit step")
            runner.frame_step(5)
        here = _cam_tile(runner)
        far = _open_run_east(here)
        _walk_to(runner, (far, here[1]), right=True)
        _assert_window_exact(runner, f"{far - here[0]} tiles east of the house")
        _walk_to(runner, here, left=True)
        _assert_window_exact(runner, "back at the house, after the return")


def _open_run_east(start):
    """How far east of `start` she can walk before the terrain refuses — from
    the world blob, so a re-themed map moves the test instead of breaking it.
    Four tiles is the floor: fewer than that stages no full column and the walk
    would prove nothing about the streamer."""
    tx = start[0]
    while not _is_blocked(tx + 1, start[1]):
        tx += 1
    if tx - start[0] < 4:
        pytest.fail(f"only {tx - start[0]} open tiles east of {start} — not "
                    f"enough to stage a column")
    return tx
