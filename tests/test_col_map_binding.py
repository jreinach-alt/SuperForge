"""col_map's binding contract and its parameterised code paths.

WHY THIS EXISTS, and it is the whole justification: the generalisation gave
`col_map.asm` three assembly-time code paths, and the shipping composition
exercises exactly ONE of them. microzero binds W = 512 with 8 chunks, so `make
microzero` + the emulator suite prove the `W_LOG2 > 8` shift arm and the
multi-chunk bank arm. The `W_LOG2 < 8` arm and the `CHUNKS = 1` elision — the
two arms that exist *for the second rail* — are covered by nothing that runs
today, and "it will be exercised when m7_dungeon lands" is how a wrong shift
ships and gets diagnosed as a map bug.

THE OUTPUT REGION READ IS THE EMITTED MACHINE CODE. These tests assemble the
real `engine/features/col_map/col_map.asm` (not a copy) at several bindings,
link it flat, and DECODE the bytes ca65 produced — the same discipline as
reading VRAM rather than a variable that should reflect it.

The decoder below is deliberately real. The first draft of this file asserted
"no branch opcode appears anywhere in the byte string", which is wrong for a
reason worth recording: `$30` is `BMI` *and* it is `CM_PX`'s direct-page
offset, `$80` is `BRA` *and* it is the high byte of the `$8000` window — so
the check failed on the shipping binding, on operand bytes. A byte-set test
over an instruction stream is not a test of the instruction stream. Decoding
costs thirty lines and says what it means. (It also removed a second bug: the
byte-offset slices in the first draft were off by one.)

No emulator: there is no hardware state to read, because the claim under test
is what the ASSEMBLER emits. The behavioural claims — the lookup is correct,
total, and reads the right bank — are tests/test_col_map.py's, on the
emulator, at the shipping binding.
"""
import subprocess
import textwrap
from pathlib import Path

import pytest

F = Path(__file__).resolve().parent.parent
KERNEL_DIR = F / "engine" / "features" / "col_map"

# A binding that is deliberately NOT microzero's addresses: the point is to
# read the SHAPE of the emitted code, and distinctive values make a mis-fold
# visible in the decoded stream instead of blending into a plausible one.
PREAMBLE = """\
.p816
.smart
ES_CM_HOT = $30
CM_WORLD_W_LOG2      = {w}
CM_WORLD_H_LOG2      = {h}
CM_WORLD_BLOB        = $8000
CM_WORLD_BLOB_BANK   = 1
CM_WORLD_BLOB_CHUNKS = {chunks}
CM_FLAGS             = $028000
.segment "CODE"
.include "col_map.asm"
"""

CFG = textwrap.dedent("""\
    MEMORY { RAM: start=$8000, size=$8000, file=%O, fill=no; }
    SEGMENTS { CODE: load=RAM, type=ro; }
    """)

# --- a linear 65816 decoder over exactly the opcodes this kernel uses -------
# (mnemonic, operand bytes). `None` = sized by the current A width, which the
# decoder tracks through sep/rep — the same discipline the width lint enforces
# on the source side. An opcode outside this table is a FAILURE, not a skip:
# the kernel growing a new instruction should make someone look at this file.
OPS = {
    0xA5: ("lda dp", 1),   0xA9: ("lda #", None), 0x29: ("and #", None),
    0x4A: ("lsr", 0),      0x0A: ("asl", 0),      0xEB: ("xba", 0),
    0x85: ("sta dp", 1),   0x18: ("clc", 0),      0x69: ("adc #", None),
    0x65: ("adc dp", 1),   0xAA: ("tax", 0),      0xE2: ("sep #", 1),
    0xC2: ("rep #", 1),    0x8B: ("phb", 0),      0x48: ("pha", 0),
    0xAB: ("plb", 0),      0xBD: ("lda abs,x", 2), 0xBF: ("lda long,x", 3),
    0x60: ("rts", 0),
}
# Every 65816 opcode that transfers control conditionally or by a relative
# displacement. If one of these is DECODED (not merely present as a byte), the
# kernel has grown a branch.
BRANCH_OPS = {0x10, 0x30, 0x50, 0x70, 0x80, 0x82, 0x90, 0xB0, 0xD0, 0xF0,
              0x20, 0x22, 0x4C, 0x5C, 0x6C, 0x7C, 0xDC, 0xFC}


def decode(code):
    """-> list of (mnemonic, operand int or None). Raises on an unknown op."""
    out, i, a16 = [], 0, True          # col_map_at is entered .a16
    while i < len(code):
        op = code[i]
        if op in BRANCH_OPS:
            raise AssertionError(f"branch/jump opcode {op:#04x} decoded at "
                                 f"offset {i} — the kernel is branchless")
        assert op in OPS, f"unknown opcode {op:#04x} at offset {i}: {code.hex()}"
        name, n = OPS[op]
        if n is None:
            n = 2 if a16 else 1
        operand = int.from_bytes(code[i + 1:i + 1 + n], "little") if n else None
        if op == 0xE2 and operand & 0x20:
            a16 = False
        if op == 0xC2 and operand & 0x20:
            a16 = True
        out.append((name, operand))
        i += 1 + n
    return out


def assemble(tmp_path, src):
    """Assemble + flat-link a fragment. Returns (ok, code bytes, ca65 output)."""
    s = tmp_path / "frag.s"
    s.write_text(src)
    (tmp_path / "f.cfg").write_text(CFG)
    r = subprocess.run(["ca65", "-I", str(KERNEL_DIR),
                        "-o", str(tmp_path / "frag.o"), str(s)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return False, b"", r.stdout + r.stderr
    r2 = subprocess.run(["ld65", "-C", str(tmp_path / "f.cfg"),
                         "-o", str(tmp_path / "frag.bin"), str(tmp_path / "frag.o")],
                        capture_output=True, text=True)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    return True, (tmp_path / "frag.bin").read_bytes(), r.stdout + r.stderr


def bind(tmp_path, w, h, chunks):
    ok, code, out = assemble(tmp_path, PREAMBLE.format(w=w, h=h, chunks=chunks))
    assert ok, f"binding W={w} H={h} chunks={chunks} failed to assemble:\n{out}"
    return decode(code), code


# --- the six required symbols, each proved to be a real gate ----------------

REQUIRED = ["CM_WORLD_W_LOG2", "CM_WORLD_H_LOG2", "CM_WORLD_BLOB",
            "CM_WORLD_BLOB_BANK", "CM_WORLD_BLOB_CHUNKS", "CM_FLAGS"]


@pytest.mark.parametrize("omitted", REQUIRED)
def test_omitting_any_required_binding_fails_the_build_naming_it(tmp_path, omitted):
    """the spec: "each missing one is a hard `.error` naming it".

    The named-ness is the contract, not merely the failure: an unbound symbol
    that surfaced as a downstream range error would leave the includer to
    guess, which is exactly what the includer-supplied-symbol design was
    chosen to avoid ("the undefined-symbol error is the design review").
    """
    src = "\n".join(l for l in PREAMBLE.format(w=9, h=9, chunks=8).splitlines()
                    if not l.startswith(omitted + " "))
    ok, _, out = assemble(tmp_path, src)
    assert not ok, f"omitting {omitted} still assembled — the gate has a hole"
    assert f"must define {omitted}" in out, \
        f"build failed but did not name {omitted}:\n{out}"


def test_all_six_present_assembles(tmp_path):
    """The control arm: the same harness with nothing omitted must be green,
    or every assertion above is passing for the wrong reason."""
    ops, code = bind(tmp_path, 9, 9, 8)
    assert len(code) > 0 and ops[-1][0] == "rts"


# --- the three code paths, read off the decoded instruction stream ----------

def test_w9_emits_microzeros_shipped_sequence(tmp_path):
    """W=512, H=512, 8 chunks — the shipping binding, asserted whole.

    The full stream, not a spot check: this is the sequence the 951.9 mc/query
    figure describes and the sequence `microzero`'s md5 pin locks. If the
    parameterisation ever stops folding to it, the cost and the pin move
    together and this says which instruction did it.
    """
    ops, _ = bind(tmp_path, 9, 9, 8)
    assert ops == [
        ("lda dp", 0x32), ("lsr", None), ("lsr", None), ("lsr", None),
        ("and #", 511),                       # ty mask = H-1
        ("sta dp", 0x36),
        ("and #", 63),                        # row within chunk = rpc-1
        ("xba", None), ("asl", None),         # * 512  (xba + W_LOG2-8 asl)
        ("sta dp", 0x38),
        ("lda dp", 0x30), ("lsr", None), ("lsr", None), ("lsr", None),
        ("and #", 511),                       # tx mask = W-1
        ("clc", None), ("adc dp", 0x38), ("tax", None),
        ("lda dp", 0x36),                     # chunk arm PRESENT
        *[("lsr", None)] * 6,                 # >> log2(rows per chunk)
        ("clc", None), ("adc #", 1),
        ("sep #", 0x20), ("phb", None), ("pha", None), ("plb", None),
        ("lda abs,x", 0x8000), ("plb", None),
        ("rep #", 0x20), ("and #", 255), ("tax", None),
        ("sep #", 0x20), ("lda long,x", 0x028000), ("sta dp", 0x34),
        ("rts", None),
    ]


def test_w7_narrows_the_row_scale_and_elides_the_chunk_term(tmp_path):
    """W=128, H=128, 1 chunk — m7_dungeon / platformer_stream's shape.

    Two things must happen and NEITHER is exercised by microzero: the row
    scale becomes `xba` + one `lsr` (a shift DOWN, to *128), and the
    chunk-bank add disappears in favour of a constant `lda #bank`. The second
    is the assembly-time `.if` the spec requires INSTEAD of a runtime
    branch, which is why `decode` refuses a branch opcode outright.
    """
    ops, code = bind(tmp_path, 7, 7, 1)
    assert ("and #", 127) == ops[4], "tile-y mask is not #127"
    assert [o[0] for o in ops[6:9]] == ["and #", "xba", "lsr"], \
        "row scale is not `and #` + xba + lsr (a shift DOWN to *128)"
    assert ops[6] == ("and #", 255), "rows-per-chunk mask is not #255"
    assert ("and #", 127) == ops[14], "tile-x mask is not #127"
    # The chunk arm is GONE: a constant bank load stands where lda-dp/lsr/adc was
    assert ops[18] == ("lda #", 1), \
        f"the one-chunk world did not fold the bank to a constant: {ops[18]}"
    assert ("clc", None) not in ops[18:], "a `clc` survives — the add was not elided"
    assert ("adc #", 1) not in ops, "the chunk-bank ADD was not elided"
    _, code9 = bind(tmp_path, 9, 9, 8)
    assert len(code) < len(code9), "the elided form is not shorter"


def test_every_binding_stays_branchless(tmp_path):
    """col_map's headline invariant — "no bounds check, no sentinel, no
    branch" — checked on the DECODED stream at every shape. `decode` raises on
    any branch or jump opcode, so reaching the end of each binding is the
    assertion. The generalisation is only free if the `.if`s stayed at
    assembly time."""
    for w, h, chunks in [(9, 9, 8), (8, 8, 4), (7, 7, 1), (6, 5, 1)]:
        ops, _ = bind(tmp_path, w, h, chunks)
        assert ops[-1] == ("rts", None), f"W_LOG2={w} did not decode to a clean rts"


def test_w8_needs_no_shift_at_all(tmp_path):
    """W=256 is the hinge between the two shift arms: `xba` alone IS *256, so
    neither `.if` branch should fire. Included because an off-by-one in the
    `> 8` / `< 8` conditions would be invisible at 512 and 128."""
    ops, _ = bind(tmp_path, 8, 8, 4)
    assert [o[0] for o in ops[6:9]] == ["and #", "xba", "sta dp"], \
        f"W=256 emitted a shift it does not need: {ops[6:10]}"


def test_a_world_too_tall_for_the_row_scale_is_REFUSED(tmp_path):
    """The stated limit is a gate, not a comment. 64 wide x 512 tall puts 512
    whole rows in one 32 KB chunk, so the masked row index reaches 511 and
    `xba` stops being a shl-8. It must refuse rather than miscompute."""
    ok, _, out = assemble(tmp_path, PREAMBLE.format(w=6, h=9, chunks=1))
    assert not ok, "a world with >256 rows per chunk assembled — silent miscompute"
    assert "exceeds 256 rows" in out, out


def test_a_short_wide_world_is_ACCEPTED(tmp_path):
    """The control arm for the limit above: the refusal must be about SHAPE,
    not about size. 64x32 maxes the row index at
    31 and is expressible — if this goes red the guard has become a blanket
    ban on small worlds, which is a different and wrong rule."""
    ops, _ = bind(tmp_path, 6, 5, 1)
    assert ops[4] == ("and #", 31), f"tile-y mask is not #31: {ops[4]}"
    assert [o[0] for o in ops[6:10]] == ["and #", "xba", "lsr", "lsr"], \
        f"row scale is not `and #` + xba + two lsr (*64): {ops[6:10]}"
    assert ops[6] == ("and #", 511), "rows-per-chunk mask is not #511"
