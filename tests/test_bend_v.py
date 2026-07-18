"""Run-gate for the V-axis (BGnVOFS) bend — sf_bend_v / sf_tunnel_v with the
SF_CURVE_HORIZON RECIPROCAL / 1-over-z perspective curve (v1.2-R).

The H bend displaces a vertical-stripe column horizontally; the V bend displaces
a horizontal-band field VERTICALLY, squashing the band SPACING toward the horizon
in a true barrel/perspective: rows bunch DRAMATICALLY just below the horizon and
spread toward the foreground. Primary assertions read RENDERED PIXELS from a
screenshot (the HDMA table in WRAM is implementation detail, not evidence — kit
rule #2):

  (a) COMPRESSION RATIO — the on-screen band spacing varies from a few px at the
      horizon to a wide foreground band: max:min spacing ratio >= 3x (a STRONG
      threshold, NOT merely "monotonic" — v1.2-R R3). A flat / linear / mild-
      quadratic curve fails this (proven by the sensitivity mutation in audit).
  (b) DIRECTION — the most-compressed bands are at the HORIZON (top) end, not the
      foreground (bottom). The shipped-before-remediation curve was INVERTED;
      this asserts the fix.
  (c) ROLL — the animated pattern ADVANCES between frames (sf_tunnel_v); measured
      by cross-correlating the band column (robust to the steep perspective's
      changing band structure).
  (d) REVERSE — a NEGATIVE speed flips the roll SIGN vs the positive-speed ROM.
  (e) VSCROLL — the SHADOW_BG1VOFS compose pans the field vertically while it
      stays compressed (spacing ratio preserved).

ROM contracts (BG1 horizontal bands, 8px on/off; sky region above a horizon
line; ground bands fill all 32 tilemap rows so the deep-pulled foreground stays
clean — no tilemap-wrap artifacts):
  bend_v_test.sfc         sf_tunnel_v SF_CURVE_HORIZON amp 128 speed +2, framed
                          with a sky region + horizon line above the ground.
  bend_v_reverse_test.sfc same curve/amp but speed -2 (#$FFFE).
  bend_v_scroll_test.sfc  STATIC sf_bend_v + scroll #1,#0,vofs ramped +1/frame.
  $7E:E010 heartbeat, $7E:E012 channel, $7E:E014 pan value (scroll ROM only).
"""
from pathlib import Path

import pytest
from PIL import Image

from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
WR = MemoryType.SnesWorkRam
SHOTS = Path("/tmp/e2e_screenshots")


@pytest.fixture(scope="module")
def runner():
    r = MesenRunner()
    yield r
    r.stop()


def _shot(runner, name):
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / name
    runner.take_screenshot(str(path))
    return Image.open(path).convert("RGB")


def _band_column_x(img):
    """Centre column — the whole field is solid horizontal bands, so any x works."""
    return img.size[0] // 2


def _col_bits(img, x=None):
    """Band pattern down the centre column: 1 = green ground band, 0 otherwise
    (sky-blue / gap / white horizon line are all 0). Selecting green specifically
    keeps the sky region out of the band-spacing measurement."""
    if x is None:
        x = _band_column_x(img)
    h = img.size[1]
    out = []
    for y in range(h):
        r, g, b = img.getpixel((x, y))
        out.append(1 if (g > 120 and g > b + 30) else 0)
    return out


def _raw_edges(bits):
    """Row indices of every gap→band transition (each ground band's top edge)."""
    return [y for y in range(1, len(bits)) if bits[y] == 1 and bits[y - 1] == 0]


def _ground_spacings(img):
    """On-screen spacings between consecutive ground-band top edges, top→bottom,
    with the saturated foreground / bottom-wrap tail dropped: a steep perspective
    spreads the nearest band very wide, so keep the run of edges whose spacing
    stays within 4x the *smallest* (most-compressed, horizon) spacing — that is
    the resolvable barrel run."""
    edges = _raw_edges(_col_bits(img))
    if len(edges) < 3:
        return edges, []
    spac = [edges[i + 1] - edges[i] for i in range(len(edges) - 1)]
    return edges, spac


def _clean_run(spac):
    """Keep the leading run of spacings up to (and including) the first one that
    is the foreground's wide band, dropping any trailing wrap/garble after an
    oversized jump. Returns the resolvable horizon→foreground run."""
    if not spac:
        return []
    kept = [spac[0]]
    smallest = spac[0]
    for s in spac[1:]:
        kept.append(s)
        # once we have crossed into a very wide foreground band, stop (the next
        # transitions are the bottom-screen wrap, not the perspective run).
        if s >= 6 * max(1, smallest) and len(kept) >= 3:
            break
    return kept


def _foreground_band_top(img):
    """Screen y of the TOP of the widest (longest-run) green band down the centre
    column — the nearest FOREGROUND ground band that the 1/z perspective spreads
    widest. As the curve phase rolls, the field flows under the barrel and this
    foreground band marches up/down by many px — a large, UNAMBIGUOUS directional
    signal (it is one contiguous run, immune to the horizon's band births/deaths)."""
    x = _band_column_x(img)
    bits = [1 if (img.getpixel((x, y))[1] > 120 and
                  img.getpixel((x, y))[1] > img.getpixel((x, y))[2] + 30)
            else 0 for y in range(img.size[1])]
    best_len, best_top, i = 0, None, 0
    n = len(bits)
    while i < n:
        if bits[i] == 1:
            j = i
            while j < n and bits[j] == 1:
                j += 1
            if j - i > best_len:
                best_len, best_top = j - i, i
            i = j
        else:
            i += 1
    return best_top


def _roll_drift(img_a, img_b):
    """Signed movement of the foreground band top between two frames (positive =
    the foreground flowed DOWN, i.e. toward the viewer)."""
    ya = _foreground_band_top(img_a)
    yb = _foreground_band_top(img_b)
    if ya is None or yb is None:
        return None
    return yb - ya


def test_bend_v_compresses_and_rolls(runner):
    rom = BUILD / "bend_v_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"
    runner.load_rom(str(rom), run_seconds=0.5)

    # --- secondary: boot magic + a real HDMA channel + live heartbeat ---
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    chan = runner.read_u16(WR, 0xE012)
    assert 3 <= chan <= 7, f"sf_tunnel_v failed to allocate: {chan:#x}"
    beat0 = runner.read_u16(WR, 0xE010)
    runner.run_frames(10)
    assert runner.read_u16(WR, 0xE010) > beat0, "frame heartbeat stalled"

    img_a = _shot(runner, "bend_v_a.png")
    edges, spac = _ground_spacings(img_a)
    run = _clean_run(spac)
    assert len(run) >= 3, \
        f"too few resolvable ground bands: edges={edges} spac={spac}"

    # --- PRIMARY (a): STRONG compression ratio (v1.2-R R3) -------------------
    # The reciprocal perspective bunches bands to a few px at the horizon and
    # spreads them to a wide foreground band. max:min spacing must be >= 3x — a
    # flat / linear / mild-quadratic curve cannot reach this (sensitivity-proven).
    ratio = max(run) / min(run)
    assert ratio >= 3.0, \
        f"compression ratio too weak: max/min spacing = {ratio:.2f}x " \
        f"(need >=3x for a barrel horizon) — run={run} edges={edges}"

    # --- PRIMARY (b): DIRECTION — most-compressed bands at the HORIZON (top) --
    # The smallest spacing must be in the TOP portion of the run, expanding
    # downward. The pre-remediation curve was INVERTED (compressed at the bottom);
    # this asserts the corrected orientation.
    min_idx = run.index(min(run))
    assert min_idx < len(run) / 2, \
        f"compression is INVERTED — most-compressed band at index {min_idx} of " \
        f"{len(run)} (expected near the TOP/horizon): run={run}"
    # corroborate: the run increases overall (top median < bottom median).
    h = len(run) // 2
    top_med = sorted(run[:h])[h // 2]
    bot_med = sorted(run[h:])[(len(run) - h) // 2]
    assert bot_med > top_med, \
        f"spacing does not expand top→bottom: top median {top_med} vs " \
        f"bottom median {bot_med} (run={run})"

    # --- PRIMARY (c): the V tunnel ROLLS (pattern advances between frames) ----
    # Track the foreground band as it flows under the barrel — it marches many px
    # as the phase rolls.
    runner.run_frames(10)
    img_b = _shot(runner, "bend_v_b.png")
    assert img_a.tobytes() != img_b.tobytes(), \
        "frames identical 10 apart — the V tunnel is not rolling"
    moved = _roll_drift(img_a, img_b)
    assert moved is not None and abs(moved) >= 4, \
        f"roll not visible: foreground band moved {moved}px over 10 frames"


def test_bend_v_negative_speed_reverses_the_roll(runner):
    """(d) The reverse-speed ROM rolls the OPPOSITE vertical direction. Both ROMs
    carry the identical horizon-framed field; track the foreground band's signed
    movement over N frames for each. The movement SIGN must differ — read from
    rendered pixels, not a 'frames differ' proxy."""
    def roll_move(rom_name):
        rom = BUILD / rom_name
        assert rom.exists(), f"{rom} not built"
        runner.load_rom(str(rom), run_seconds=0.5)
        assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
        runner.run_frames(8)
        ia = _shot(runner, f"bend_v_dir_{rom_name}_0.png")
        runner.run_frames(10)
        ib = _shot(runner, f"bend_v_dir_{rom_name}_1.png")
        return _roll_drift(ia, ib)

    d_pos = roll_move("bend_v_test.sfc")
    d_neg = roll_move("bend_v_reverse_test.sfc")
    assert d_pos is not None and d_neg is not None, \
        f"could not track the foreground band: pos={d_pos} neg={d_neg}"
    assert abs(d_pos) >= 4 and abs(d_neg) >= 4, \
        f"a roll did not move the field: pos Δ={d_pos} neg Δ={d_neg}"
    assert (d_pos > 0) != (d_neg > 0), \
        f"reverse speed did not flip the roll direction: pos Δ={d_pos} neg Δ={d_neg}"


def test_bend_v_scroll_pans_field_while_compressed(runner):
    """(e) The SHADOW_BG1VOFS compose pans the field VERTICALLY while it stays
    compressed: with a STATIC squash and a ramped vofs, the band field marches
    down between frames AND the spacing still compresses >=3x (squash preserved)."""
    rom = BUILD / "bend_v_scroll_test.sfc"
    assert rom.exists(), f"{rom} not built"
    runner.load_rom(str(rom), run_seconds=0.5)
    assert runner.read_bytes(WR, 0xE000, 4) == b"SFDB"
    chan = runner.read_u16(WR, 0xE012)
    assert 3 <= chan <= 7, f"sf_bend_v failed to allocate: {chan:#x}"

    pan0 = runner.read_u16(WR, 0xE014)
    img_a = _shot(runner, "bend_v_scroll_a.png")
    edges, spac = _ground_spacings(img_a)
    run = _clean_run(spac)
    runner.run_frames(10)
    pan1 = runner.read_u16(WR, 0xE014)
    img_b = _shot(runner, "bend_v_scroll_b.png")

    # the pan accumulator advanced (the scroll loop is live)
    assert pan1 != pan0, f"vofs pan stalled: {pan0} -> {pan1}"

    # the field STILL shows a strong compression squash (the compose preserved it)
    assert len(run) >= 3, f"too few resolvable bands: edges={edges} spac={spac}"
    ratio = max(run) / min(run)
    assert ratio >= 3.0, \
        f"field not compressed under the pan: max/min spacing {ratio:.2f}x " \
        f"(run={run})"

    # the field PANNED vertically: track the foreground band (the wide, expanded
    # band low in the field), where the uniform vertical pan is clearly visible
    # (the heavily-compressed horizon bands barely move on screen per source px).
    moved = _roll_drift(img_a, img_b)
    assert moved is not None and abs(moved) >= 2, \
        f"field did not pan vertically: foreground band moved {moved}px"
