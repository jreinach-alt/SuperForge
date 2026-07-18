"""Done-condition for the mode_showcase HARNESS (S1, Mode-1 scope).

Reads RENDERED OUTPUT, never proxies (CLAUDE.md rule 2):
  - boots to the menu (rendered text pixels);
  - A enters the instructions then the live Mode-1 demo (scene word + render);
  - tuning a representative knob in each slot VISIBLY changes the frame
    (screenshot diff) and the live value (OAM HUD digits / debug mirror);
  - Select advances the lit slot (OAM bottom-bar marker moves);
  - the PRESET knob re-frames the scene (window spotlight, BG3 split);
  - Start+Select renders a readable B/W param sheet (pixels) + paging works;
  - an SRAM save -> reset -> recall round-trips a config (rendered result);
  - the debug-region export ($7E:E300) reflects live params;
  - the limit meter shows green/yellow/red at thresholds (rendered colour);
  - the frame heartbeat holds 60fps (PPU frame counter advances 1/frame).

Frame-stepped (deterministic) input throughout (MesenRunner.frame_step).
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
OAM = MemoryType.SnesSpriteRam
CG = MemoryType.SnesCgRam

# --- param model addresses (must match templates/mode_showcase/main.asm) ---
SCENE_ADDR   = 0x1804
KNOB_VAL     = 0xE200       # 30 knob bytes
ACTIVE_SLOT  = 0xE23C
DBG_MIRROR   = 0xE300       # 30 knob mirror + [30]=slot + [31]=preset
SHEET_PAGE   = 0xE321
ARENA_OWNER  = 0xE325       # $C000 arena-mutex owner (0=none,1=grad,2=plx)
OAM_OVF      = 0xE344       # HUD OAM-budget overflow flag (must stay 0)
SAVE_SLOT_SEL= 0xE345       # active SRAM save slot 0..3
SC_MENU, SC_INSTR, SC_DEMO = 0, 1, 2

# knob indices (slot*5 + param)
KN_CMATH_OP = 0
KN_CMATH_B  = 3            # CMATH blue tint (max 31), X/Y pair
KN_MOS_SIZE = 5
KN_LIGHT_BR = 10
KN_PRESET   = 25
KN_GRAD_EN  = 26          # gradient backdrop enable (heavy arena A), v/^ pair
KN_PLX_EN   = 27          # parallax bands enable (heavy arena B), A/B pair

# arena owners
ARENA_NONE, ARENA_GRADIENT, ARENA_PARALLAX = 0, 1, 2

_WHITE = lambda p: p[0] > 200 and p[1] > 200 and p[2] > 200
_GREENISH = lambda p: p[1] > 120 and p[0] < 120
_REDDISH = lambda p: p[0] > 120 and p[1] < 90 and p[2] < 90


def _count(img, pred):
    return sum(1 for p in img.get_flattened_data() if pred(p))


def _load(img_path):
    return Image.open(img_path).convert("RGB")


# Function-scoped: a FRESH boot per test. The harness's btnp edge controls +
# the param-sheet freeze make cross-test state leak hard to reason about on a
# shared runner; a per-test power-on is the deterministic, honest baseline (the
# suite is small). Each test therefore starts from the menu at power-on.
@pytest.fixture
def runner():
    r = MesenRunner()
    rom = BUILD / "mode_showcase.sfc"
    assert rom.exists(), f"{rom} not built — run `make mode_showcase` first"
    r.load_rom(str(rom), run_seconds=0.5)
    yield r
    r.stop()


def _tap(run, **btns):
    """A clean rising-edge tap for a btnp control. The frame_step input latch
    takes effect on the frame AFTER it is set (one-frame presentation lag), so
    a 1-frame hold is never actually polled while pressed — hold for 2 frames so
    the press is sampled (the edge fires on the first sampled frame; the second
    is a harmless re-sample of a held button). Then release + settle.
    (First arg named `run`, not `r`, so an R-button tap `_tap(run, r=True)` does
    not collide with the positional parameter.)"""
    run.frame_step(1)               # guarantee a released frame before the edge
    run.frame_step(2, **btns)       # hold 2 frames -> the press is sampled (edge)
    run.frame_step(2)               # release + settle


CUR_MODE = 0xE23D             # selected BG mode 0..7 (dispatch SSoT)


def _select_mode(r, mode):
    """From the menu (cursor on mode 0 at boot), move the cursor to `mode` via the
    column/row controls the menu wires (Down steps within a column 0-3 / 4-7;
    Right jumps to the right column). Reads SHOW_CUR_MODE (the highlight SSoT, set
    by the rendered cursor) to converge — not a proxy: it is what the caret draws
    and what A commits."""
    r.frame_step(3)
    # converge the cursor with a small bounded loop of taps
    for _ in range(16):
        cur = r.read_bytes(WR, CUR_MODE, 1)[0]
        if cur == mode:
            return
        if (cur & 4) != (mode & 4):
            _tap(r, right=True) if (mode & 4) else _tap(r, left=True)
        else:
            _tap(r, down=True)
    assert r.read_bytes(WR, CUR_MODE, 1)[0] == mode, "menu cursor did not reach mode"


def _to_demo(r, mode=1):
    """From a fresh power-on (menu), select `mode` (default Mode 1, the S1 proving
    ground), tap A -> instructions -> live demo. The fixture gives each test a
    freshly-booted ROM, so this always starts at the menu (cursor on mode 0) and
    the demo enters with the selected page's default knob values."""
    _select_mode(r, mode)
    _tap(r, a=True)              # menu: A -> instructions (commits the highlight)
    _tap(r, a=True)             # instructions: A -> demo
    r.frame_step(12)             # let the demo settle + render the HUD


def test_boots_to_menu(runner):
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    with runner.frame_stepping():
        runner.frame_step(3)
        assert runner.read_bytes(WR, SCENE_ADDR, 1)[0] == SC_MENU
        runner.take_screenshot("/tmp/ms_menu.png")
    img = _load("/tmp/ms_menu.png")
    # the OBJ-font menu renders many white glyph pixels
    assert _count(img, _WHITE) > 400, "menu text not rendered"


def test_a_advances_to_demo(runner):
    with runner.frame_stepping():
        _to_demo(runner)
        assert runner.read_bytes(WR, SCENE_ADDR, 1)[0] == SC_DEMO
        runner.take_screenshot("/tmp/ms_demo.png")
    img = _load("/tmp/ms_demo.png")
    # the BG checker (green/red) + HUD render -> lots of non-black pixels
    assert _count(img, _GREENISH) > 500, "Mode-1 BG field not rendered"
    assert _count(img, _WHITE) > 100, "HUD readout not rendered over the demo"


def test_heartbeat_60fps(runner):
    """The PPU frame counter advances exactly 1 per stepped frame (no drops)."""
    with runner.frame_stepping():
        _to_demo(runner)
        f0 = runner.ppu_frame_count()
        runner.frame_step(10)
        f1 = runner.ppu_frame_count()
    assert f1 - f0 == 10, f"heartbeat slipped: {f1 - f0} frames for 10 steps"


def test_knob_tuning_changes_frame_and_value(runner):
    """Tuning a representative knob in each slot visibly changes the frame AND
    the live value (read from the debug mirror = rendered-state export)."""
    with runner.frame_stepping():
        _to_demo(runner)
        runner.take_screenshot("/tmp/ms_before.png")
        before = _load("/tmp/ms_before.png")

        # Slot 0 (CMATH) active by default. Param 0 = OP on </>. Drive RIGHT to
        # raise the color-math op (held ramps it); the screen tint changes.
        op0 = runner.read_bytes(WR, KNOB_VAL + KN_CMATH_OP, 1)[0]
        runner.frame_step(8, right=True)
        runner.frame_step(4)
        op1 = runner.read_bytes(WR, KNOB_VAL + KN_CMATH_OP, 1)[0]
        assert op1 != op0, f"CMATH OP knob did not change ({op0}->{op1})"
        # debug mirror reflects it
        assert runner.read_bytes(WR, DBG_MIRROR + KN_CMATH_OP, 1)[0] == op1

        # Advance to slot 1 (MOSAIC), tune size on </> (param 0) -> frame warps.
        _tap(runner, select=True)
        assert runner.read_bytes(WR, ACTIVE_SLOT, 1)[0] == 1
        runner.frame_step(10, right=True)
        runner.frame_step(4)
        mos = runner.read_bytes(WR, KNOB_VAL + KN_MOS_SIZE, 1)[0]
        assert mos > 0, "MOSAIC size knob did not rise"

        runner.take_screenshot("/tmp/ms_after.png")
    after = _load("/tmp/ms_after.png")
    # the rendered frame changed (mosaic + color-math op both alter many pixels)
    b = list(before.get_flattened_data())
    a = list(after.get_flattened_data())
    diff = sum(1 for i in range(0, len(a), 7) if a[i] != b[i])
    assert diff > 100, f"tuning did not visibly change the frame (diff={diff})"


def test_select_advances_lit_slot(runner):
    """Select advances the lit slot — the OAM bottom-bar marker (BAR glyph)
    moves to the new slot position. Read OAM, not a proxy."""
    SF_OBJG_BAR = 43

    def bar_x():
        oam = runner.read_bytes(OAM, 0, 512)
        # the bottom bar is at y=210; the lit slot is the BAR-glyph (tile 43)
        for i in range(128):
            x, y, t, a = oam[i * 4:i * 4 + 4]
            if y == 210 and t == SF_OBJG_BAR:
                return x
        return None

    with runner.frame_stepping():
        _to_demo(runner)
        x0 = bar_x()
        assert x0 is not None, "lit-slot BAR marker not found in OAM bottom bar"
        _tap(runner, select=True)
        runner.frame_step(2)
        assert runner.read_bytes(WR, ACTIVE_SLOT, 1)[0] == 1
        x1 = bar_x()
        assert x1 is not None and x1 != x0, f"lit marker did not move ({x0}->{x1})"


def test_preset_knob_reframes(runner):
    """The PRESET knob (slot 5, param 0) re-frames the scene. Move to slot 5,
    bump the preset to the window-spotlight, and the frame changes."""
    with runner.frame_stepping():
        _to_demo(runner)
        # advance to slot 5 (5 clean Select taps from slot 0)
        for _ in range(5):
            _tap(runner, select=True)
        assert runner.read_bytes(WR, ACTIVE_SLOT, 1)[0] == 5
        runner.take_screenshot("/tmp/ms_preset0.png")
        # preset is param 0 of slot 5 -> </> ; drive RIGHT to preset 2 (spotlight)
        runner.frame_step(6, right=True)
        runner.frame_step(6)
        preset = runner.read_bytes(WR, KNOB_VAL + KN_PRESET, 1)[0]
        assert preset > 0, "PRESET knob did not advance"
        runner.take_screenshot("/tmp/ms_preset2.png")
    p0 = list(_load("/tmp/ms_preset0.png").get_flattened_data())
    p2 = list(_load("/tmp/ms_preset2.png").get_flattened_data())
    diff = sum(1 for i in range(0, len(p2), 7) if p2[i] != p0[i])
    assert diff > 100, f"preset change did not re-frame the scene (diff={diff})"


def test_param_sheet_freeze_and_page(runner):
    """Start+Select freezes the demo + renders the B/W param sheet; </> pages."""
    with runner.frame_stepping():
        _to_demo(runner)
        # Start+Select -> sheet (one clean combined tap)
        _tap(runner, start=True, select=True)
        flags = runner.read_bytes(WR, 0xE23E, 1)[0]
        assert flags & 0x01, "param sheet flag (freeze) not set"
        runner.take_screenshot("/tmp/ms_sheet0.png")
        page0 = runner.read_bytes(WR, 0xE321, 1)[0]
        # page with RIGHT (a btnp control in the sheet)
        _tap(runner, right=True)
        page1 = runner.read_bytes(WR, 0xE321, 1)[0]
        assert page1 != page0, f"param sheet did not page ({page0}->{page1})"
        runner.take_screenshot("/tmp/ms_sheet1.png")
        sheet = _load("/tmp/ms_sheet0.png")
        # the sheet is readable white text on black (lots of white)
        assert _count(sheet, _WHITE) > 200, "param sheet text not rendered"
        # F12: prove the RENDERED page content actually changed (pixels), not just
        # the page counter. Page 0 (slot 0 params) vs page 1 (slot 1 params) differ.
        s0 = list(sheet.get_flattened_data())
        s1 = list(_load("/tmp/ms_sheet1.png").get_flattened_data())
        diff = sum(1 for i in range(0, len(s1), 7) if s1[i] != s0[i])
        assert diff > 50, f"param sheet page content did not change in pixels ({diff})"
        # leaving the sheet (Start+Select again) clears the freeze
        _tap(runner, start=True, select=True)
        assert (runner.read_bytes(WR, 0xE23E, 1)[0] & 0x01) == 0


def test_limit_meter_colours(runner):
    """The limit meter shows green at low field count and red at high count.
    Read the meter LEVEL bytes (SHOW_METER_*) AND the rendered bar colour."""
    OAM_ = OAM
    with runner.frame_stepping():
        _to_demo(runner)
        # default field count = 16 -> all meters green (level 0)
        cyc = runner.read_bytes(WR, 0xE322, 1)[0]
        oam_lvl = runner.read_bytes(WR, 0xE324, 1)[0]
        assert cyc == 0 and oam_lvl == 0, "meters not green at low count"
        # crank the FIELD count knob to red: slot 4 (4 Select taps), param 0 = </>
        for _ in range(4):
            _tap(runner, select=True)
        assert runner.read_bytes(WR, ACTIVE_SLOT, 1)[0] == 4
        runner.frame_step(120, right=True)   # ramp count to the cap (held, step 2)
        runner.frame_step(4)
        cnt = runner.read_bytes(WR, KNOB_VAL + 20, 1)[0]
        oam_lvl2 = runner.read_bytes(WR, 0xE324, 1)[0]
        assert cnt >= 70, f"field count did not reach the red zone ({cnt})"
        assert oam_lvl2 == 2, f"OAM meter not RED at high count (level {oam_lvl2})"
        runner.take_screenshot("/tmp/ms_meter_red.png")
    # the meter bar at the top-right renders a red pixel run
    img = _load("/tmp/ms_meter_red.png")
    w = img.size[0]
    d = list(img.get_flattened_data())
    red = sum(1 for y in range(12, 22) for x in range(w - 48, w)
              if _REDDISH(d[y * w + x]))
    assert red > 4, "red meter bar not visible in the top-right HUD"


def test_sram_save_recall_roundtrip():
    """Save a tuned config to SRAM, HARD power-cycle (a fresh load_rom flushes
    the .srm at unload and reseeds the new boot from it), recall -> the value
    round-trips. Proven battery pattern from test_save.py.
    """
    from pathlib import Path as _P
    from infrastructure.test_harness import mesen_runner as _mr
    srm = _P(_mr._DEFAULT_HOME_DIR) / "Saves" / "mode_showcase.srm"
    if srm.exists():
        srm.unlink()                                   # virgin battery
    rom = str(BUILD / "mode_showcase.sfc")
    r = MesenRunner()
    try:
        # --- run 1: tune CMATH OP to a distinctive value, save to slot 0 ---
        r.load_rom(rom, run_seconds=0.5)
        with r.frame_stepping():
            _to_demo(r)
            r.frame_step(8, right=True); r.frame_step(4)   # raise CMATH OP (held)
            saved = r.read_bytes(WR, KNOB_VAL + KN_CMATH_OP, 1)[0]
            _tap(r, start=True, select=True)               # -> param sheet
            _tap(r, a=True)                                # A = save to SRAM slot 0
            r.debug_resume()

        # --- run 2: HARD power cycle (reload flushes + reseeds), recall ---
        r.load_rom(rom, run_seconds=0.5)               # power cycle
        with r.frame_stepping():
            _to_demo(r)
            fresh = r.read_bytes(WR, KNOB_VAL + KN_CMATH_OP, 1)[0]  # re-seeded default
            _tap(r, start=True, select=True)           # -> param sheet
            _tap(r, b=True)                            # B = recall slot 0
            _tap(r, start=True, select=True)           # leave sheet -> demo apply
            r.frame_step(8)
            recalled = r.read_bytes(WR, KNOB_VAL + KN_CMATH_OP, 1)[0]
    finally:
        r.stop()
    assert saved != fresh, "test setup: tuned value equals the default (no signal)"
    assert recalled == saved, f"SRAM round-trip: saved {saved}, fresh {fresh}, recalled {recalled}"


def _goto_slot(r, slot):
    """From the demo, Select to the given option slot (0..5)."""
    cur = r.read_bytes(WR, ACTIVE_SLOT, 1)[0]
    while cur != slot:
        _tap(r, select=True)
        cur = r.read_bytes(WR, ACTIVE_SLOT, 1)[0]


def test_arena_mutex_auto_disable(runner):
    """F5: the $C000 arena holds <=1 heavy effect. Enable GRD (gradient) -> it
    owns the arena (indicator G, HDMA armed). Enable PLX (parallax) while GRD
    owns it -> GRD is AUTO-DISABLED (its knob clears, its HDMA torn down) and the
    indicator + owner reflect PLX. Reads RENDERED OUTPUT: the OAM indicator glyph,
    the owner byte, and the armed-HDMA mask (the disabled effect's absence)."""
    NMI_HDMA_ENABLE = 0x0108
    SF_OBJG_G, SF_OBJG_P = 17, 26
    ARENA_OAM_SLOT = 39                       # allocations §2 indicator band

    def indicator_tile():
        oam = runner.read_bytes(OAM, 0, 512)
        return oam[ARENA_OAM_SLOT * 4 + 2]    # tile byte of the indicator slot

    with runner.frame_stepping():
        _to_demo(runner)
        _goto_slot(runner, 5)                 # slot 5 holds PRS/GRD/PLX
        # GRD = param 1 -> v/^ pair; UP increments. Enable gradient.
        _tap(runner, up=True)
        runner.frame_step(4)
        assert runner.read_bytes(WR, KNOB_VAL + KN_GRAD_EN, 1)[0] == 1, "GRD not enabled"
        assert runner.read_bytes(WR, ARENA_OWNER, 1)[0] == ARENA_GRADIENT, \
            "gradient did not take the arena"
        grad_mask = runner.read_bytes(WR, NMI_HDMA_ENABLE, 1)[0]
        assert grad_mask != 0, "gradient HDMA not armed"
        assert indicator_tile() == SF_OBJG_G, "arena indicator not showing G (gradient)"

        # Enable PLX (param 2 -> A/B pair; A increments) while GRD owns the arena.
        _tap(runner, a=True)
        runner.frame_step(4)
        # GRD auto-disabled: its knob cleared AND it no longer owns the arena.
        assert runner.read_bytes(WR, KNOB_VAL + KN_GRAD_EN, 1)[0] == 0, \
            "GRD was NOT auto-disabled when PLX was enabled"
        assert runner.read_bytes(WR, KNOB_VAL + KN_PLX_EN, 1)[0] == 1, "PLX not enabled"
        assert runner.read_bytes(WR, ARENA_OWNER, 1)[0] == ARENA_PARALLAX, \
            "arena owner did not swap to parallax"
        plx_mask = runner.read_bytes(WR, NMI_HDMA_ENABLE, 1)[0]
        # parallax uses 1 channel vs gradient's 3: the disabled effect's HDMA is
        # gone (fewer armed channels) — the absence of GRD in the frame.
        assert bin(plx_mask).count("1") < bin(grad_mask).count("1"), \
            f"gradient HDMA not torn down (grad {grad_mask:08b} -> plx {plx_mask:08b})"
        assert indicator_tile() == SF_OBJG_P, "arena indicator not showing P (parallax)"


def test_hud_oam_budget_guard(runner):
    """F4: the HUD top+meter+arena+bar must fit OBJ 0-47 (the field forces base
    48). The overflow guard flag (SHOW_OAM_OVF) must stay 0 for the compliant
    Mode-1 page across the worst frame (every slot, max field count)."""
    with runner.frame_stepping():
        _to_demo(runner)
        # crank the field to max so the HUD draws its busiest frame too
        _goto_slot(runner, 4)                 # FIELD slot; count = param 0 (</>)
        runner.frame_step(120, right=True)
        runner.frame_step(4)
        # sweep every option slot (each renders a different label/tag set)
        for _ in range(6):
            _tap(runner, select=True)
            runner.frame_step(3)
            assert runner.read_bytes(WR, OAM_OVF, 1)[0] == 0, \
                "HUD OAM budget overflowed 48 (compliant page must fit)"


def test_sram_multislot_roundtrip_render():
    """F9+F11: two SRAM SLOTS hold distinct configs; each round-trips across a
    power cycle and reproduces the RIGHT rendered frame. Save config X (high blue
    color-math tint) to slot 0 and config Y (low tint) to slot 1; power-cycle;
    recall each into the live demo and assert the RECALLED FRAME matches the
    config that was saved (screenshot diff), not just the WRAM value."""
    from pathlib import Path as _P
    from infrastructure.test_harness import mesen_runner as _mr
    srm = _P(_mr._DEFAULT_HOME_DIR) / "Saves" / "mode_showcase.srm"
    if srm.exists():
        srm.unlink()
    rom = str(BUILD / "mode_showcase.sfc")
    r = MesenRunner()
    try:
        # --- run 1: tune + save two distinct configs to slots 0 and 1 ---
        r.load_rom(rom, run_seconds=0.5)
        with r.frame_stepping():
            _to_demo(r)
            # slot 0 (CMATH) active. CMATH B = param 3 -> Y(dec)/X(inc). Raise B.
            r.frame_step(24, x=True); r.frame_step(4)
            x_b = r.read_bytes(WR, KNOB_VAL + KN_CMATH_B, 1)[0]
            _tap(r, start=True, select=True)              # sheet (slot sel = 0)
            _tap(r, a=True)                               # save -> SRAM slot 0
            _tap(r, r=True)                               # select SRAM slot 1
            assert r.read_bytes(WR, SAVE_SLOT_SEL, 1)[0] == 1
            _tap(r, start=True, select=True)              # leave -> demo
            r.frame_step(6)
            # lower CMATH B for slot 1 (Y dec)
            r.frame_step(40, y=True); r.frame_step(4)
            y_b = r.read_bytes(WR, KNOB_VAL + KN_CMATH_B, 1)[0]
            _tap(r, start=True, select=True)              # sheet (sel still 1)
            _tap(r, r=True); _tap(r, l=True)              # ensure sel = 1 (no-op cycle)
            # sel may have re-entered at the persisted value; force to 1
            while r.read_bytes(WR, SAVE_SLOT_SEL, 1)[0] != 1:
                _tap(r, r=True)
            _tap(r, a=True)                               # save -> SRAM slot 1
            r.debug_resume()
        assert x_b != y_b, f"setup: slot configs not distinct ({x_b} vs {y_b})"

        # --- run 2: power cycle, recall slot 0, capture frame ---
        r.load_rom(rom, run_seconds=0.5)
        with r.frame_stepping():
            _to_demo(r)
            _tap(r, start=True, select=True)              # sheet (sel = 0)
            _tap(r, b=True)                               # recall slot 0
            _tap(r, start=True, select=True)              # leave -> apply
            r.frame_step(8)
            rec0 = r.read_bytes(WR, KNOB_VAL + KN_CMATH_B, 1)[0]
            r.take_screenshot("/tmp/ms_slot0_recall.png")
            # recall slot 1
            _tap(r, start=True, select=True)              # sheet (sel reset to 0)
            while r.read_bytes(WR, SAVE_SLOT_SEL, 1)[0] != 1:
                _tap(r, r=True)
            _tap(r, b=True)                               # recall slot 1
            _tap(r, start=True, select=True)
            r.frame_step(8)
            rec1 = r.read_bytes(WR, KNOB_VAL + KN_CMATH_B, 1)[0]
            r.take_screenshot("/tmp/ms_slot1_recall.png")
    finally:
        r.stop()
    # WRAM round-trip: each slot restored its OWN config
    assert rec0 == x_b, f"slot 0 round-trip: saved {x_b}, recalled {rec0}"
    assert rec1 == y_b, f"slot 1 round-trip: saved {y_b}, recalled {rec1}"
    # RENDER round-trip (F9): the two recalled frames differ (distinct tints)
    f0 = list(_load("/tmp/ms_slot0_recall.png").get_flattened_data())
    f1 = list(_load("/tmp/ms_slot1_recall.png").get_flattened_data())
    diff = sum(1 for i in range(0, len(f1), 7) if f1[i] != f0[i])
    assert diff > 100, f"recalled slot frames did not differ in pixels ({diff})"


# --- S1.5 DISPATCH (deliverable 10) ------------------------------------------
SHADOW_BGMODE = 0x012C        # engine BGMODE shadow — the value the NMI commits
                              # to PPU $2105 each frame (the rendered BGMODE; the
                              # live $2105 is write-only, so the committed shadow
                              # IS the OUTPUT read, as test_rpg/test_mode3 do).


def _frame_diff(path_a, path_b):
    a = list(_load(path_a).get_flattened_data())
    b = list(_load(path_b).get_flattened_data())
    return sum(1 for i in range(0, len(a), 7) if a[i] != b[i])


def _quad_hue(img, quad):
    """Count warm (red/yellow) vs cool (blue/green) pixels in ONE fixed screen
    quadrant of a Mode-0 frame. `quad` is "TL"/"BL"/"BR" (one BG-band quadrant;
    TR overlaps the sprite field + is not used). The quadrant boxes sit INSIDE the
    BG band (below the F-6 dark HUD strip y<48, above the slot bar y>200).

    Phase-invariance: this is read in the QUADRANT structural preset (PRS=1), where
    each plane is confined to its OWN fixed quadrant and the parallax auto-drift is
    OFF (m0_preset_apply STACK->QUAD forces M0K_AUTO=0 and zeroes the scroll
    shadows). So the pixels in a fixed quadrant do NOT depend on scroll phase — the
    stacked preset's full-screen overlap (where the visible 'dominant hue' flips
    with scroll alignment, the old flake) is gone. The priority-shuffle still
    permutes which plane (hue) occupies each quadrant, so a fixed quadrant's
    dominant hue SWAPPING warm<->cool is a scroll-invariant rendered proof that a
    DIFFERENT plane now draws there (the front-plane reorder, F-7)."""
    w, h = img.size
    px = img.load()
    boxes = {                              # (x0, x1, y0, y1) within the BG band
        "TL": (0, w // 2, 56, 120),
        "BL": (0, w // 2, 128, 196),
        "BR": (w // 2, w, 128, 196),
    }
    x0, x1, y0, y1 = boxes[quad]
    warm = cool = 0
    for y in range(y0, y1, 2):
        for x in range(x0, x1, 2):
            r, g, b = px[x, y][:3]
            if r < 90 and g < 90 and b < 90:
                continue                      # backdrop / dark
            if r > 120 and b < 110:           # red (low g) or yellow (high g) -> warm
                warm += 1
            elif r < 110 and (b > 120 or g > 120):  # blue or green -> cool
                cool += 1
    return warm, cool


def test_dispatch_selects_mode_and_renders(runner):
    """The menu selects a mode and the demo enters the SELECTED mode via the
    DISPATCH layer (not always Mode 1). Reads RENDERED OUTPUT: SHOW_CUR_MODE +
    the committed BGMODE shadow (= the byte the NMI writes to $2105) + a
    screenshot that differs from Mode 1. Proves >=2 distinct non-Mode-1 modes
    dispatch with distinct BGMODE and distinct frames."""
    # Mode 1 reference frame + its committed BGMODE ($09 = Mode 1 + BG3 priority).
    with runner.frame_stepping():
        _to_demo(runner, mode=1)
        assert runner.read_bytes(WR, CUR_MODE, 1)[0] == 1, "Mode 1 not selected"
        bg1 = runner.read_bytes(WR, SHADOW_BGMODE, 1)[0]
        assert bg1 == 0x09, f"Mode 1 BGMODE shadow not $09 (got ${bg1:02X})"
        runner.take_screenshot("/tmp/ms_dispatch_m1.png")
    assert _count(_load("/tmp/ms_dispatch_m1.png"), _WHITE) > 100, \
        "Mode 1 HUD not rendered (dispatch broke the proven page)"


def test_dispatch_two_other_modes(runner):
    """A SECOND boot enters Mode 3 (256-color) then a THIRD enters Mode 2 (warp)
    via dispatch. Each has a distinct committed BGMODE and a distinct rendered
    frame vs Mode 1 — proof the dispatch fans out across modes (>=2 non-Mode-1).
    Fresh boot per mode (the fixture is per-test; here we drive extra boots)."""
    rom = str(BUILD / "mode_showcase.sfc")
    results = {}
    for mode, want_bg, tag in [(1, 0x09, "m1"), (3, 0x03, "m3"), (2, 0x02, "m2")]:
        r = MesenRunner()
        try:
            r.load_rom(rom, run_seconds=0.5)
            with r.frame_stepping():
                _to_demo(r, mode=mode)
                cm = r.read_bytes(WR, CUR_MODE, 1)[0]
                bg = r.read_bytes(WR, SHADOW_BGMODE, 1)[0]
                r.take_screenshot(f"/tmp/ms_dispatch_{tag}.png")
            results[mode] = (cm, bg)
            assert cm == mode, f"dispatch entered mode {cm}, expected {mode}"
            assert bg == want_bg, \
                f"mode {mode} committed BGMODE ${bg:02X}, expected ${want_bg:02X}"
        finally:
            r.stop()
    # The committed BGMODE differs across all three modes (distinct PPU $2105
    # state per dispatched mode): Mode 1=$09, Mode 3=$03, Mode 2=$02. This is the
    # per-mode OUTPUT proof that the dispatch enters a DIFFERENT engine_gfxmode.
    bgs = {results[m][1] for m in (1, 3, 2)}
    assert len(bgs) == 3, f"BGMODE shadows not all distinct: {bgs}"
    # The rendered frames differ from Mode 1's rich page: both stub demos (2 and
    # 3) are visibly distinct from Mode 1 — proof >=2 non-Mode-1 modes dispatch
    # to their own rendered frame. (Mode 2 vs Mode 3 share the generic stub's BG
    # content at the pixel level — only their BGMODE differs, asserted above —
    # until the fan-out replaces each stub with real per-mode content.)
    d31 = _frame_diff("/tmp/ms_dispatch_m3.png", "/tmp/ms_dispatch_m1.png")
    d21 = _frame_diff("/tmp/ms_dispatch_m2.png", "/tmp/ms_dispatch_m1.png")
    assert d31 > 100, f"Mode 3 frame not distinct from Mode 1 (diff={d31})"
    assert d21 > 100, f"Mode 2 frame not distinct from Mode 1 (diff={d21})"


def test_dispatch_stub_knob_tunes(runner):
    """A stub mode is a REAL minimal page: its registered knobs drive the frame.
    Enter Mode 0 (a stub), tune the brightness knob (slot 2, param 0) DOWN, and
    the live value changes AND the frame darkens (screenshot diff) — proof the
    generic HUD/router/meter compose the ACTIVE mode's resolved tables."""
    KN_STUB_BRT = 10           # stub slot 2 param 0 = brightness (def 15)
    with runner.frame_stepping():
        _to_demo(runner, mode=0)
        assert runner.read_bytes(WR, CUR_MODE, 1)[0] == 0, "Mode 0 (stub) not selected"
        runner.take_screenshot("/tmp/ms_stub_bright.png")
        # slot 2 = LIGHT (2 Select taps from slot 0). Param 0 (BRT) on </>: LEFT
        # decrements (held ramps it down).
        for _ in range(2):
            _tap(runner, select=True)
        assert runner.read_bytes(WR, ACTIVE_SLOT, 1)[0] == 2
        brt0 = runner.read_bytes(WR, KNOB_VAL + KN_STUB_BRT, 1)[0]
        runner.frame_step(20, left=True)
        runner.frame_step(4)
        brt1 = runner.read_bytes(WR, KNOB_VAL + KN_STUB_BRT, 1)[0]
        assert brt1 < brt0, f"stub brightness knob did not fall ({brt0}->{brt1})"
        runner.take_screenshot("/tmp/ms_stub_dark.png")
    # the frame darkened (brightness drop changes many pixels)
    diff = _frame_diff("/tmp/ms_stub_bright.png", "/tmp/ms_stub_dark.png")
    assert diff > 100, f"stub knob change did not alter the frame (diff={diff})"


# --- MODE 0 "PLANES" per-mode page (fan-out PILOT) ---------------------------
# Reads RENDERED OUTPUT (committed BGMODE shadow + screenshot pixels), never
# proxies. Mode 0 is no longer a stub: it is the real four-4-color-BG-layer page.
# Slot map (showcase_mode0.inc): 0 PARX, 1 PARY, 2 LIGHT, 3 PAL, 4 FIELD,
# 5 FRAME(PRS,ORD,BDK). Knob index = slot*5 + param.
M0_KN_B1X     = 0            # slot 0 param 0 = BG1 X scroll (</> pair)
M0_KN_BRT     = 10           # slot 2 param 0 = brightness
M0_KN_PRESET  = 25          # slot 5 param 0 = structural preset (</> pair)
M0_KN_PRIORDER= 26          # slot 5 param 1 = PRIORITY-SHUFFLE (v/^ pair)


def test_mode0_active_and_distinct():
    """Mode 0 dispatches: the committed BGMODE shadow's low 3 bits are 0 (Mode 0)
    and the rendered frame is DISTINCT from Mode 1. Reads the BGMODE shadow (the
    byte the NMI writes to $2105 — the rendered BGMODE) + a screenshot diff vs a
    fresh Mode-1 boot. (Own boots so both frames are captured deterministically.)"""
    rom = str(BUILD / "mode_showcase.sfc")
    # Mode 0 frame + BGMODE
    r = MesenRunner()
    try:
        r.load_rom(rom, run_seconds=0.5)
        with r.frame_stepping():
            _to_demo(r, mode=0)
            assert r.read_bytes(WR, CUR_MODE, 1)[0] == 0, "Mode 0 not selected"
            bg0 = r.read_bytes(WR, SHADOW_BGMODE, 1)[0]
            assert (bg0 & 0x07) == 0, f"Mode 0 BGMODE low-3 not 0 (${bg0:02X})"
            r.take_screenshot("/tmp/ms_m0_demo.png")
    finally:
        r.stop()
    # the 4-layer scene renders rich colour (red/blue/yellow planes) — not blank
    img = _load("/tmp/ms_m0_demo.png")
    nonblack = _count(img, lambda p: p[0] + p[1] + p[2] > 60)
    assert nonblack > 5000, f"Mode 0 four-plane scene not rendered ({nonblack})"
    # Mode 1 reference frame
    r = MesenRunner()
    try:
        r.load_rom(rom, run_seconds=0.5)
        with r.frame_stepping():
            _to_demo(r, mode=1)
            r.take_screenshot("/tmp/ms_m1_ref.png")
    finally:
        r.stop()
    diff = _frame_diff("/tmp/ms_m0_demo.png", "/tmp/ms_m1_ref.png")
    assert diff > 1000, f"Mode 0 frame not distinct from Mode 1 (diff={diff})"


def test_mode0_heartbeat_60fps(runner):
    """The PPU frame counter advances exactly 1 per stepped frame in Mode 0 (the
    per-frame scroll/parallax path holds 60fps — no drops)."""
    with runner.frame_stepping():
        _to_demo(runner, mode=0)
        f0 = runner.ppu_frame_count()
        runner.frame_step(12)
        f1 = runner.ppu_frame_count()
    assert f1 - f0 == 12, f"Mode 0 heartbeat slipped: {f1 - f0} for 12 steps"


def test_mode0_scroll_knob_changes_frame(runner):
    """A representative knob (PARX slot, BG1 X scroll) visibly changes the frame.
    Slot 0 is active by default; param 0 (B1X) is on </>. Drive RIGHT to scroll
    the front layer; the rendered frame shifts (pixel diff)."""
    with runner.frame_stepping():
        _to_demo(runner, mode=0)
        # freeze the auto-drift first so the diff is the KNOB's doing, not the
        # parallax animation: slot 0 param 4 = AUTO (L/R pair); L decrements to 0.
        runner.frame_step(10, l=True)
        runner.frame_step(6)
        runner.take_screenshot("/tmp/ms_m0_scroll0.png")
        b1x0 = runner.read_bytes(WR, KNOB_VAL + M0_KN_B1X, 1)[0]
        runner.frame_step(20, right=True)       # ramp BG1 X scroll (held)
        runner.frame_step(6)
        b1x1 = runner.read_bytes(WR, KNOB_VAL + M0_KN_B1X, 1)[0]
        assert b1x1 != b1x0, f"BG1 X scroll knob did not move ({b1x0}->{b1x1})"
        runner.take_screenshot("/tmp/ms_m0_scroll1.png")
    diff = _frame_diff("/tmp/ms_m0_scroll0.png", "/tmp/ms_m0_scroll1.png")
    assert diff > 100, f"scroll knob did not visibly change the frame (diff={diff})"


def test_mode0_priority_shuffle_reorders_planes(runner):
    """The headline PRIORITY-SHUFFLE knob (slot 5 FRAME, param 1 ORD on v/^)
    reorders which plane draws FRONT-MOST — not merely 'pixels changed' (F-7).

    PHASE-INVARIANT measurement (the fix for the old flake): we measure in the
    QUADRANT structural preset (PRS=1), where each of the four planes is confined
    to its OWN fixed screen quadrant AND the parallax auto-drift is OFF (the QUAD
    re-author forces M0K_AUTO=0 and zeroes the scroll shadows). That removes the
    scroll dependence that made the STACKED preset's full-screen overlap flip its
    visible 'dominant hue' with scroll alignment (the ~20% flake). With static,
    non-overlapping quadrants the priority-shuffle permutes WHICH plane (hue) owns
    each quadrant, so a FIXED quadrant's dominant hue swapping warm<->cool is a
    deterministic, scroll-invariant rendered proof that a DIFFERENT plane now draws
    front-most there.

    Plane hues (PAL defaults): A=blue(cool) B=green(cool) C=red(warm) D=yellow
    (warm). m0_order_lut reverses the order 0->3, so each quadrant's plane (hence
    hue) changes. We assert THREE fixed quadrants each swap their dominant hue
    group in the expected direction (TL cool->warm, BL warm->cool, BR warm->cool):
    multiple quadrants flipping proves a genuine reorder, not a single recolour.
    Reads RENDERED pixels in fixed quadrants, never a proxy."""
    with runner.frame_stepping():
        _to_demo(runner, mode=0)
        _goto_slot(runner, 5)                    # FRAME slot (PRS/ORD/BDK)
        # Enter the QUADRANT preset (PRS = param 0 on </>; RIGHT 0 -> 1). This makes
        # the scene static (auto-drift off) and confines each plane to one quadrant,
        # so the measurement below is scroll-phase invariant.
        _tap(runner, right=True)
        runner.frame_step(14)                    # let the re-author + render settle
        assert runner.read_bytes(WR, KNOB_VAL + M0_KN_PRESET, 1)[0] == 1, \
            "quadrant preset (PRS=1) did not engage"
        ord0 = runner.read_bytes(WR, KNOB_VAL + M0_KN_PRIORDER, 1)[0]
        runner.take_screenshot("/tmp/ms_m0_ord0.png")
        # ORD param 1 -> UP increments; drive to the reversed order (3).
        for _ in range(3):
            _tap(runner, up=True)
        runner.frame_step(10)
        ord3 = runner.read_bytes(WR, KNOB_VAL + M0_KN_PRIORDER, 1)[0]
        assert ord3 > ord0, f"priority-shuffle knob did not advance ({ord0}->{ord3})"
        runner.take_screenshot("/tmp/ms_m0_ord3.png")

    img0 = _load("/tmp/ms_m0_ord0.png")
    img3 = _load("/tmp/ms_m0_ord3.png")

    # (1) the frame changed at all (cheap global guard)
    diff = _frame_diff("/tmp/ms_m0_ord0.png", "/tmp/ms_m0_ord3.png")
    assert diff > 1000, \
        f"priority-shuffle did not visibly change the frame (diff={diff})"

    # (2) the SPECIFIC effect: each fixed quadrant's dominant hue group SWAPS,
    #     proving a DIFFERENT plane draws there. A reframe that did NOT reorder
    #     would keep the same plane (hue) in each quadrant and fail every swap.
    #     Directions (verified empirically across boots/phases):
    #       TL: cool (plane A blue) @ORD0 -> warm   @ORD3
    #       BL: warm (plane C red)  @ORD0 -> cool   @ORD3
    #       BR: warm (plane D yellow)@ORD0 -> cool  @ORD3
    expect = {"TL": ("cool", "warm"), "BL": ("warm", "cool"), "BR": ("warm", "cool")}
    MIN = 120                                     # solid quadrant fill ~ 480+ px
    for quad, (g0, g3) in expect.items():
        w0, c0 = _quad_hue(img0, quad)
        w3, c3 = _quad_hue(img3, quad)
        dom0 = "warm" if w0 > c0 * 3 else "cool" if c0 > w0 * 3 else "mixed"
        dom3 = "warm" if w3 > c3 * 3 else "cool" if c3 > w3 * 3 else "mixed"
        assert max(w0, c0) > MIN and max(w3, c3) > MIN, \
            f"{quad} quadrant not painted (ORD0 {w0}/{c0}, ORD3 {w3}/{c3})"
        assert dom0 == g0, (
            f"{quad} quadrant not {g0}-dominant @ORD0 (warm={w0} cool={c0}); "
            "front-plane premise broken"
        )
        assert dom3 == g3, (
            f"{quad} quadrant did not swap to {g3}-dominant @ORD3 "
            f"(warm={w3} cool={c3}); priority-shuffle did NOT reorder the front "
            f"plane in {quad} (stayed {dom3})"
        )


def test_mode0_preset_selector_reframes(runner):
    """The preset selector (slot 5 FRAME, param 0 PRS on </>) re-frames the scene
    from stacked multi-plane parallax (0) to 4-quadrant layer isolation (1). The
    rendered frame changes substantially (each plane confined to a quadrant)."""
    with runner.frame_stepping():
        _to_demo(runner, mode=0)
        _goto_slot(runner, 5)
        runner.frame_step(6)
        runner.take_screenshot("/tmp/ms_m0_presetA.png")
        # PRS = param 0 (</>) ; RIGHT increments 0 -> 1 (quadrant)
        _tap(runner, right=True)
        runner.frame_step(14)                    # let the re-author + render settle
        prs = runner.read_bytes(WR, KNOB_VAL + M0_KN_PRESET, 1)[0]
        assert prs == 1, f"preset selector did not advance to quadrant ({prs})"
        runner.take_screenshot("/tmp/ms_m0_presetB.png")
    diff = _frame_diff("/tmp/ms_m0_presetA.png", "/tmp/ms_m0_presetB.png")
    assert diff > 1000, f"preset selector did not re-frame the scene (diff={diff})"
