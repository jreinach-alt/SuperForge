"""mtap — players 3 and 4 behind a four-pad adapter in port 2 (docs/102 MT-1..MT-7).

THE ROM UNDER TEST is `tests/fixtures/mtap_probe/`: the input stack
(`input` + `input2` + `mtap`) composed ALONE — no scene manager, no display,
no game — built by `make mtap-probe` with the same allocator / no_literals /
ca65 / ld65 steps a rail's Makefile block runs. Its frame loop calls `mtap_read` the
instant VBlank begins, BEFORE the automatic read has started: the race
docs/102 D7 names, so every correct read below is also a proof of the guard.
It then asks `pad_btn` / `pad_btnp` about players 5..0 with every button bit
set and records the answers.

THE OUTPUT REGIONS: the DP words `mtap` (and `input` / `input2`) write —
the feature's whole output — and the `pad_btn` / `pad_btnp` answers the probe
recorded. The harness this stands on is proved separately, on a ROM with no
engine code at all (`test_mtap_harness.py`).

THE PAD SCRIPT IS THE INPUT, THE WORDS ARE THE OUTPUT, AND EVERY ASSERTION
NAMES ALL FOUR PLAYERS. A press is required to land in its own player's word
AND to be absent from the other three, because the failure this class has is
a crossed or leaked wire, not a missing one.
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
MAP_DIR = BUILD / "mtap_probe"
ROM = BUILD / "mtap_probe.sfc"
W = MemoryType.SnesWorkRam

# The JOY1 word layout (fullsnes; docs/102 §2) — the order a pad shifts out.
BITS = {"b": 15, "y": 14, "select": 13, "start": 12, "up": 11, "down": 10,
        "left": 9, "right": 8, "a": 7, "x": 6, "l": 5, "r": 4}
CUR = ["ES_INP_CUR", "ES_INP2_CUR", "ES_INP3_CUR", "ES_INP4_CUR"]
PRESS = ["ES_INP_PRESS", "ES_INP2_PRESS", "ES_INP3_PRESS", "ES_INP4_PRESS"]
BOOT = 20


@pytest.fixture(scope="module")
def addr():
    """Build the probe (`make mtap-probe`); answer {symbol: DP offset}."""
    r = run_make("mtap-probe")
    assert r.returncode == 0, f"make mtap-probe failed:\n{r.stdout}\n{r.stderr}"
    jmap = json.loads((MAP_DIR / "symbol_map.json").read_text())
    return {p["sym"]: p["start"] for p in jmap["globals"]}


@pytest.fixture(autouse=True)
def hand_back_the_core():
    yield
    Machine.close_current()


def _boot(port2):
    return Machine(str(ROM), port2=port2).advance(BOOT)


def _words(m, addr, names):
    return [m.read_u16(W, addr[n]) for n in names]


def _answers(m, addr):
    """pad_btn / pad_btnp answers for players 0..5, plus pad_btn's Z flags."""
    held = m.read_bytes(W, addr["US_HELD"], 12)
    press = m.read_bytes(W, addr["US_PRESS"], 12)
    w = lambda b, i: b[2 * i] | (b[2 * i + 1] << 8)
    return ([w(held, i) for i in range(6)], [w(press, i) for i in range(6)],
            m.read_u16(W, addr["US_ZFLAG"]))


def _pads(player, button):
    return {f"pad{player + 1}": {button: True}}


# =============================================================================
# MT-1 — detection, both ways
# =============================================================================
def test_detection_sets_the_flag_with_an_adapter_and_clears_it_without(addr):
    m = _boot(mr.PORT2_MULTITAP)
    assert m.read_u16(W, addr["US_FRAMES"]) >= BOOT - 2, "the probe loop stalled"
    assert m.read_u16(W, addr["ES_MTAP_ON"]) == 1
    m.close()
    m = _boot(mr.PORT2_PAD)
    assert m.read_u16(W, addr["US_FRAMES"]) >= BOOT - 2, "the probe loop stalled"
    assert m.read_u16(W, addr["ES_MTAP_ON"]) == 0


# =============================================================================
# MT-2 + MT-6 — every button of every player lands in that player's word only,
# and pad_btn / pad_btnp agree with the words for 0-3 and answer 0 for 4-5
# =============================================================================
@pytest.mark.parametrize("player", [0, 1, 2, 3])
def test_every_button_lands_in_its_own_players_word_only(addr, player):
    m = _boot(mr.PORT2_MULTITAP)
    for button, bit in BITS.items():
        m.advance(2, **_pads(player, button))
        want = [1 << bit if p == player else 0 for p in range(4)]
        got = _words(m, addr, CUR)
        assert got == want, (
            f"player {player + 1} '{button}': cur words "
            f"{[hex(v) for v in got]}, want {[hex(v) for v in want]}")
        held, _, zflag = _answers(m, addr)
        assert held[:4] == want, (
            f"pad_btn disagrees with the words: {[hex(v) for v in held[:4]]}")
        assert held[4:] == [0, 0], f"pad_btn(4/5) answered {held[4:]}"
        assert zflag == (0b111111 & ~(1 << player)), (
            f"pad_btn's Z flags {zflag:#08b}: set for every idle player and "
            f"for 4-5, clear for player {player} only")
        m.advance(1)                            # release: next press is an edge


def test_out_of_range_players_answer_zero_with_every_pad_holding_everything(addr):
    m = _boot(mr.PORT2_MULTITAP)
    allb = {b: True for b in BITS}
    m.advance(1)
    m.advance(1, pad1=allb, pad2=allb, pad3=allb, pad4=allb)
    held, press, zflag = _answers(m, addr)
    full = sum(1 << b for b in BITS.values())
    assert held[:4] == [full] * 4 and press[:4] == [full] * 4, (
        [hex(v) for v in held], [hex(v) for v in press])
    assert held[4:] == [0, 0] and press[4:] == [0, 0]
    assert zflag == 0b110000, f"Z flags {zflag:#08b}: set for players 4-5 only"


# =============================================================================
# MT-3 — the edge: press is cur AND NOT prev, for one frame only
# =============================================================================
@pytest.mark.parametrize("player", [0, 1, 2, 3])
def test_a_held_button_is_pressed_on_its_first_frame_only(addr, player):
    m = _boot(mr.PORT2_MULTITAP)
    a = 1 << BITS["a"]
    m.advance(1)
    seen = []
    for _ in range(5):
        m.advance(1, **_pads(player, "a"))
        seen.append((_words(m, addr, CUR)[player], _words(m, addr, PRESS)[player],
                     _answers(m, addr)[1][player]))
    m.advance(1)
    seen.append((_words(m, addr, CUR)[player], _words(m, addr, PRESS)[player],
                 _answers(m, addr)[1][player]))
    want = [(a, a, a)] + [(a, 0, 0)] * 4 + [(0, 0, 0)]
    assert seen == want, (
        f"player {player + 1}: (cur, press, pad_btnp) per frame {seen}, want "
        f"{want}")
    # and nobody else's press word moved
    assert [w for i, w in enumerate(_words(m, addr, PRESS)) if i != player] \
        == [0, 0, 0]


# =============================================================================
# MT-4 — no adapter: players 3-4 read nothing, whatever is latched
# =============================================================================
def test_without_an_adapter_players_3_and_4_read_nothing(addr):
    m = _boot(mr.PORT2_PAD)
    allb = {b: True for b in BITS}
    m.advance(3, pad3=allb, pad4=allb)
    assert _words(m, addr, CUR)[2:] == [0, 0]
    assert _words(m, addr, PRESS)[2:] == [0, 0]
    held, press, zflag = _answers(m, addr)
    assert held[2:] == [0, 0, 0, 0] and press[2:] == [0, 0, 0, 0]
    assert zflag == 0b111111, f"every player idle, Z flags {zflag:#08b}"


# =============================================================================
# MT-5 — players 1-2 are the same with and without the adapter
# =============================================================================
def test_players_1_and_2_read_identically_with_and_without_the_adapter(addr):
    script = [({"right": True}, None), ({"b": True, "up": True}, {"y": True}),
              (None, {"start": True, "left": True}), (None, None),
              ({"a": True}, {"a": True, "r": True})]
    runs = {}
    for port2 in (mr.PORT2_PAD, mr.PORT2_MULTITAP):
        m = _boot(port2)
        trace = []
        for p1, p2 in script:
            m.advance(2, pad1=p1, pad2=p2)
            trace.append(_words(m, addr, CUR[:2] + PRESS[:2]))
        runs[port2] = trace
        m.close()
    assert runs[mr.PORT2_PAD] == runs[mr.PORT2_MULTITAP], runs
    # and the trace is not vacuous: every scripted press showed up
    assert runs[mr.PORT2_PAD][1][:2] == [(1 << 15) | (1 << 11), 1 << 14]


# =============================================================================
# MT-7 — WRIO.7 is back to 1 after the read
# =============================================================================
def test_the_select_line_is_released_so_the_next_auto_read_sees_slots_1_and_2(addr):
    """The OBSERVABLE consequence of WRIO.7 left low: the next frame's
    automatic read would route slots 3/4 to $421A/$421E, so player 4's
    buttons would appear in player 2's and player 3's words. Held for many
    frames, so every auto-read after the first sees whatever line state the
    previous mtap_read left behind."""
    m = _boot(mr.PORT2_MULTITAP)
    m.advance(10, pad4={"b": True, "x": True})
    assert _words(m, addr, CUR) == [0, 0, 0, (1 << 15) | (1 << 6)], (
        [hex(v) for v in _words(m, addr, CUR)])
    m.advance(10, pad2={"y": True}, pad3={"l": True})
    assert _words(m, addr, CUR) == [0, 1 << 14, 1 << 5, 0], (
        [hex(v) for v in _words(m, addr, CUR)])
