"""C2 — the `sram` claim class: program-wide packing, refusals, header bytes.

The class's acceptance surface: infeasible declarations REFUSE
the build with complete blame lists; the cart header bytes FOLLOW the claims
(read out of built .sfc files, not out of the allocator's bookkeeping); a
hand-written $70xxxx literal refuses no_literals with the emitted symbol
named. Placement is PROGRAM-wide — one free list over the union of every
feature's sram claims across globals + all scenes, deduped by feature name.

Each refusal here was FALSIFIED during this change: the check was planted out
on a committed tree (place_sram given an unbounded free list; the header
derivation hardcoded back to $00; the no_literals sram branch removed), the
test observed RED, and the tree restored byte-clean. The falsification
evidence is in this change's final report — a green refusal test that has
never seen its gate fail proves nothing (AGENTS.md).
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "allocator"))

from allocate import (AllocationError, allocate, emit,  # noqa: E402
                      place_sram, sram_header_bytes)
from schemas import StateDecl, load_feature, load_manifest, load_substrate  # noqa: E402

SUB = load_substrate(SUPERFORGE / "allocator" / "substrate.toml")
NO_STATE = StateDecl((), {})


def feature(tmp_path, name, body=""):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "feature.toml").write_text(f'name = "{name}"\nrole = "feature"\n{body}')
    return load_feature(d / "feature.toml", SUB)


def manifest(tmp_path, text):
    p = tmp_path / "game.toml"
    p.write_text(text)
    return load_manifest(p)


# --------------------------------------------------------------------------
# placement: program-wide, deduped, deterministic
# --------------------------------------------------------------------------

def test_sram_places_program_wide_and_dedupes_by_feature(tmp_path):
    """A feature composed into TWO scenes places its sram claim ONCE.

    The spc holders pattern applied to a packer: scene composition must not
    duplicate (or worse, scene-scope-reuse) a persistent region. The
    placement lands in the GLOBALS map regardless of where the feature was
    composed, because SRAM layout is program-lifetime.
    """
    sv = feature(tmp_path, "sv",
                 '[[claims.sram]]\nname = "slots"\nbytes = 64\n')
    man = manifest(tmp_path,
                   '[[scene]]\nid = "a"\nfeatures = ["sv"]\n'
                   '[[scene]]\nid = "b"\nfeatures = ["sv"]\n')
    alloc = allocate(SUB, {"sv": sv}, NO_STATE, man)
    placed = [p for p in alloc.globals_map if p.cls == "sram"]
    assert len(placed) == 1, f"claim placed {len(placed)} times, want once"
    assert placed[0].name == "slots" and placed[0].size == 64
    assert placed[0].start == 0
    for sm in alloc.scenes.values():
        assert not [p for p in sm.placements if p.cls == "sram"], \
            "an sram placement leaked into a scene map"


def test_sram_global_and_scene_holders_share_one_free_list(tmp_path):
    """Two DIFFERENT features — one global, one scene-scoped — pack into the
    same program-wide space: disjoint offsets, both in the globals map."""
    g = feature(tmp_path, "g", '[[claims.sram]]\nname = "g_slots"\nbytes = 64\n')
    s = feature(tmp_path, "s", '[[claims.sram]]\nname = "s_slots"\nbytes = 32\n')
    man = manifest(tmp_path,
                   'globals = ["g"]\n[[scene]]\nid = "a"\nfeatures = ["s"]\n')
    alloc = allocate(SUB, {"g": g, "s": s}, NO_STATE, man)
    placed = sorted((p for p in alloc.globals_map if p.cls == "sram"),
                    key=lambda p: p.start)
    assert [(p.name, p.start, p.size) for p in placed] == \
        [("g_slots", 0, 64), ("s_slots", 64, 32)], \
        "largest-first deterministic packing over ONE free list"


# --------------------------------------------------------------------------
# the refusals — falsified on a committed tree
# --------------------------------------------------------------------------

def test_sram_over_budget_refuses_with_complete_blame(tmp_path):
    """Demand over the one-bank-window ceiling stops the build, naming EVERY
    contributing claim and the exact shortfall (the F3 blame-list rule)."""
    a = feature(tmp_path, "a", '[[claims.sram]]\nname = "big"\nbytes = 0x6000\n')
    b = feature(tmp_path, "b", '[[claims.sram]]\nname = "more"\nbytes = 0x3000\n')
    man = manifest(tmp_path, '[[scene]]\nid = "x"\nfeatures = ["a", "b"]\n')
    with pytest.raises(AllocationError) as e:
        allocate(SUB, {"a": a, "b": b}, NO_STATE, man)
    msg = str(e.value)
    assert "SRAM over budget" in msg
    assert "big(24576)" in msg and "more(12288)" in msg, \
        f"blame list incomplete: {msg}"
    assert f"by {0x9000 - SUB.sram_bytes}" in msg, f"shortfall wrong: {msg}"


def test_sram_pin_overlap_refuses_with_the_pin_named(tmp_path):
    """Two pins whose ranges intersect refuse, naming the pinned claim."""
    a = feature(tmp_path, "a",
                '[[claims.sram]]\nname = "lo"\nbytes = 32\nat = 0x10\n')
    b = feature(tmp_path, "b",
                '[[claims.sram]]\nname = "hi"\nbytes = 32\nat = 0x20\n')
    man = manifest(tmp_path, '[[scene]]\nid = "x"\nfeatures = ["a", "b"]\n')
    with pytest.raises(AllocationError) as e:
        allocate(SUB, {"a": a, "b": b}, NO_STATE, man)
    msg = str(e.value)
    assert "sram claim 'hi'" in msg and "pinned range" in msg, msg
    assert "not free" in msg


def test_sram_pin_out_of_window_refuses(tmp_path):
    """A pin past the window ceiling cannot carve — the free list is the
    arbiter, same as every other pinned class."""
    a = feature(tmp_path, "a",
                '[[claims.sram]]\nname = "off_the_end"\nbytes = 64\nat = 0x7FF0\n')
    man = manifest(tmp_path, '[[scene]]\nid = "x"\nfeatures = ["a"]\n')
    with pytest.raises(AllocationError, match="off_the_end"):
        allocate(SUB, {"a": a}, NO_STATE, man)


def test_verify_mirrors_the_sram_overlap_check(tmp_path):
    """Belt-and-suspenders: verify() re-checks sram overlap + budget bounds
    independently of place_sram's bookkeeping. Corrupt a placement behind
    the solver's back and the checker must catch it."""
    from allocate import Placement, verify
    sv = feature(tmp_path, "sv", '[[claims.sram]]\nname = "slots"\nbytes = 64\n')
    man = manifest(tmp_path, '[[scene]]\nid = "a"\nfeatures = ["sv"]\n')
    alloc = allocate(SUB, {"sv": sv}, NO_STATE, man)
    alloc.globals_map.append(
        Placement("intruder", "sram", 32, 64, "<global>", "engine:evil"))
    with pytest.raises(AssertionError, match="sram overlap"):
        verify(alloc)
    alloc.globals_map.pop()
    alloc.globals_map.append(
        Placement("oob", "sram", SUB.sram_bytes - 8, 64, "<global>", "engine:evil"))
    with pytest.raises(AssertionError, match="sram out of range"):
        verify(alloc)


# --------------------------------------------------------------------------
# header derivation: a pure function of the claims
# --------------------------------------------------------------------------

def test_header_derivation_rounds_demand_up(tmp_path):
    """64 B demanded -> N=1 (2 KiB declared, the minimum); boundary cases
    exercise the round-up rather than trusting the arithmetic."""
    from allocate import Placement

    def hdr(total):
        return sram_header_bytes(
            [Placement("x", "sram", 0, total, "<global>", "t")], SUB)

    assert sram_header_bytes([], SUB) is None, "no claims -> emit nothing"
    assert hdr(64) == (1, 0x02)
    assert hdr(2048) == (1, 0x02), "exactly 2 KiB still fits N=1"
    assert hdr(2049) == (2, 0x02), "one byte over rounds up to 4 KiB"
    assert hdr(0x8000) == (5, 0x02), "the full window is N=5 (32 KiB)"


def test_claimless_game_emits_no_header_symbols(tmp_path):
    """No sram claims -> NOTHING emitted: the header.inc defaults hold and
    existing ROMs stay byte-identical (the microzero md5 pin depends on it)."""
    f = feature(tmp_path, "plain", '[[claims.dp]]\nbytes = 2\n')
    man = manifest(tmp_path, '[[scene]]\nid = "a"\nfeatures = ["plain"]\n')
    alloc = allocate(SUB, {"plain": f}, NO_STATE, man)
    emit(alloc, tmp_path / "out")
    ginc = (tmp_path / "out" / "engine_state_globals.inc").read_text()
    assert "SF_HDR_SRAM_SIZE" not in ginc
    assert "SF_HDR_CART_TYPE" not in ginc
    assert "ES_S_" not in ginc


def test_header_bytes_flow_into_the_emitted_globals_inc(tmp_path):
    """The derived encodings ride the globals inc (the _SC_BASE/_NBA family),
    where header.inc's .ifndef defaults pick them up — include order is
    generated inc BEFORE header.inc in every main.asm."""
    sv = feature(tmp_path, "sv", '[[claims.sram]]\nname = "slots"\nbytes = 64\n')
    man = manifest(tmp_path, '[[scene]]\nid = "a"\nfeatures = ["sv"]\n')
    alloc = allocate(SUB, {"sv": sv}, NO_STATE, man)
    emit(alloc, tmp_path / "out")
    ginc = (tmp_path / "out" / "engine_state_globals.inc").read_text()
    assert "SF_HDR_SRAM_SIZE = $01" in ginc
    assert "SF_HDR_CART_TYPE = $02" in ginc
    assert "ES_S_SLOTS = $0000" in ginc
    assert "ES_S_SLOTS_BANK = $70" in ginc
    assert "ES_S_SLOTS_LONG = $700000" in ginc
    assert "ES_S_SLOTS_SIZE = 64" in ginc


def test_sram_placements_ride_the_symbol_map(tmp_path):
    """symbol_map.json carries class "sram" placements so no_literals'
    _allocated_hit has its input (the wram precedent)."""
    sv = feature(tmp_path, "sv", '[[claims.sram]]\nname = "slots"\nbytes = 64\n')
    man = manifest(tmp_path, '[[scene]]\nid = "a"\nfeatures = ["sv"]\n')
    alloc = allocate(SUB, {"sv": sv}, NO_STATE, man)
    emit(alloc, tmp_path / "out")
    jmap = json.loads((tmp_path / "out" / "symbol_map.json").read_text())
    hit = [p for p in jmap["globals"] if p["class"] == "sram"]
    assert hit == [{"sym": "ES_S_SLOTS", "class": "sram", "start": 0,
                    "size": 64, "scope": "global", "consumer": "engine:sv",
                    "kind": ""}]
    assert jmap["spaces"]["sram_bytes"] == SUB.sram_bytes
    assert jmap["spaces"]["sram_base_addr"] == 0x700000


# --------------------------------------------------------------------------
# header bytes are ROM-FILE bytes
# --------------------------------------------------------------------------
# LoROM: the internal header at $00:FFC0-$FFDF is file offset $7FC0-$7FDF.
OFF_CART_TYPE = 0x7FD6
OFF_SRAM_SIZE = 0x7FD8


def _run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    assert r.returncode == 0, f"{cmd}:\n{r.stdout}{r.stderr}"
    return r


def test_a_claiming_fixture_rom_declares_its_sram(tmp_path):
    """Allocator -> ca65 -> ld65 -> read the .sfc bytes at the header
    offsets. This is the artifact a flashcart menu, bsnes, or real hardware
    reads — the whole point of driving BOTH bytes (Mesen persists on size
    alone; the chipset byte is for everyone else — settlement §3.3)."""
    fx = SUPERFORGE / "tests" / "fixtures" / "sram_hdr"
    out = tmp_path / "map"
    _run([sys.executable, str(SUPERFORGE / "allocator" / "allocate.py"),
          "--game", str(fx), "--out", str(out)])
    _run(["ca65", "--cpu", "65816", "-I", str(out),
          "-I", str(SUPERFORGE / "vendor" / "rom"),
          "-o", str(tmp_path / "probe.o"), str(fx / "main.asm")])
    _run(["ld65", "-C", str(SUPERFORGE / "vendor" / "rom" / "lorom_32k.cfg"),
          "-o", str(tmp_path / "probe.sfc"), str(tmp_path / "probe.o")])
    img = (tmp_path / "probe.sfc").read_bytes()
    assert img[OFF_CART_TYPE] == 0x02, \
        f"$FFD6 cart type is ${img[OFF_CART_TYPE]:02X}, want $02 (battery)"
    assert img[OFF_SRAM_SIZE] == 0x01, \
        f"$FFD8 SRAM size is ${img[OFF_SRAM_SIZE]:02X}, want $01 (2 KiB)"


def test_claimless_microzero_keeps_a_no_sram_header_and_its_md5(tmp_path):
    """The other half of the derivation contract: a game with NO sram claims
    ships $00/$00 — and byte-identically, which the pinned md5 proves. The
    measurement reference must not move; if this fails and
    you did not deliberately move microzero, the class has leaked into a
    composition that never asked for it."""
    import hashlib
    r = subprocess.run(["make", "microzero"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"make microzero failed:\n{r.stderr}"
    img = (SUPERFORGE / "build" / "microzero.sfc").read_bytes()
    assert img[OFF_CART_TYPE] == 0x00 and img[OFF_SRAM_SIZE] == 0x00
    assert hashlib.md5(img).hexdigest() == "008b19045c002c1026f87696e9350472", \
        "microzero.sfc moved — the measurement reference is a pinned md5"


# --------------------------------------------------------------------------
# the literal smuggle
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def claiming_map(tmp_path_factory):
    """A symbol map holding one sram claim, for no_literals runs."""
    out = tmp_path_factory.mktemp("smap")
    fx = SUPERFORGE / "tests" / "fixtures" / "sram_hdr"
    _run([sys.executable, str(SUPERFORGE / "allocator" / "allocate.py"),
          "--game", str(fx), "--out", str(out)])
    return out / "symbol_map.json"


def no_literals(map_path, asm: Path):
    # NOTE: no `--partial-files`. This invocation hands ONE file a whole
    # composition's map, which the whole-composition rom-backing pass cannot
    # answer — it survives only because the tests/fixtures/sram_hdr fixture has
    # ZERO rom claims. Add one and this test fails with a rom-backing error
    # that has nothing to do with its subject. Naming the dependency, not
    # restructuring the test: that is separate work (the brief's out-of-scope
    # list).
    return subprocess.run(
        [sys.executable, str(SUPERFORGE / "allocator" / "no_literals.py"),
         "--map", str(map_path), str(asm)],
        capture_output=True, text=True)


def test_a_70_bank_long_literal_refuses_naming_the_symbol(
        tmp_path, claiming_map):
    """`sta f:$700000` is a hand-narrated save address. The gate must refuse
    AND say which emitted symbol owns the byte, so the fix is legible."""
    bad = tmp_path / "smuggle.asm"
    bad.write_text("save_it:\n    sta f:$700000\n    rts\n")
    r = no_literals(claiming_map, bad)
    assert r.returncode == 1, f"accepted a $70-bank literal:\n{r.stdout}"
    assert "ES_S_PROBE_SLOTS" in r.stderr, \
        f"refusal does not name the owning symbol:\n{r.stderr}"
    assert "address" in r.stderr


def test_a_70_literal_inside_the_claim_interior_also_refuses(
        tmp_path, claiming_map):
    """Not just the base: byte 5 of the claim is still the claim."""
    bad = tmp_path / "smuggle2.asm"
    bad.write_text("poke:\n    lda f:$700005\n    rts\n")
    r = no_literals(claiming_map, bad)
    assert r.returncode == 1 and "ES_S_PROBE_SLOTS" in r.stderr, r.stderr


def test_the_emitted_symbol_form_stays_clean(tmp_path, claiming_map):
    """The legal spelling — long addressing THROUGH the emitted symbol —
    must pass, or the gate is a wall instead of a rail."""
    good = tmp_path / "legal.asm"
    good.write_text("save_it:\n"
                    "    sta f:ES_S_PROBE_SLOTS_LONG\n"
                    "    lda f:ES_S_PROBE_SLOTS_LONG + 8\n"
                    "    rts\n")
    r = no_literals(claiming_map, good)
    assert r.returncode == 0, f"the symbol form was refused:\n{r.stderr}"


