"""The harness can put a four-pad adapter in port 2 and drive every slot (docs/102 MT-H1).

LEVEL 0, ON PURPOSE. The ROM under test is `tests/fixtures/mtap_harness/
probe_mtap.asm`: no allocator, no feature, no engine routine — it runs
fullsnes' detection and read sequence by hand and copies what the hardware
answered into a result block. So everything asserted here is a claim about the
EMULATED HARDWARE as the harness configures it, and nothing the engine's
`mtap` feature does can make these cases pass or fail. The engine's own tests
(`test_mtap.py`) then stand on this one.

What is proved, each on the hardware's own answer:

  * the adapter config is real: detection reads A=$FF, B<>$FF with it and
    A=B=$00 without it (the plain pad never drives pin 5);
  * the override-index -> slot mapping, measured one index at a time with a
    DIFFERENT button per index so a crossed wire cannot pass: 0 -> $4218,
    1 -> $421A, 2 -> $421E, 3 -> the manual bit-0 word, 4 -> the manual
    bit-1 word — and each press lands in exactly ONE place;
  * the default (no adapter) harness is unchanged: port 2 is a plain pad,
    `pad3`/`pad4` reach nothing, and building a default Machine after an
    adapter Machine puts the plain pad back;
  * EMPTY PORTS AND EMPTY SLOTS (docs/102 D10): `port1=PORT_EMPTY`,
    `port2=PORT_EMPTY` and the adapter's `tap_slots` put nothing where they
    say, and the 17th bit every line answers is fullsnes' — "17th and up:
    Padding (always 1=Low) (or 0=High when no pad connected)" — 1 behind a
    pad, 0 on an empty port or slot, for every combination. This is the
    ground truth `mtap`'s per-pad presence census stands on.

Addresses are the probe's own equates, parsed from the fixture source — the
same primary-source rule `vendor/probes/` follows for ROMs the allocator never
places.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))

from machine import Machine, MemoryType  # noqa: E402
import mesen_runner as mr  # noqa: E402

SRC = SUPERFORGE / "tests" / "fixtures" / "mtap_harness" / "probe_mtap.asm"
BUILD = SUPERFORGE / "build"
ROM = BUILD / "probe_mtap_harness.sfc"
W = MemoryType.SnesWorkRam

_EQ = dict((m.group(1), int(m.group(2), 16)) for m in re.finditer(
    r"^(R_[A-Z0-9]+)\s*=\s*\$([0-9A-Fa-f]+)", SRC.read_text(), re.M))
R_DETA, R_DETB, R_JOY = _EQ["R_DETA"], _EQ["R_DETB"], _EQ["R_JOY"]
R_MAN0, R_MAN1, R_SIG = _EQ["R_MAN0"], _EQ["R_MAN1"], _EQ["R_SIG"]
R_X17, R_X17B = _EQ["R_X17"], _EQ["R_X17B"]

# One button per override index, each a different bit of the pad word, so a
# swapped pair of indices reads as the wrong BIT, not merely the wrong place.
BUTTON = {0: ("b", 0x8000), 1: ("y", 0x4000), 2: ("select", 0x2000),
          3: ("start", 0x1000), 4: ("up", 0x0800)}

BOOT = 30


@pytest.fixture(scope="module", autouse=True)
def rom_built():
    """Assemble the fixture with the same tools and template every rail uses."""
    BUILD.mkdir(exist_ok=True)
    obj = BUILD / "probe_mtap_harness.o"
    for argv in (["ca65", "--cpu", "65816", "-I", str(SUPERFORGE / "vendor" / "rom"),
                  "-o", str(obj), str(SRC)],
                 ["ld65", "-C", str(SUPERFORGE / "vendor" / "rom" / "lorom_32k.cfg"),
                  "-o", str(ROM), str(obj)],
                 [sys.executable, str(SUPERFORGE / "tools" / "fix_checksum.py"),
                  str(ROM)]):
        r = subprocess.run(argv, capture_output=True, text=True)
        assert r.returncode == 0, f"{argv[0]} failed:\n{r.stdout}\n{r.stderr}"
    yield


@pytest.fixture(autouse=True)
def hand_back_the_core():
    yield
    Machine.close_current()


def _result(m):
    joy = m.read_bytes(W, R_JOY, 8)
    word = lambda b, o: b[o] | (b[o + 1] << 8)
    return {"deta": m.read_byte(W, R_DETA), "detb": m.read_byte(W, R_DETB),
            "joy1": word(joy, 0), "joy2": word(joy, 2), "joy3": word(joy, 4),
            "joy4": word(joy, 6), "man0": m.read_u16(W, R_MAN0),
            "man1": m.read_u16(W, R_MAN1)}


def _press(m, idx, frames=2):
    """Hold ONE override index's button (pad<idx+1>), everything else released."""
    m.advance(frames, **{f"pad{idx + 1}": {BUTTON[idx][0]: True}})
    return _result(m)


def test_the_adapter_answers_detection_and_the_plain_pad_does_not():
    m = Machine(str(ROM), port2=mr.PORT2_MULTITAP).advance(BOOT)
    assert m.read_u16(W, R_SIG) == 0x1234, "the probe never finished detection"
    r = _result(m)
    assert r["deta"] == 0xFF and r["detb"] != 0xFF, (
        f"adapter: A={r['deta']:#04x} B={r['detb']:#04x} — fullsnes' "
        f"present condition is A=$FF and B<>$FF")
    m.close()
    m = Machine(str(ROM)).advance(BOOT)
    r = _result(m)
    assert (r["deta"], r["detb"]) == (0, 0), (
        f"plain pad: A={r['deta']:#04x} B={r['detb']:#04x} — a pad that does "
        f"not drive pin 5 reads $00 both ways")


@pytest.mark.parametrize("idx", [0, 1, 2, 3, 4])
def test_each_override_index_reaches_exactly_one_slot(idx):
    where = {0: "joy1", 1: "joy2", 2: "joy4", 3: "man0", 4: "man1"}
    m = Machine(str(ROM), port2=mr.PORT2_MULTITAP).advance(BOOT)
    idle = _result(m)
    assert all(idle[k] == 0 for k in where.values()), f"not idle: {idle}"
    r = _press(m, idx)
    bit = BUTTON[idx][1]
    for i, k in where.items():
        want = bit if i == idx else 0
        assert r[k] == want, (
            f"override {idx} ({BUTTON[idx][0]}): {k} = {r[k]:#06x}, want "
            f"{want:#06x}. Full read: { {a: hex(b) for a, b in r.items()} }")
    assert r["joy3"] == 0, "port 1 pin 5 ($421C) has nothing behind it"


def test_without_the_adapter_pads_3_and_4_reach_nothing():
    m = Machine(str(ROM)).advance(BOOT)
    m.advance(2, pad3={"select": True}, pad4={"start": True})
    r = _result(m)
    assert (r["joy1"], r["joy2"], r["joy4"]) == (0, 0, 0), r
    # Port 2's plain pad keeps answering 1s after its 16 bits, so the manual
    # bit-0 word is all ones and bit 1 (pin 5, undriven) all zeros — a pad,
    # not an adapter, and unmoved by the latched overrides.
    assert (r["man0"], r["man1"]) == (0xFFFF, 0x0000), r
    m.advance(2, pad2={"y": True})
    assert _result(m)["joy2"] == 0x4000, "port 2's plain pad stopped answering"


def test_a_default_machine_after_an_adapter_machine_gets_the_plain_pad_back():
    Machine(str(ROM), port2=mr.PORT2_MULTITAP).advance(BOOT).close()
    assert mr._PORT2_MODE == mr.PORT2_MULTITAP
    m = Machine(str(ROM)).advance(BOOT)
    assert mr._PORT2_MODE == mr.PORT2_PAD
    r = _result(m)
    assert (r["deta"], r["detb"]) == (0, 0), (
        "the adapter leaked into a default Machine's load")


def test_the_default_config_is_the_two_pad_config_it_always_was():
    """`_apply_port2` adds nothing in pad mode: port 2 is a SnesController and
    every sub-port is the zero struct, exactly the pre-docs/102 bytes."""
    mr.ensure_port2_device(mr.PORT2_PAD)
    cfg = mr._make_base_snes_config()
    assert cfg.Port1.Type == 1 and cfg.Port2.Type == 1
    assert all(bytes(cfg.Port2SubPorts[i]) == bytes(mr._ControllerConfig())
               for i in range(4))
    assert mr.ensure_port2_device(mr.PORT2_PAD) is False, (
        "asking for the mode already in force must not touch the config")


# =============================================================================
# empty ports and empty adapter slots — the 17th bit (docs/102 D10)
# =============================================================================
_SLOTS = [tuple(bool(n >> (3 - i) & 1) for i in range(4)) for n in range(16)]
_CONFIGS = ([(p1, mr.PORT2_PAD, mr.TAP_FULL) for p1 in (mr.PORT_PAD, mr.PORT_EMPTY)]
            + [(p1, mr.PORT_EMPTY, mr.TAP_FULL) for p1 in (mr.PORT_PAD, mr.PORT_EMPTY)]
            + [(p1, mr.PORT2_MULTITAP, sl) for p1 in (mr.PORT_PAD, mr.PORT_EMPTY)
               for sl in _SLOTS])


def _cfg_id(c):
    return f"{c[0]}-{c[1]}" + ("-" + "".join("1" if b else "0" for b in c[2])
                               if c[1] == mr.PORT2_MULTITAP else "")


@pytest.mark.parametrize("cfg", _CONFIGS, ids=[_cfg_id(c) for c in _CONFIGS])
def test_the_17th_bit_is_1_behind_a_pad_and_0_on_an_empty_port_or_slot(cfg):
    """Per line, written out from the configuration alone: port 1 pin 4 is
    port 1's pad; port 2 pin 4 is port 2's plain pad or the adapter's slot 1;
    pin 5 is the adapter's slot 2 (a plain pad does not drive it); under
    WRIO.7 = 0, bits 0/1 are the adapter's slots 3/4 (a plain pad keeps
    shifting 1s out of pin 4, and leaves pin 5 low)."""
    p1, p2, slots = cfg
    m = Machine(str(ROM), port1=p1, port2=p2, tap_slots=slots).advance(BOOT)
    assert m.read_u16(W, R_SIG) == 0x1234, "the probe never finished detection"
    pad1 = p1 == mr.PORT_PAD
    if p2 == mr.PORT2_MULTITAP:
        pin4, pin5, sel4, sel5 = slots
    elif p2 == mr.PORT2_PAD:
        pin4, pin5, sel4, sel5 = True, False, True, False
    else:
        pin4 = pin5 = sel4 = sel5 = False
    want_x17 = int(pad1) | int(pin4) << 1 | int(pin5) << 2
    want_x17b = int(sel4) | int(sel5) << 1
    got = (m.read_byte(W, R_X17), m.read_byte(W, R_X17B))
    assert got == (want_x17, want_x17b), (
        f"{_cfg_id(cfg)}: 17th bits {got[0]:#05b} / {got[1]:#04b}, want "
        f"{want_x17:#05b} / {want_x17b:#04b} (port1/pin4/pin5, then slots 3/4)")
    # ...and an empty slot or port is EMPTY, not an idle pad that a latched
    # override could still reach: hold every button on every index.
    allb = {b: True for b in ("b", "y", "select", "start", "up", "down",
                              "left", "right", "a", "x", "l", "r")}
    m.advance(2, pad1=allb, pad2=allb, pad3=allb, pad4=allb, pad5=allb)
    r = _result(m)
    full = 0xFFF0
    assert r["joy1"] == (full if pad1 else 0), r
    assert r["joy2"] == (full if pin4 else 0), r
    assert r["joy4"] == (full if (p2 == mr.PORT2_MULTITAP and pin5) else 0), r
    if p2 == mr.PORT2_MULTITAP:
        assert (r["man0"], r["man1"]) == (full if sel4 else 0,
                                          full if sel5 else 0), r


def test_an_impossible_port_configuration_is_refused():
    with pytest.raises(ValueError):
        mr.check_ports(port2=mr.PORT2_PAD, tap_slots=(True, False, True, True))
    with pytest.raises(ValueError):
        mr.check_ports(port1=mr.PORT2_MULTITAP)
    with pytest.raises(ValueError):
        mr.check_ports(port2="mouse")


@pytest.mark.parametrize("ports", [dict(port1=mr.PORT_EMPTY),
                                   dict(port2=mr.PORT_EMPTY),
                                   dict(port1=mr.PORT_EMPTY, port2=mr.PORT_EMPTY)],
                         ids=["port1", "port2", "both"])
def test_a_default_machine_after_an_empty_port_machine_gets_both_pads_back(ports):
    """Each port alone as well as both: a pin that compared only the port it
    used to compare (port 2) would leak an empty port 1 into the next load."""
    Machine(str(ROM), **ports).advance(BOOT).close()
    m = Machine(str(ROM)).advance(BOOT)
    assert (mr._PORT1_MODE, mr._PORT2_MODE, mr._TAP_SLOTS) == (
        mr.PORT_PAD, mr.PORT2_PAD, mr.TAP_FULL)
    assert m.read_byte(W, R_X17) == 0b011, (
        "an empty port leaked into a default Machine's load: 17th bits "
        f"{m.read_byte(W, R_X17):#05b}, want both pads (port 1, port 2 pin 4)")
