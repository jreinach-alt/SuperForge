"""The claims.reg writer-side gate (docs/09 §2.1 hole 1, closed this change).

no_literals' reg-ownership pass: an in-scope sta/stx/sty/stz to a bank-0 port
carrying a REGISTER_FOOTPRINT name must be declared by, or covered by, the
claim set its file answers to. Fixtures live under tests/fixtures/reg_gate/
as firing + silent siblings (the width-lint fixture pattern): every rule has
a case that FIRES and a neighbouring case that must stay SILENT, so the gate
is proven to have teeth and proven not to bite the shipped conventions.

The in-tree regression guard at the bottom runs the real tool over the real
tree with freshly-built maps, then proves the pass was ARMED in that exact
invocation shape by planting a copy — a green run of a disarmed pass is the
failure mode tests/test_make_gates.py exists to warn about.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
TOOL = SUPERFORGE / "allocator" / "no_literals.py"
FIX = SUPERFORGE / "tests" / "fixtures" / "reg_gate"

sys.path.insert(0, str(SUPERFORGE / "allocator"))
import no_literals as NL                                   # noqa: E402
import schemas                                             # noqa: E402

# A synthetic map in allocate.py's emitted shape (test_no_literals.py's
# pattern). The game fixtures' contexts read scenes.<id>.reg / channels /
# dma_init / placements and the globals list — exactly the fields the real
# emission carries; test_span_pins + the in-tree guard below tie the shape
# back to the real allocator output.
GFIX_MAP = {
    "spaces": {"wram_bytes": 0x20000, "wram_base_addr": 0x7E0000,
               "dp_bytes": 256, "vram_words": 0x8000,
               "io_allowed": [[0x2100, 0x21FF], [0x4200, 0x43FF]]},
    "globals": [
        {"sym": "ES_GLOB_STATE", "class": "dp", "start": 0, "size": 2,
         "scope": "global", "consumer": "engine:rgfx_glob", "kind": ""},
    ],
    "spc_owner": None,
    "scenes": {
        "s1": {
            "placements": [
                {"sym": "ES_SF_PAL", "class": "cgram", "start": 16,
                 "size": 16, "scope": "s1", "consumer": "engine:rgfx_scenef",
                 "kind": ""},
            ],
            "channels": [],
            "dma_init": [],
            "reg": [
                {"name": "sf_m7sel", "registers": ["M7SEL"], "seed": False,
                 "consumer": "engine:rgfx_scenef",
                 "scene_writes": ["M7SEL"], "scene_writes_shared": []},
                # INIDISP is HELD but not opened, on purpose: gfix/main.asm
                # writes only $4200, and gfix_owned/main.asm (item 5) writes
                # $2100 to prove the owned-but-unopened refusal fires while
                # the neighbouring $4200 stays silent. This is the sm_display
                # shape, which is why scene_writes is a LIST.
                {"name": "glob_nmi", "registers": ["INIDISP", "NMITIMEN"],
                 "seed": False, "consumer": "engine:rgfx_glob",
                 "scene_writes": ["NMITIMEN"], "scene_writes_shared": []},
            ],
            "vblank_bytes": 0, "vblank_transfers": 0,
        },
        "s2": {
            "placements": [],
            "channels": [],
            "dma_init": [],
            "reg": [
                {"name": "glob_nmi", "registers": ["INIDISP", "NMITIMEN"],
                 "seed": False, "consumer": "engine:rgfx_glob",
                 "scene_writes": ["NMITIMEN"], "scene_writes_shared": []},
            ],
            "vblank_bytes": 0, "vblank_transfers": 0,
        },
        # item 5: s3 exercises the scene tier's owned-but-unopened refusal
        # against the SAME claim that opens NMITIMEN — one claim, one register
        # opened and one not, which is the sm_display shape.
        "s3": {
            "placements": [],
            "channels": [],
            "dma_init": [],
            "reg": [
                {"name": "glob_nmi", "registers": ["INIDISP", "NMITIMEN"],
                 "seed": False, "consumer": "engine:rgfx_glob",
                 "scene_writes": ["NMITIMEN"], "scene_writes_shared": []},
            ],
            "vblank_bytes": 0, "vblank_transfers": 0,
        },
        # item 5: s4 is the SPAN case — one claim named ALU, opening nothing.
        # $4204 is inside its span and no footprint name sits there.
        "s4": {
            "placements": [],
            "channels": [],
            "dma_init": [],
            "reg": [
                {"name": "sp_alu", "registers": ["ALU"], "seed": False,
                 "consumer": "engine:rgfx_span",
                 "scene_writes": [], "scene_writes_shared": []},
            ],
            "vblank_bytes": 0, "vblank_transfers": 0,
        },
        # gfix_bad's scene: present so its main.asm context resolves; its
        # globals list is empty, which is the point of that fixture.
        "sb": {
            "placements": [], "channels": [], "dma_init": [], "reg": [],
            "vblank_bytes": 0, "vblank_transfers": 0,
        },
    },
}


# item 5 / M4b: the `covered` arm's own map. Separate from GFIX_MAP so the
# scene ids do not collide, and because these scenes are the only ones that
# need `channels` entries — GFIX_MAP's three all carry `"channels": []`, so
# every covered-arm fixture is an (asm, map) PAIR rather than just an .asm.
# Note the `consumer` key on the channel entries: that is M2b, and M4b's rule
# is the only thing that reads it. Before M2b these entries carried None.
GFIX_COV_MAP = {
    "spaces": GFIX_MAP["spaces"],
    "globals": [],
    "spc_owner": None,
    "scenes": {
        # s4 — covered by an hdma claim and declared by NOBODY. FIRES.
        "s4": {
            "placements": [],
            "channels": [{"name": "cov_m7", "ch": 3,
                          "registers": ["M7A", "M7B"], "band": [0, 224],
                          "phase": "active", "bbad": 0x1B, "dmap": 3,
                          "consumer": "engine:rgfx_cov"}],
            "dma_init": [], "reg": [],
            "vblank_bytes": 0, "vblank_transfers": 0,
        },
        # s5 — covered AND opened. SILENT. race's BGMODE shape; cannot
        # discriminate between the two readings (see s7).
        "s5": {
            "placements": [],
            "channels": [{"name": "cov_mode", "ch": 3, "registers": ["BGMODE"],
                          "band": [0, 224], "phase": "active", "bbad": 0x05,
                          "dmap": 0, "consumer": "engine:rgfx_cov"}],
            "dma_init": [],
            "reg": [{"name": "cov_seed", "registers": ["BGMODE"], "seed": True,
                     "consumer": "engine:rgfx_cov",
                     "scene_writes": ["BGMODE"], "scene_writes_shared": []}],
            "vblank_bytes": 0, "vblank_transfers": 0,
        },
        # s6 — a region data port covered by a cgram PLACEMENT. SILENT: the
        # latch/data half is not narrowed.
        "s6": {
            "placements": [{"sym": "ES_COV_PAL", "class": "cgram", "start": 0,
                            "size": 32, "scope": "s6",
                            "consumer": "engine:rgfx_cov", "kind": ""}],
            "channels": [], "dma_init": [], "reg": [],
            "vblank_bytes": 0, "vblank_transfers": 0,
        },
        # s7 — THE DISCRIMINATOR. rgfx_cov covers TM with a transfer claim AND
        # opens it on a [[claims.reg]], but scene_writes is EMPTY. Weak
        # reading: accept. Strong reading (built): refuse.
        "s7": {
            "placements": [],
            "channels": [{"name": "cov_tm", "ch": 3, "registers": ["TM"],
                          "band": [0, 224], "phase": "active", "bbad": 0x2C,
                          "dmap": 0, "consumer": "engine:rgfx_cov"}],
            "dma_init": [],
            "reg": [{"name": "cov_hold", "registers": ["TM"], "seed": True,
                     "consumer": "engine:rgfx_cov",
                     "scene_writes": [], "scene_writes_shared": []}],
            "vblank_bytes": 0, "vblank_transfers": 0,
        },
        # the NAME axis. cov_plane holds COLDATA_R — one plane of
        # $2132 — and opens nothing. Four names cover that port and the
        # alphabetically-first, COLDATA, is NOT one this claim holds.
        "s8": {
            "placements": [], "channels": [], "dma_init": [],
            "reg": [{"name": "cov_plane", "registers": ["COLDATA_R"],
                     "seed": False, "consumer": "engine:rgfx_cov",
                     "scene_writes": [], "scene_writes_shared": []}],
            "vblank_bytes": 0, "vblank_transfers": 0,
        },
        # the KIND axis. A dma_init drives BGMODE. `seed` exempts
        # hdma ONLY, so the hdma branch's advice would be refused here. (All
        # four live dma_init claims name VMDATAL/VMDATAH, which are data ports
        # and never reach this branch — hence synthetic, and hence latent.)
        "s9": {
            "placements": [], "channels": [],
            "dma_init": [{"name": "cov_init", "ch": 1, "registers": ["BGMODE"],
                          "phase": "forced_blank", "bbad": 0x05, "dmap": 0,
                          "consumer": "engine:rgfx_cov"}],
            "reg": [], "vblank_bytes": 0, "vblank_transfers": 0,
        },
        # s6's silence has TWO causes (the placement puts CGDATA
        # in `covered` AND puts cgram in `res`), so no single-rule neutering
        # can turn it red — which is what made it read as a fixture that
        # cannot fail. s11 isolates the surviving route (a transfer claim's
        # NAME, no placement anywhere) and s12 is the firing sibling both of
        # them were missing: identical writes, nothing claimed.
        "s11": {
            "placements": [],
            "channels": [{"name": "cov_cgd", "ch": 5, "registers": ["CGDATA"],
                          "band": [0, 224], "phase": "vblank", "bbad": 0x22,
                          "dmap": 0, "consumer": "engine:rgfx_cov"}],
            "dma_init": [], "reg": [],
            "vblank_bytes": 0, "vblank_transfers": 0,
        },
        "s12": {
            "placements": [], "channels": [], "dma_init": [], "reg": [],
            "vblank_bytes": 0, "vblank_transfers": 0,
        },
        # the NAME axis on the TRANSFER branch: the seed'd reg
        # claim the advice asks for must name the plane the hdma claim drives,
        # or `seed = true` has nothing to override and is refused in its turn.
        "s10": {
            "placements": [],
            "channels": [{"name": "cov_rplane", "ch": 4,
                          "registers": ["COLDATA_R"], "band": [0, 224],
                          "phase": "active", "bbad": 0x32, "dmap": 0,
                          "consumer": "engine:rgfx_cov"}],
            "dma_init": [], "reg": [],
            "vblank_bytes": 0, "vblank_transfers": 0,
        },
    },
}


def in_class_count(stdout: str) -> int:
    """The `N in-class` figure out of the summary line's category census.

    A helper rather than an inline split because the line grew a clause (item
    5's `scene_writes: N claim(s) validated`) and a positional parse silently
    read the wrong number when it did."""
    m = re.search(r"(\d+) in-class", stdout)
    assert m, f"no in-class census in summary line:\n{stdout}"
    return int(m.group(1))


def run_on(tmp_path, *files: Path, map_dict=GFIX_MAP):
    mp = tmp_path / "symbol_map.json"
    mp.write_text(json.dumps(map_dict))
    return subprocess.run(
        [sys.executable, str(TOOL), "--map", str(mp),
         *[str(f) for f in files]],
        capture_output=True, text=True)


# --------------------------------------------------------------------------
# feature-file context: engine/features/<name>/*.asm answers to its own toml
# --------------------------------------------------------------------------

def test_feature_undeclared_write_fires(tmp_path):
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_fires/rgfx_fires.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "[reg]" in r.stderr and "$2105" in r.stderr
    assert "BGMODE" in r.stderr and "rgfx_fires" in r.stderr
    # the refusal names who DOES own the port among sibling features —
    # here nobody (the rgfx_* siblings do not declare BGMODE)
    assert "declared by nobody" in r.stderr
    assert "feature.toml" in r.stderr


def test_feature_covered_and_declared_writes_silent(tmp_path):
    """The false-positive guard: latches covered by their region's resource claim, data ports covered
    by region classes, a declared reg port — none may flag."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_covered/rgfx_covered.asm")
    assert r.returncode == 0, r.stdout + r.stderr


def test_feature_hdma_port_claim_covers_cpu_store(tmp_path):
    """The vwf shape: no vram claim; VMDATAL/H named on a vblank hdma claim.
    Its `sta $2118` is 'a data port you claim as a port' — silent."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_hdma_port/rgfx_hdma_port.asm")
    assert r.returncode == 0, r.stdout + r.stderr


def test_feature_dma_init_only_port_claim_covers_cpu_store(tmp_path):
    """the covered branch's dma_init HALF, isolated — no vram
    claim, no hdma claim; VMDATAL/H named on a [[claims.dma_init]] alone.
    Every in-tree dma_init holder also holds the region claim, so only this
    fixture pins the branch against drift."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_dma_init_port/"
                     "rgfx_dma_init_port.asm")
    assert r.returncode == 0, r.stdout + r.stderr


def test_refusal_names_hdma_and_dma_init_port_owners(tmp_path):
    """the owner survey covers hdma/dma_init claims naming the
    port, labelled by claim kind — a COLDATA-shaped finding names the plane
    claims instead of 'nobody'. Here $2118's owners are rgfx_hdma_port's
    hdma claim and rgfx_dma_init_port's dma_init claim."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_data_port_fires/"
                     "rgfx_data_port_fires.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "[reg]" in r.stderr and "$2118" in r.stderr
    assert "declared elsewhere by" in r.stderr
    assert "rgfx_dma_init_port (dma_init claim 'rgfx_dip_up')" in r.stderr
    assert "rgfx_hdma_port (hdma claim 'rgfx_hp_q')" in r.stderr
    assert "declared by nobody" not in r.stderr


def test_feature_alias_spelling_gets_literal_verdict(tmp_path):
    """`X = $2100 + 5` / `sta a:X` may not evade the gate."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_alias/rgfx_alias.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "[reg]" in r.stderr and "$2105" in r.stderr and "BGMODE" in r.stderr


def test_azf_initial_symbol_fires_bare_and_prefixed(tmp_path):
    """STORE_RE's old `[azf]?:?` ate the bare leading
    letter of `sta FADE_PORT`, so the bare spelling evaded while
    `sta a:FADE_PORT` fired. Both spellings must fire — one finding each,
    at the two store lines."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_azf_evasion/rgfx_azf_evasion.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    reg_lines = [ln for ln in r.stderr.splitlines() if "[reg]" in ln]
    assert len(reg_lines) == 2, r.stderr          # bare AND prefixed, no more
    assert all("$2100" in ln and "INIDISP" in ln for ln in reg_lines), r.stderr
    assert ":13:" in reg_lines[0] and ":14:" in reg_lines[1], r.stderr
    # the sibling survey names the declared owner (not "nobody")
    assert "declared elsewhere by rgfx_azf_declared " \
           "(claim 'rgfx_azfd_inidisp')" in r.stderr


def test_azf_initial_symbol_for_declared_port_silent(tmp_path):
    """The silent sibling: an a-initial symbol for a DECLARED port must
    resolve as the full name (no leading-letter mis-parse) and produce zero
    findings for either spelling — no double fire."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_azf_declared/rgfx_azf_declared.asm")
    assert r.returncode == 0, r.stdout + r.stderr


def test_alu_span_write_fires_off_base_port(tmp_path):
    """$4203 (WRMPYB) is not the footprint's ALU port — the span makes it
    answer to the ALU name anyway."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_alu_fires/rgfx_alu_fires.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "$4203" in r.stderr and "ALU" in r.stderr


def test_span_alias_refusal_explains_itself(tmp_path):
    """$4203 is WRMPYB and $2141 is APUI01 — neither is the port
    its covering NAME sits at, because ALU and APUIO each own a BLOCK under
    one name. Without saying so the refusal reads "$4203 (ALU)" and the
    author's first thought is that the tool is confused.
    A port that IS its name's base must not carry the clause."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_alu_fires/rgfx_alu_fires.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "inside `ALU`'s span" in r.stderr, r.stderr
    assert "one resource, one name, several ports" in r.stderr
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_fires/rgfx_fires.asm")
    assert "span" not in r.stderr, r.stderr     # $2105 IS BGMODE's own port


def test_alu_claim_covers_whole_span(tmp_path):
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_alu_silent/rgfx_alu_silent.asm")
    assert r.returncode == 0, r.stdout + r.stderr


def test_override_with_reason_suppresses(tmp_path):
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_override/rgfx_override.asm")
    assert r.returncode == 0, r.stdout + r.stderr


def test_bare_override_is_itself_a_finding(tmp_path):
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_bare_override/"
                     "rgfx_bare_override.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "bare `; REG-LINT: ok`" in r.stderr


# --------------------------------------------------------------------------
# the latch/data category — the 48-site blind spot, closed
# --------------------------------------------------------------------------

def test_latch_write_without_the_resource_claim_fires(tmp_path):
    """the single largest coverage item. VMAIN/VMADDL carry no
    REGISTER_FOOTPRINT name, so the earlier gate `continue`d them as
    "unnamed: unclaimable, exempt" — a verdict reached by the footprint table
    happening not to name them rather than by a rule, and one that left 48 of
    the live tree's 158 non-channel io write sites unchecked."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_latch_fires/rgfx_latch_fires.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    reg = [ln for ln in r.stderr.splitlines() if "[reg]" in ln]
    assert len(reg) == 2, r.stderr              # $2115 and $2116, one each
    assert "$2115" in r.stderr and "VMAIN" in r.stderr
    assert "$2116" in r.stderr and "VMADDL" in r.stderr
    # the verdict must teach the satisfying claim, not just refuse
    assert "claims neither a `vram` region" in r.stderr
    assert "VMDATAH" in r.stderr and "VMDATAL" in r.stderr


def test_latch_write_under_a_region_claim_is_silent(tmp_path):
    """The false-positive guard for the latch/data category: the same two
    writes under a
    `vram` region claim. This is the shape of the entire live tree, which is
    why closing a 30% blind spot cost ZERO new declarations."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_latch_silent/rgfx_latch_silent.asm")
    assert r.returncode == 0, r.stdout + r.stderr


def test_latch_covered_by_naming_the_data_port(tmp_path):
    """The live `vwf` shape: no vram REGION claim, VMDATAL/H named on a vblank
    hdma claim. Naming a resource's data port covers that resource's LATCHES
    too — the latch is the *where* of the port you claimed. Load-bearing: vwf's
    single `stx a:$2116` is a real in-tree site, and a latch rule that fired on
    it would be unusable."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_latch_byname/rgfx_latch_byname.asm")
    assert r.returncode == 0, r.stdout + r.stderr


def test_latch_and_data_refusals_name_the_siblings_that_cover_them(tmp_path):
    """The owner survey must compose with the latch/data category.

    The survey looked only at footprint NAMES, and that category is satisfied
    by a REGION claim — for a latch, by a name that resolves to a DIFFERENT
    port. The two never joined, so every one of the 79 newly-covered latch
    sites, and every region-covered data site, said *"declared by nobody"*
    while a sibling plainly held the covering claim. Affirmatively wrong, not
    merely absent — and the exact sentence the fix
    existed to stop, reintroduced on the category the latch rule added.

    Both arms, on both categories. The siblings here are pre-existing fixtures
    written for other rules, so this cannot pass by matching a fixture tuned
    to it.
    """
    # --- a LATCH site: $2115/$2116, in a feature claiming nothing vram-ish
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_latch_fires/rgfx_latch_fires.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "declared by nobody" not in r.stderr, r.stderr
    # the REGION arm — a sibling holding [[claims.vram]] may drive this latch
    assert "rgfx_covered (vram region claim)" in r.stderr, r.stderr
    assert "rgfx_latch_silent (vram region claim)" in r.stderr, r.stderr
    # the NAME arm — VMDATAL/H on a claim covers that resource's latches too,
    # and $2116 is not a port any of those names resolves TO
    assert ("rgfx_hdma_port (hdma claim 'rgfx_hp_q' names VMDATAH/VMDATAL)"
            in r.stderr), r.stderr

    # --- a DATA site: $2118, which the port-name survey could already see.
    # Its region-claiming holders were the half that went missing.
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_data_port_fires/"
                     "rgfx_data_port_fires.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "declared by nobody" not in r.stderr, r.stderr
    assert "rgfx_covered (vram region claim)" in r.stderr, r.stderr
    # ... and the port-name statement is still the one made for a sibling that
    # names $2118 itself: the more precise clause wins, and is not doubled
    assert "rgfx_hdma_port (hdma claim 'rgfx_hp_q')" in r.stderr, r.stderr
    assert "rgfx_hdma_port (vram region claim)" not in r.stderr, r.stderr


def test_the_survey_and_the_rule_ask_the_same_question():
    """The root cause was two pieces of code answering "does this claim set
    cover this resource?" — the rule's and the survey's — and only one of them
    knowing about region claims. Pinned as one predicate, since a second
    reader is how they drifted apart the first time."""
    assert NL.RegContext.satisfies_resource.__doc__
    ctx = NL.RegContext("feature 'x'", {}, set(), "hint",
                        names={"VMDATAL"}, res=set())
    # both arms of the rule, asked through the context ...
    assert ctx.satisfies_resource("vram", "VMADDL")
    assert not ctx.satisfies_resource("cgram", "CGADD")
    region = NL.RegContext("feature 'y'", {}, set(), "hint",
                           names=set(), res={"cgram"})
    assert region.satisfies_resource("cgram", "CGADD")
    # ... and the survey's helper is that same function, not a copy of it
    assert NL._covers_resource(set(), {"VMDATAL"}, "vram", "VMADDL")
    assert NL._covers_resource({"cgram"}, set(), "cgram", "CGADD")
    assert not NL._covers_resource(set(), set(), "vram", "VMADDL")


def test_wmdata_write_without_a_wram_claim_fires(tmp_path):
    """Latent (no in-tree $2180-$2183 writer today) but real:
    WMDATA/WMADD* are a SINGLE GLOBAL CURSOR, so two undeclared users is
    precisely the silent fight. Free once the latch category landed — the
    same category machinery, one more resource."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_wmdata_fires/"
                     "rgfx_wmdata_fires.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    reg = [ln for ln in r.stderr.splitlines() if "[reg]" in ln]
    assert len(reg) == 2, r.stderr
    assert "$2180" in r.stderr and "WMDATA" in r.stderr
    assert "$2181" in r.stderr and "WMADDL" in r.stderr
    # WMDATA/WMADD* carry NO footprint name, so the only satisfying claim is
    # the region one — and the refusal must say exactly that rather than
    # offering a [[claims.reg]] the schema would then reject.
    assert "holds no `wram` claim" in r.stderr
    assert "claim the `wram` region" in r.stderr
    assert "no [[claims.reg]] can name it" in r.stderr
    assert "add a [[claims.wram]] to" in r.stderr
    assert "add a [[claims.reg]] to" not in r.stderr


def test_rmw_writes_to_an_undeclared_port_fire(tmp_path):
    """`inc a:$2106` and `trb a:$2106` WRITE MOSAIC; the earlier write set was
    sta/stx/sty/stz, so they were invisible — the old gate found 0 here and
    this one finds 2. Latent in this tree — zero live RMW instructions
    target an io port, every one is accumulator-mode or a DP symbol — so this
    fixture IS the coverage."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_rmw_fires/rgfx_rmw_fires.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    reg = [ln for ln in r.stderr.splitlines() if "[reg]" in ln]
    assert len(reg) == 2, r.stderr              # inc AND trb
    assert all("$2106" in ln and "MOSAIC" in ln for ln in reg), r.stderr


def test_rmw_writes_to_a_declared_port_are_silent(tmp_path):
    """The silent sibling: the new mnemonics go through the SAME ownership
    check as a store rather than becoming an unconditional finding — and
    accumulator-mode RMW (`lsr a`, 39 live sites) never resolves to a port."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_rmw_silent/rgfx_rmw_silent.asm")
    assert r.returncode == 0, r.stdout + r.stderr


def test_mvn_mvp_are_deliberately_not_write_shaped():
    """Both take BANK bytes, never an address, so no operand of theirs is ever
    an io port. Pinned so a future 'add every write-shaped mnemonic' sweep
    cannot quietly add them."""
    assert "mvn" not in NL.REG_WRITE_MN and "mvp" not in NL.REG_WRITE_MN
    assert {"sta", "stx", "sty", "stz"} <= NL.REG_WRITE_MN
    assert {"inc", "dec", "asl", "lsr", "rol", "ror",
            "trb", "tsb"} <= NL.REG_WRITE_MN


# --------------------------------------------------------------------------
# the fail-closed fold — reporting the base IS the laundering
# --------------------------------------------------------------------------

@pytest.mark.parametrize("fixture,why", [
    ("rgfx_unfold_sym", "`+ SYM` — the offset is a symbol"),
    ("rgfx_unfold_minus", "`- 1` — subtractive, and $2107-1 IS MOSAIC"),
    ("rgfx_unfold_or", "`| $0006` — bitwise, not additive"),
])
def test_unfoldable_offset_fails_closed(tmp_path, fixture, why):
    """Before this rule, `_port_expr_value` returned None for anything that
    was not a `+`-sum, `_store_port` passed the None on, and the site was
    SILENTLY SKIPPED. All three
    spellings were proven live by the convergence (§1.4): LANDED silent,
    UNLANDED fires.

    `sta a:$2107 - 1` is the sharpest: under the old fold it produced ZERO findings of
    ANY kind, because the ADDRESS rule permits $2107 as an io literal."""
    r = run_on(tmp_path,
               FIX / f"engine/features/{fixture}/{fixture}.asm")
    assert r.returncode == 1, why + "\n" + r.stdout + r.stderr
    reg = [ln for ln in r.stderr.splitlines() if "[reg]" in ln]
    assert len(reg) == 1, r.stderr
    assert "cannot be folded from this file" in r.stderr
    # the refusal must not name a port — naming the base IS the laundering
    assert "$2100 + 5` is BGMODE, not INIDISP" in r.stderr
    assert "REG-LINT: ok" in r.stderr           # the escape hatch is offered


def test_unfoldable_offset_inside_the_channel_file_is_silent(tmp_path):
    """The silent sibling and the deliberate exception: the tree's own
    `<FEAT>_REGS = $4300 + ES_[HD]_<CLAIM>_CH * 16` idiom. 115 live sites are
    this shape (measured with tools/reg_census.py); the whole $4300-$437F
    extent belongs to the channel rules, so an unfoldable term there resolves
    to the base and is handed on. A fold that failed closed on these would
    have made the fail-closed fold unlandable.

    Asserted as "zero [reg] findings", not "exit 0": this fixture's hand-written
    DMAP/BBAD literals DO trip the [encoding] rule, and that is the point —
    $4300-$437F is the channel rules' territory, and a single write must never
    be reported by two rules."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_unfold_chan/rgfx_unfold_chan.asm")
    reg = [ln for ln in r.stderr.splitlines() if "[reg]" in ln]
    assert reg == [], r.stderr
    enc = [ln for ln in r.stderr.splitlines() if "[encoding]" in ln]
    assert len(enc) == 2, r.stderr          # the channel rule DOES own them
    assert "cannot be folded" not in r.stderr


def test_unresolved_is_not_a_real_port():
    """UNRESOLVED_PORT shares the return channel with real ports, so it must
    be outside the io window in both directions — otherwise a fail-closed
    site would be mistaken for a resolved one."""
    assert NL.UNRESOLVED_PORT < 0x2100
    assert not NL._in_io(NL.UNRESOLVED_PORT)
    assert NL._reg_category(0x2105)[0] != "unresolved"


def test_equate_definitions_use_the_same_resolver_as_writes(tmp_path):
    """The fold's second door. A later review found the
    DEFINITION side taking `rest.split("+")[0]`, so `BGM = $2100 + 5`
    resolved to INIDISP and laundered a BGMODE write. One resolver cannot
    disagree with itself — `_port_aliases` now calls `_store_port`."""
    src = tmp_path / "engine" / "features" / "eqp"
    src.mkdir(parents=True)
    (src / "feature.toml").write_text('name = "eqp"\nrole = "fixture"\n')
    f = src / "eqp.asm"
    f.write_text(".p816\nBGM = $2100 + 5\n    sep #$20\n"
                 "    lda #1\n    sta a:BGM\n    rts\n")
    r = run_on(tmp_path, f)
    assert r.returncode == 1, r.stdout + r.stderr
    # $2105 (BGMODE), NOT $2100 (INIDISP)
    assert "$2105" in r.stderr and "BGMODE" in r.stderr, r.stderr
    assert "INIDISP" not in r.stderr.split("is BGMODE")[0], r.stderr
    # ... and an UNFOLDABLE equate propagates the fail-closed verdict
    f.write_text(".p816\n.import SLOT\nBGM = $2100 + SLOT\n    sep #$20\n"
                 "    lda #1\n    sta a:BGM\n    rts\n")
    r = run_on(tmp_path, f)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "cannot be folded from this file" in r.stderr, r.stderr


# --------------------------------------------------------------------------
# unnamed ports are a finding-with-override
# --------------------------------------------------------------------------

def test_unnamed_port_write_fires(tmp_path):
    """The confirmed default. $4201 (WRIO) is INSIDE io_allowed
    but carries no REGISTER_FOOTPRINT name, so no claim can describe it — and
    the earlier gate `continue`d exactly that as "unnamed port: unclaimable,
    exempt". That is the
    census-of-undeclared-writers disease C4 abolished, re-entering through the
    one door the gate left open.

    Landed only after the latch category — without it this fired on all
    48 latch sites at once — and surveyed first: ZERO unnamed sites in the
    live population, so it cost zero declarations."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_unnamed_fires/"
                     "rgfx_unnamed_fires.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    reg = [ln for ln in r.stderr.splitlines() if "[reg]" in ln]
    assert len(reg) == 1, r.stderr
    assert "$4201" in r.stderr
    assert "no REGISTER_FOOTPRINT name" in r.stderr
    assert "Add the name to `REGISTER_FOOTPRINT` first" in r.stderr
    # the refusal must name the escape hatch, not just the problem
    assert "if the port is deliberately unowned" in r.stderr
    # the refusal must not pretend a claim would fix it as things stand
    assert "cannot declare it as things stand" in r.stderr


def test_unnamed_port_write_with_a_reasoned_override_is_silent(tmp_path):
    """It is finding-with-OVERRIDE, not finding-full-stop. A port no claim
    class describes yet must have an escape hatch, or the only way to write
    one is to invent a footprint name for it."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_unnamed_override/"
                     "rgfx_unnamed_override.asm")
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_settlement_example_never_reaches_the_reg_rule(tmp_path):
    """$4016/$4017 — the spec's own worked example of an unnamed port —
    sit OUTSIDE io_allowed, so the ADDRESS rule refuses them first and the
    reg rule never sees them. A fixture built from the settlement's example
    would 'pass' while testing a different rule entirely — a failure shape
    this repo has paid for more than once. When a spec hands you an example,
    RUN it."""
    src = tmp_path / "engine" / "features" / "joy"
    src.mkdir(parents=True)
    (src / "feature.toml").write_text('name = "joy"\nrole = "fixture"\n')
    f = src / "joy.asm"
    f.write_text(".p816\n    sep #$20\n    lda #1\n    sta a:$4016\n    rts\n")
    r = run_on(tmp_path, f)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "[address]" in r.stderr, r.stderr
    assert "[reg]" not in r.stderr, r.stderr


# --------------------------------------------------------------------------
# an unreadable declaration is a FINDING, never a traceback
# --------------------------------------------------------------------------

def _staged(tmp_path, fixture: str, suffix: str) -> Path:
    """Copy a fixture dir into tmp and rename its parked toml into place.
    Parked as feature.toml.<suffix> in the repo so the allocator's
    `*/feature.toml` glob never sees a deliberately-broken declaration."""
    src = FIX / "engine" / "features" / fixture
    dst = tmp_path / "engine" / "features" / fixture
    shutil.copytree(src, dst)
    (dst / f"feature.toml.{suffix}").rename(dst / "feature.toml")
    return dst / f"{fixture}.asm"


def test_unparseable_toml_is_a_finding_not_a_traceback(tmp_path):
    """Before this rule, a TOML SYNTAX error raised tomllib.TOMLDecodeError
    straight through the gate — the build still failed (exit 1), so this is a
    diagnostics defect rather than a soundness one, but a traceback tells the
    author nothing about what to fix."""
    asm = _staged(tmp_path, "rgfx_badtoml", "malformed")
    r = run_on(tmp_path, asm)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Traceback" not in r.stderr, r.stderr
    assert "TOMLDecodeError" not in r.stderr, r.stderr
    assert "does not parse as TOML" in r.stderr
    assert "line 2" in r.stderr                 # the position is carried
    # ... and it says WHY falling through would be dangerous
    assert "WEAKEST check" in r.stderr


def test_wrongly_typed_toml_is_a_finding_not_a_traceback(tmp_path):
    """Its sibling, filed by a later review
    against its OWN gate. Here schemas.load_feature's type validation already
    produces a clean SchemaError finding; the added AttributeError/TypeError
    catch is what stops a future loader change reopening it as a traceback."""
    asm = _staged(tmp_path, "rgfx_wrongtype", "wrongtype")
    r = run_on(tmp_path, asm)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Traceback" not in r.stderr, r.stderr
    assert "failed to load" in r.stderr
    assert "must be <class 'list'>" in r.stderr  # the type is named


def test_a_gate_bug_is_not_laundered_into_a_declaration_complaint():
    """`_load_decl` catches SchemaError / TOMLDecodeError / AttributeError /
    TypeError and deliberately NOT `Exception`. A crash inside the gate must
    surface as a crash, not as 'your feature.toml is malformed'."""
    src = (SUPERFORGE / "allocator" / "no_literals.py").read_text()
    body = src.split("def _load_decl", 1)[1].split("\ndef ", 1)[0]
    assert "except Exception" not in body, body
    for exc in ("schemas.SchemaError", "TOMLDecodeError",
                "AttributeError", "TypeError"):
        assert exc in body, exc


# --------------------------------------------------------------------------
# the summary line reports what was EXAMINED, and at which tier
# --------------------------------------------------------------------------

def test_summary_line_reports_tier_split_and_site_census(tmp_path):
    """`26 file(s) clean` is true of the ADDRESS rule and says
    nothing about whether the reg pass examined anything.
    The line now carries the TIER split — keeping the weaker scene-union check
    visible, which is docs/09 §2.1 hole 2, still open — and the per-category
    site census."""
    out = subprocess.run(
        [sys.executable, str(TOOL), "--map",
         str(SUPERFORGE / "build" / "mz" / "symbol_map.json"),
         str(SUPERFORGE / "game/microzero/main.asm"),
         *[str(p) for p in sorted(
             (SUPERFORGE / "game/microzero/scenes").glob("*.asm"))],
         *[str(p) for p in sorted(
             (SUPERFORGE / "engine/features").glob("*/*.asm"))]],
        capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    line = out.stdout.strip().splitlines()[-1]
    assert "file(s) clean" in line
    assert "feature-strict" in line and "scene-union" in line \
        and "globals-union" in line, line
    assert "io write-site(s) examined" in line, line
    for cat in ("channel", "data", "latch", "in-class", "unnamed",
                "unresolved"):
        assert f" {cat}" in line, (cat, line)


def test_summary_line_makes_zero_examined_visible(tmp_path):
    """The point of the tiered summary, isolated. The earlier gate printed only "clean"
    for a file it never examined, which is a gate reporting an unchecked file
    as if it had checked it. `0 io write-site(s) examined` is now readable
    instead of needing an instrument to find.

    (a later change removed the "no reg pass" tier entirely, so the way to
    reach zero now is a file with no io writes in it — the number is the
    load-bearing part, not which tier produced it.)"""
    f = tmp_path / "t.asm"
    f.write_text(".p816\n    sep #$20\n    lda #1\n    inc a\n    rts\n")
    r = run_on(tmp_path, f)
    assert r.returncode == 0, r.stdout + r.stderr
    line = r.stdout.strip().splitlines()[-1]
    assert "0 io write-site(s) examined" in line, line


# --------------------------------------------------------------------------
# the override is PORT-SCOPED, not site-radius (both sides missed)
# --------------------------------------------------------------------------

def test_override_does_not_leak_to_an_unrelated_write_next_door(tmp_path):
    """The MEDIUM both gates missed.
    Probe fp12_radius: one `; REG-LINT: ok — BGMODE is safe here by
    construction` silenced an entirely unrelated, undeclared `sta a:$2101`
    (OBSEL) on the next line. BOTH gates: 0 findings. It was filed as an INFO
    and deferred, and never actually tested until now.

    The override is a REVIEWER-FACING artifact — a reviewer reading a stated
    BGMODE reason has no cue that an OBSEL write is riding on it. It now binds
    to the write on its own line."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_ov_radius_leak/"
                     "rgfx_ov_radius_leak.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    reg = [ln for ln in r.stderr.splitlines() if "[reg]" in ln]
    assert len(reg) == 1, r.stderr
    assert "$2101" in reg[0] and "OBSEL" in reg[0], reg[0]
    # ... and the DECLARED BGMODE write it does cover is still silent
    assert "$2106" not in r.stderr, r.stderr


def test_override_naming_a_port_scopes_to_that_port(tmp_path):
    """Override rule 1: `; REG-LINT: ok $2101 — reason` is unambiguous
    wherever it sits, and is the spelling the ambiguous diagnostic points
    at."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_ov_named_port/"
                     "rgfx_ov_named_port.asm")
    assert r.returncode == 0, r.stdout + r.stderr


def test_standalone_override_over_two_ports_is_ambiguous(tmp_path):
    """Override rule 3: a standalone override whose window holds would-be
    findings for TWO DIFFERENT ports excuses NEITHER, and says which ports it
    could not choose between."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_ov_ambiguous/"
                     "rgfx_ov_ambiguous.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    reg = [ln for ln in r.stderr.splitlines() if "[reg]" in ln]
    assert len(reg) == 2, r.stderr
    assert all("AMBIGUOUS" in ln for ln in reg), r.stderr
    assert "$2101" in r.stderr and "$2106" in r.stderr
    assert "Name the port" in r.stderr


def test_unfoldable_write_in_an_ambiguous_window_renders_honestly(tmp_path):
    """The UNRESOLVED_PORT sentinel met the port-scoped override's
    ambiguity rule and was formatted as an address: `$-001`.

    Two defects in one message. `$-001` is not a port, so a reader has
    nothing to look up; and the fix it printed —
    `; REG-LINT: ok $-001 — <reason>` — matches NEITHER override pattern, so
    an author following the advice verbatim gets no override and no
    complaint about that. The refusal now names the STATE the write is in
    and points at the escape hatch that exists for it.
    """
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_ov_unfoldable/"
                     "rgfx_ov_unfoldable.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    reg = [ln for ln in r.stderr.splitlines() if "[reg]" in ln]
    assert len(reg) == 2, r.stderr              # both subjects still refused
    assert all("AMBIGUOUS" in ln for ln in reg), r.stderr
    # the sentinel never reaches a reader, in any spelling
    assert "$-001" not in r.stderr, r.stderr
    assert "-001" not in r.stderr, r.stderr
    # the unfoldable site is described as what it IS ...
    unf = next(ln for ln in reg if "$2100 + STRIDE" in ln)
    assert "cannot be folded from this file" in unf, unf
    assert "no port to NAME" in unf, unf
    assert "on THIS line" in unf, unf           # rule 2, the reachable hatch
    # ... and it keeps _unresolved_verdict's teaching text, which the
    # ambiguity branch used to swallow by returning before it (the
    # third-order note)
    assert "is BGMODE, not INIDISP" in unf, unf
    # ... while the RESOLVED neighbour still gets rule 1's spelling, and the
    # window description names the unfoldable site in prose
    res = next(ln for ln in reg if "write to $2101" in ln)
    assert "`; REG-LINT: ok $2101 — <reason>`" in res, res
    assert "an operand whose port cannot be folded" in res, res


def test_the_ambiguity_refusals_print_advice_that_can_be_typed(tmp_path):
    """The load-bearing half: the printed fix must WORK.

    The strings are lifted out of the tool's own stderr rather than
    hand-copied, so this cannot pass against advice that has drifted from
    what the override grammar accepts — which is exactly how `$-001` shipped.
    """
    src = FIX / "engine" / "features" / "rgfx_ov_unfoldable"
    r = run_on(tmp_path, src / "rgfx_ov_unfoldable.asm")
    named = re.search(r"`(; REG-LINT: ok \$[0-9A-Fa-f]+ — )<reason>`",
                      r.stderr)
    same_line = re.search(r"put `(; REG-LINT: ok — )<reason>` on THIS line",
                          r.stderr)
    assert named and same_line, r.stderr

    dst = tmp_path / "engine" / "features" / "rgfx_ov_unfoldable"
    shutil.copytree(src, dst)
    body = (src / "rgfx_ov_unfoldable.asm").read_text()
    # rule 1: the standalone override, respelled with the port it printed
    body = body.replace(
        "    ; REG-LINT: ok — one of these is safe by construction, but which?",
        "    " + named.group(1) + "typed verbatim from the refusal")
    # rule 2: the same-line form it offered the unfoldable write
    body = body.replace(
        "    sta a:$2100 + STRIDE\n",
        "    sta a:$2100 + STRIDE        "
        + same_line.group(1) + "typed verbatim from the refusal\n")
    (dst / "rgfx_ov_unfoldable.asm").write_text(body)

    r2 = run_on(tmp_path, dst / "rgfx_ov_unfoldable.asm")
    assert r2.returncode == 0, (
        "the tool printed advice its own override grammar rejects\n"
        + r2.stdout + r2.stderr)


def test_an_override_does_not_leak_between_two_unfoldable_writes(tmp_path):
    """The SILENCE half — the sharper defect under the cosmetic one.

    With the sentinel serving as the identity, `-1 == -1` made every write a
    file cannot fold the SAME subject: a same-line override on one silenced
    the next (measured on the pre-fix branch: zero findings). The write it
    silenced here is `sta a:$2107 - 1` — a MOSAIC write, and the fold's own
    sharpest case. A site with no port is identified by its LINE."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_ov_unfold_pair/"
                     "rgfx_ov_unfold_pair.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    reg = [ln for ln in r.stderr.splitlines() if "[reg]" in ln]
    assert len(reg) == 1, r.stderr              # the SECOND write, not both
    assert "$2107 - 1" in reg[0], reg[0]
    assert "cannot be folded from this file" in reg[0], reg[0]
    assert ":27:" in reg[0], reg[0]             # the un-excused line
    # the override on line 26 still covers ITS own write — no over-firing
    assert ":26:" not in r.stderr, r.stderr


def test_unscoped_override_still_works_where_it_was_unambiguous(tmp_path):
    """The port-scoped override is an EXTENSION, not a fork. The unscoped spelling — a
    standalone `; REG-LINT: ok — reason` over a single would-be finding — is
    what all three pre-existing fixtures use and what every live override
    would use (there are currently zero). It must keep working, or the rule
    forks the convention the convergence warned about forking."""
    for fixture in ("rgfx_override", "rgfx_unnamed_override"):
        r = run_on(tmp_path,
                   FIX / f"engine/features/{fixture}/{fixture}.asm")
        assert r.returncode == 0, fixture + "\n" + r.stdout + r.stderr


def test_override_grammar_is_factored_not_duplicated():
    """Its first half. The reg and channel rules carried
    character-identical regex pairs; a third copy is how the separator
    alternations drift apart. One spelling, parameterised by token."""
    reg_ok, reg_bare = NL._override_res("REG-LINT")
    ch_ok, ch_bare = NL._override_res("CHANNEL-LINT")
    assert (NL.REG_OVERRIDE_RE, NL.REG_BARE_OVERRIDE_RE) == (reg_ok, reg_bare)
    assert (NL.OVERRIDE_RE, NL.BARE_OVERRIDE_RE) == (ch_ok, ch_bare)
    # same separator alternation for both, and a reason still required
    for rx, tok in ((reg_ok, "REG-LINT"), (ch_ok, "CHANNEL-LINT")):
        assert rx.search(f"; {tok}: ok — why")
        assert rx.search(f"; {tok}: ok -- why")
        assert rx.search(f"; {tok}: ok - why")
        assert rx.search(f"; {tok}: ok: why")
        assert not rx.search(f"; {tok}: ok")
    # the optional port token parses on both, and a CHANNEL override still
    # must not silence a reg finding (the wrong-token guard)
    assert reg_ok.search("; REG-LINT: ok $2101 — why").group("port") == "2101"
    assert not reg_ok.search("; CHANNEL-LINT: ok — why")


def test_fixture_claims_do_not_collide_with_the_nobody_assertion():
    """Fixture claims are a SHARED NAMESPACE, and this pins it.

    `_feature_port_owners` globs EVERY dir under the fixture root, so a claim
    added to one fixture appears in every other fixture's refusal text. Two
    tests here assert a port is "declared by nobody" — a new fixture claiming
    that port silently turns their message into "declared elsewhere by ...",
    and the failure reads as a bug in the OWNER SURVEY rather than as a
    fixture collision. It cost two rounds to diagnose; a red here
    names the cause in one line instead.

    The namespace WIDENED with that fix: a latch/data refusal now also
    surveys REGION claims (`[[claims.vram]]` and friends), so a region claim
    added to any fixture appears in every other fixture's latch/data refusal
    too. Only footprint names are scanned below, because only footprint names
    have a "nobody" assertion riding on them today — if one is ever written
    for a latch or a data port, extend this to the region claims as well.
    """
    import tomllib
    root = FIX / "engine" / "features"
    claimed: dict[str, list[str]] = {}
    for toml in sorted(root.glob("*/feature.toml")):
        data = tomllib.loads(toml.read_text())
        for kind in ("reg", "hdma", "dma_init"):
            for entry in data.get("claims", {}).get(kind, []):
                for reg in entry.get("registers", []):
                    claimed.setdefault(reg, []).append(toml.parent.name)
    # the ports the "declared by nobody" assertions depend on
    for reg, who in (("BGMODE", "test_feature_undeclared_write_fires"),):
        assert reg not in claimed, (
            f"{claimed.get(reg)} now claim(s) {reg}, which {who} asserts is "
            f"'declared by nobody'. Pick another register for the new fixture "
            f"(see rgfx_rmw_silent/feature.toml's note).")


def test_no_fixture_comment_teaches_the_deleted_exempt_by_scope_rule():
    """A stale rule in prose, and the reason it survived a docs sweep.

    The latch/data category DELETED "a port with no footprint name is
    unclaimable, so it is exempt". A latch is now silent because it rides the
    claim on the RESOURCE its data port serves — a different rule reaching the
    same verdict on the shipped fixtures, which is exactly why nothing went red
    when the comments kept teaching the old one. `rgfx_covered` is the
    canonical false-positive guard for the whole reg pass, so it is the file a
    reader opens to LEARN the rule, and it taught the deleted one for a change.

    A firing/silent fixture pins the verdict and never the explanation; this
    pins the explanation.

    WHAT THIS GUARD ACTUALLY IS (the docstring used to say otherwise): a
    narrow two-phrase SUBSTRING scan over `FIX.rglob("*.asm")`. It parses no
    tense and no grammar. Historical narration survives it — `rgfx_unnamed_
    fires` quotes the old verdict as something the EARLIER gate did — but
    that is because the phrase LIST is narrow enough not to collide with how
    the history happens to be worded, NOT because anything distinguishes a
    past-tense mention from a present-tense claim. A history that happened to
    quote one of these two phrases verbatim would go red, and would be a
    false positive.

    So: widening the list is not free, and the value of a candidate phrase is
    "how likely is a live comment to teach this" weighed against "how likely
    is a history to quote it". A later review offered a file-set widening (scan the
    tomls too); it now catches nothing, because both are fixed. It
    can be taken or not — but it must not be claimed as a catch.
    """
    stale = ("exempt by scope", "no footprint name: exempt")
    for asm in sorted((FIX).rglob("*.asm")):
        text = asm.read_text()
        for phrase in stale:
            assert phrase not in text, (
                f"{asm.relative_to(FIX)} teaches the rule the latch category deleted "
                f"({phrase!r}). A latch is silent because it RIDES THE CLAIM "
                f"on the resource its data port serves — delete that claim "
                f"and it fires. Say that instead.")


def test_category_map_partitions_the_io_window():
    """Every port the gate can resolve gets exactly one category, and the
    latch/data tables name resources RESOURCE_PORT_NAMES knows how to
    satisfy — otherwise a latch would be unsatisfiable by any declaration."""
    for port, (res, _name) in {**NL.REG_LATCH, **NL.REG_DATA}.items():
        assert res in NL.RESOURCE_PORT_NAMES, (hex(port), res)
        assert res in NL.DATA_PORTS, (hex(port), res)
        kind, info = NL._reg_category(port)
        assert kind in ("latch", "data"), (hex(port), kind)
        assert info[0] == res
    # the data ports each resource's names resolve to are the REG_DATA ports
    for res, names in NL.RESOURCE_PORT_NAMES.items():
        ports = {p for p, (r, _n) in NL.REG_DATA.items() if r == res}
        assert ports == set(NL.DATA_PORTS[res]), res
        # ... for the names that are CLAIMABLE. `wram`/WMDATA is the one that
        # is not in REGISTER_FOOTPRINT at all (docs/09 §2.1's "C4 needed none
        # of them as names"), which is why the verdict for it must offer the
        # region claim instead of a name — asserted above.
        claimable = [n for n in names if n in schemas.REGISTER_FOOTPRINT]
        if claimable:
            assert {schemas.REGISTER_FOOTPRINT[n][0]
                    for n in claimable} <= ports, res
    assert [n for n in NL.RESOURCE_PORT_NAMES["wram"]
            if n in schemas.REGISTER_FOOTPRINT] == [], \
        "WMDATA gained a footprint name — the wram verdict can now offer it"
    # channel territory is never a reg finding: the channel rules own it
    for port in (0x420B, 0x420C, 0x4300, 0x437F):
        assert NL._reg_category(port)[0] == "channel", hex(port)


# --------------------------------------------------------------------------
# scene + game-top contexts: game/<g>/... answers to the map / game.toml
# --------------------------------------------------------------------------

def test_scene_declared_and_covered_writes_silent(tmp_path):
    r = run_on(tmp_path, FIX / "game/gfix/scenes/s1.asm")
    assert r.returncode == 0, r.stdout + r.stderr


def test_scene_write_nobody_declares_fires(tmp_path):
    r = run_on(tmp_path, FIX / "game/gfix/scenes/s2.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "[reg]" in r.stderr and "$2106" in r.stderr
    assert "MOSAIC" in r.stderr and "scene 's2'" in r.stderr
    assert "feature this write serves" in r.stderr


def test_main_write_declared_by_global_silent(tmp_path):
    """microzero main.asm's shape: `sta a:$4200` under the global's claim."""
    r = run_on(tmp_path, FIX / "game/gfix/main.asm")
    assert r.returncode == 0, r.stdout + r.stderr


def test_main_write_with_no_global_owner_fires(tmp_path):
    r = run_on(tmp_path, FIX / "game/gfix_bad/main.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "[reg]" in r.stderr and "$2105" in r.stderr
    assert "GLOBAL feature" in r.stderr


def test_scene_file_not_in_map_is_loud(tmp_path):
    """An unmapped scene file is a declaration gap, not a skip."""
    d = tmp_path / "game" / "gfix" / "scenes"
    d.mkdir(parents=True)
    f = d / "ghost.asm"
    f.write_text("; not in game.toml\n.p816\n    rts\n")
    r = run_on(tmp_path, f)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "not a scene in the symbol map" in r.stderr


def test_unrecognised_paths_fall_to_the_composed_union(tmp_path):
    """the tool's DEFAULT tier changed, and this test is where the
    old one was written down.

    Before this rule, a file matching no context shape (the toy, the vendored probes,
    plain tmp sources) got NO reg pass, and that was recorded as stated
    residue. It was fail-OPEN on a new surface: a file added to any scan list
    was silently unchecked and the only thing the gate said about it was
    "clean". Measured: engine/toy/main.asm -> `1 file(s) clean`, ZERO sites
    examined, on a file holding 29 of them.

    The default is now the composed union of every scene in the map — the
    weakest meaningful check ("somebody in this program declared it"), which
    is strictly better than nothing and is sound because the map handed to an
    invocation always belongs to that invocation's game."""
    f = tmp_path / "t.asm"
    f.write_text(".p816\n    lda #1\n    sta a:$2105\n    rts\n")
    r = run_on(tmp_path, f)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "$2105" in r.stderr and "BGMODE" in r.stderr
    assert "composed union" in r.stderr, r.stderr


def test_composed_union_accepts_what_any_scene_OPENS(tmp_path):
    """The silent sibling: the composed union is a UNION, so a port any scene
    OPENS satisfies it. NMITIMEN is opened by rgfx_glob's scene_writes.

    Item 5 changed the verb in this test's name. It used to read "what any
    scene DECLARES" and used $2100 INIDISP, which rgfx_glob holds but does not
    open — that is now the refusal, and its own test is the sibling below."""
    f = tmp_path / "t.asm"
    f.write_text(".p816\n    lda #1\n    sta a:$4200\n    rts\n")
    r = run_on(tmp_path, f)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "composed-union" in r.stdout, r.stdout


def test_composed_union_refuses_a_port_a_scene_only_OWNS(tmp_path):
    """M4 at the FLOOR tier — the toy and the vendored probes take it, so
    leaving it un-narrowed would make it the one door boot code could still
    write anything through.

    $2100 INIDISP is on rgfx_glob's claim and NOT in its scene_writes. The
    refusal must name playtesting rather than say "declared by nobody", and must
    print the line the author has to type."""
    f = tmp_path / "t.asm"
    f.write_text(".p816\n    lda #1\n    sta a:$2100\n    rts\n")
    r = run_on(tmp_path, f)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "$2100" in r.stderr and "INIDISP" in r.stderr
    assert "OWNS this port" in r.stderr and "glob_nmi" in r.stderr
    assert "Ownership is not permission" in r.stderr
    assert 'scene_writes = ["INIDISP"]' in r.stderr, r.stderr


@pytest.mark.parametrize("game,asm,label", [
    ("engine/toy", "engine/toy/main.asm", "toy"),
    ("vendor/probes/probe_vblank", "vendor/probes/probe_vblank.asm", "vblank"),
    ("vendor/probes/probe_vb2reg", "vendor/probes/probe_vb2reg.asm", "vb2reg"),
])
def test_toy_and_probes_are_declared_not_exempted(tmp_path, game, asm, label):
    """Its other half. Having made the default fail-closed, the toy and
    the vendored probes had to actually DECLARE their boot writes — 9 findings
    on the toy alone before the declarations went in, which is the same count
    the convergence's own falsification produced (§1.10).

    Asserts BOTH halves: the file is clean, AND the pass examined a non-zero
    number of sites. "Clean" alone is what the earlier gate said about a file
    it never looked at."""
    out = tmp_path / "map"
    r = subprocess.run(
        [sys.executable, str(SUPERFORGE / "allocator" / "allocate.py"),
         "--game", str(SUPERFORGE / game), "--out", str(out)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run(
        [sys.executable, str(TOOL), "--map", str(out / "symbol_map.json"),
         str(SUPERFORGE / asm)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    line = r.stdout.strip().splitlines()[-1]
    assert "composed-union" in line, line
    n = int(line.split("reg ownership: ")[1].split(" io write-site")[0])
    assert n > 0, line


# --------------------------------------------------------------------------
# the span table cannot drift from the footprint
# --------------------------------------------------------------------------

def test_spans_contain_their_base_port():
    """The spans live in schemas.py beside the comment blocks
    that derive them from Mesen2, not in a companion table in no_literals.

    With one table there is nothing to drift against, so what has to be pinned
    changed: every span must CONTAIN the footprint port that every
    declaration-side check uses. A span edited to no longer cover its own base
    would leave `register_ports`/`_register_conflicts` and the writer-side scan
    describing different resources."""
    for name, ranges in schemas.REGISTER_SPANS.items():
        assert name in schemas.REGISTER_FOOTPRINT, name
        base = schemas.REGISTER_FOOTPRINT[name][0]
        assert any(lo <= base <= hi for lo, hi in ranges), name
        for lo, hi in ranges:
            assert lo <= hi, (name, lo, hi)
    # ALU: $4202-$4206 write ports + $4214-$4217 read ports (schemas.py's
    # AluMulDiv derivation); APUIO: the four mailbox ports; HVIRQ: the four
    # H/V timer ports HTIMEL/H + VTIMEL/H (InternalRegisters.cpp:352-377 —
    # one timer state, one IRQ line, so one name spanning all four).
    assert schemas.REGISTER_SPANS["ALU"] == ((0x4202, 0x4206),
                                             (0x4214, 0x4217))
    assert schemas.REGISTER_SPANS["APUIO"] == ((0x2140, 0x2143),)
    assert schemas.REGISTER_SPANS["HVIRQ"] == ((0x4207, 0x420A),)
    assert schemas.REGISTER_FOOTPRINT["HVIRQ"] == (0x4207, schemas.WHOLE)


def test_covering_names_is_the_reverse_lookup():
    """schemas.register_covering_names is the scan-side direction: the ASM has
    a port and needs the names. A port with no footprint name returns empty —
    that emptiness is what the `unnamed` category is built on."""
    assert schemas.register_covering_names(0x4203) == ("ALU",)
    assert schemas.register_covering_names(0x4216) == ("ALU",)
    assert schemas.register_covering_names(0x2141) == ("APUIO",)
    assert schemas.register_covering_names(0x2105) == ("BGMODE",)
    assert schemas.register_covering_names(0x4201) == ()      # WRIO: unnamed
    assert schemas.register_covering_names(0x2116) == ()      # VMADDL: a latch


def test_no_literals_resolves_ports_through_schemas_spans():
    """The single-source-of-truth property, asserted rather than assumed: the
    gate's port map must be derivable from schemas alone."""
    pn = NL._port_names(schemas.REGISTER_FOOTPRINT)
    for port, names in pn.items():
        assert names == set(schemas.register_covering_names(port)), hex(port)
    assert not hasattr(NL, "RESOURCE_SPANS"), \
        "the companion table is the rejected alternative; it was removed"


def test_data_ports_match_footprint():
    """The region-class data ports are footprint-named ports, at the
    addresses the footprint gives those names."""
    fp = schemas.REGISTER_FOOTPRINT
    assert NL.DATA_PORTS["vram"] == (fp["VMDATAL"][0], fp["VMDATAH"][0])
    assert NL.DATA_PORTS["cgram"] == (fp["CGDATA"][0],)
    assert NL.DATA_PORTS["oam"] == (fp["OAMDATA"][0],)


# --------------------------------------------------------------------------
# in-tree regression guard: the shipped tree is clean AND the pass is armed
# --------------------------------------------------------------------------

def _game_files(game: Path) -> list[Path]:
    """Mirror the Makefile's MZ_ASM/RM_ASM lists."""
    return [game / "main.asm", *sorted((game / "scenes").glob("*.asm")),
            *sorted((SUPERFORGE / "engine" / "features").glob("*/*.asm"))]


@pytest.mark.parametrize("game,label", [("game/microzero", "mz"),
                                        ("game/room", "rm")])
def test_shipped_tree_is_clean(tmp_path, game, label):
    out = tmp_path / label
    r = subprocess.run(
        [sys.executable, str(SUPERFORGE / "allocator" / "allocate.py"),
         "--game", str(SUPERFORGE / game),
         "--features-dir", str(SUPERFORGE / "engine" / "features"),
         "--out", str(out)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run(
        [sys.executable, str(TOOL), "--map", str(out / "symbol_map.json"),
         *[str(f) for f in _game_files(SUPERFORGE / game)]],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_guard_is_armed_against_a_planted_copy(tmp_path):
    """Prove the previous test's invocation shape actually runs the pass:
    copy a real feature dir under the same path shape, plant an undeclared
    BGMODE store, and require the finding. A guard that can only go green is
    the toothless-gate failure mode (AGENTS.md: prove the gate fails on a
    real violation before believing it)."""
    out = tmp_path / "mz"
    subprocess.run(
        [sys.executable, str(SUPERFORGE / "allocator" / "allocate.py"),
         "--game", str(SUPERFORGE / "game" / "microzero"),
         "--features-dir", str(SUPERFORGE / "engine" / "features"),
         "--out", str(out)],
        capture_output=True, text=True, check=True)
    plant = tmp_path / "engine" / "features" / "mode7_stream"
    plant.mkdir(parents=True)
    src = SUPERFORGE / "engine" / "features" / "mode7_stream"
    shutil.copy(src / "feature.toml", plant / "feature.toml")
    body = (src / "mode7_stream.asm").read_text()
    (plant / "mode7_stream.asm").write_text(
        body + "\nrg_plant:\n    sep #$20\n    .a8\n"
               "    lda #1\n    sta a:$2105\n    rts\n")
    r = subprocess.run(
        [sys.executable, str(TOOL), "--map", str(out / "symbol_map.json"),
         str(plant / "mode7_stream.asm")],
        capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "[reg]" in r.stderr and "$2105" in r.stderr, r.stderr


# --------------------------------------------------------------------------
# item 5 — scene-enter register attribution (docs/09 §2.1 hole 2)
#
# The weak tiers used to accept any port their closure DECLARED. `scene_writes`
# is playtesting's consent, and these tiers now read it. Every rule below has a
# firing case and a silent sibling, and the silent sibling is what proves the
# narrowing did not simply disable the tier.
#
# Test surface: the output region is the tool's EXIT CODE and its stderr
# diagnostic, read from a real subprocess run of allocator/no_literals.py
# against a fixture tree — never an imported data structure. That is the
# distinction CLAUDE.md rule 2 draws, applied to a build-time gate.
# --------------------------------------------------------------------------

def test_scene_write_to_an_owned_but_unopened_port_fires(tmp_path):
    """M4, scene tier. glob_nmi HOLDS INIDISP and does not open it.

    Asserts the whole teaching diagnostic, not just the refusal: the port, the
    owning claim, the owning feature, and the exact line to type. A refusal
    that said "declared by nobody" about a port whose owner is three lines
    away in a toml is how a real gate gets worked around."""
    r = run_on(tmp_path, FIX / "game/gfix/scenes/s3.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "$2100" in r.stderr and "INIDISP" in r.stderr
    assert "scene 's3'" in r.stderr and "OWNS this port" in r.stderr
    assert "glob_nmi" in r.stderr and "engine:rgfx_glob" in r.stderr
    assert "Ownership is not permission" in r.stderr
    assert 'scene_writes = ["INIDISP"]' in r.stderr
    assert "scene_writes_shared" in r.stderr          # the co-write escape
    # the SILENT half of the same fixture: NMITIMEN, on the SAME claim, IS
    # opened. One finding, and it is not that one.
    assert r.stderr.count("[reg]") == 1, r.stderr
    assert "$4200" not in r.stderr, r.stderr


def test_scene_write_to_an_opened_port_stays_silent_and_is_examined(tmp_path):
    """The silent sibling for M4. s1 writes M7SEL and NMITIMEN, both opened.

    Asserts BOTH halves — clean AND a non-zero in-class count. "Clean" alone
    is what a disabled tier says about a file it stopped checking."""
    r = run_on(tmp_path, FIX / "game/gfix/scenes/s1.asm")
    assert r.returncode == 0, r.stdout + r.stderr
    assert in_class_count(r.stdout) == 2, r.stdout   # M7SEL + NMITIMEN


def test_boot_write_to_an_owned_but_unopened_port_fires(tmp_path):
    """M4, globals tier — the sm_display shape. Boot writes NMITIMEN (opened)
    beside INIDISP (owned, not opened); the diagnostic names INIDISP alone."""
    r = run_on(tmp_path, FIX / "game/gfix_owned/main.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    assert r.stderr.count("[reg]") == 1, r.stderr
    assert "$2100" in r.stderr and "INIDISP" in r.stderr
    assert "globals' union" in r.stderr and "OWNS this port" in r.stderr
    assert "$4200" not in r.stderr, r.stderr


def test_boot_write_to_an_opened_port_stays_silent(tmp_path):
    """The silent sibling: gfix/main.asm writes only the opened NMITIMEN."""
    r = run_on(tmp_path, FIX / "game/gfix/main.asm")
    assert r.returncode == 0, r.stdout + r.stderr


def test_span_port_resolves_to_its_name_and_fires(tmp_path):
    """M4 through `register_span`: $4204 is inside ALU's span and no footprint
    name sits at that port, so a base-port comparison would miss it. The claim
    is named ALU and opens nothing, so the write is refused — and the refusal
    explains the aliasing rather than reading as a typo."""
    r = run_on(tmp_path, FIX / "game/gfix_span/scenes/s4.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "$4204" in r.stderr and "ALU" in r.stderr
    assert "OWNS this port" in r.stderr and "sp_alu" in r.stderr
    assert 'scene_writes = ["ALU"]' in r.stderr, r.stderr


def test_covered_only_port_fires(tmp_path):
    """M4b. $211B M7A is in the closure ONLY because an hdma claim names it.

    Narrowing `declared` alone would have left this writable: measured on the
    real tree, that leaves M7A-M7D + COLDATA writable from race.asm and
    WH0/WH1 from room.asm with zero findings. Plant D's committed shape."""
    r = run_on(tmp_path, FIX / "game/gfix_cov/scenes/s4.asm",
               map_dict=GFIX_COV_MAP)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "$211B" in r.stderr and "M7A" in r.stderr
    assert "OWNS this port" in r.stderr
    assert "transfer claim 'cov_m7'" in r.stderr, r.stderr
    assert "engine:rgfx_cov" in r.stderr
    # THE ADVICE MUST BE TYPEABLE — the same bar the latch/data branch holds.
    # The owner here is an hdma claim, and a transfer claim cannot carry
    # `scene_writes` (`_table` refuses the key), so telling the author to add
    # it "to that claim" would be advice the build then rejects. The reachable
    # fix is a SEPARATE [[claims.reg]] with `seed = true`, which is exactly the
    # shape `vb2reg_coldata` on vb_b has and for exactly this reason.
    assert "give the owning feature a [[claims.reg]]" in r.stderr, r.stderr
    assert "`seed = true`" in r.stderr
    assert "Do NOT add `scene_writes` to the transfer claim" in r.stderr
    assert "vb2reg_coldata" in r.stderr


def test_a_reg_claim_owner_gets_the_one_line_advice_instead(tmp_path):
    """The sibling of the rule above: when the port IS held by a
    [[claims.reg]], the fix really is one line on that claim, and the refusal
    must not send the author down the seed'd-separate-claim path instead."""
    r = run_on(tmp_path, FIX / "game/gfix/scenes/s3.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    assert 'add `scene_writes = ["INIDISP"]` to that [[claims.reg]]' in r.stderr
    assert "seed = true" not in r.stderr, r.stderr


def test_advice_names_a_register_the_OWNING_CLAIM_holds(tmp_path):
    """The finding, the NAME axis. `sorted(port_names[port])[0]` is the
    alphabetically-first name COVERING the port, which is not always a name the
    owning claim HOLDS: for a claim holding COLDATA_R the gate advised
    `scene_writes = ["COLDATA"]` and `_reject_not_subset` refused exactly that
    edit — the advice's own parenthetical ("a subset of its own `registers`")
    asserting the property it violated."""
    r = run_on(tmp_path, FIX / "game/gfix_cov/scenes/s8.asm",
               map_dict=GFIX_COV_MAP)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "$2132" in r.stderr and "cov_plane" in r.stderr
    assert 'scene_writes = ["COLDATA_R"]' in r.stderr, r.stderr
    assert 'scene_writes = ["COLDATA"]' not in r.stderr, r.stderr
    # the co-write tail names the same held register, not the covering one
    assert "writes COLDATA_R itself" in r.stderr, r.stderr


def test_advice_names_the_plane_the_TRANSFER_claim_drives(tmp_path):
    """The same axis on the transfer branch. Here the advice asks for a NEW
    seed'd [[claims.reg]], so the name has to be one the transfer claim
    actually drives: `seed = true` against a plane nothing overrides is
    refused in its turn ("a seed says 'another declared claim overwrites this
    base value', and nothing here does")."""
    r = run_on(tmp_path, FIX / "game/gfix_cov/scenes/s10.asm",
               map_dict=GFIX_COV_MAP)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "cov_rplane" in r.stderr
    assert "[[claims.reg]] naming COLDATA_R" in r.stderr, r.stderr
    assert 'scene_writes = ["COLDATA_R"]' in r.stderr, r.stderr
    assert "`seed = true`" in r.stderr


def test_advice_does_not_offer_seed_against_a_dma_init(tmp_path):
    """The finding, the KIND axis — the instance the sweep for the class
    turned up. `seed` exempts an hdma overrider and does NOT exempt a
    dma_init, so the hdma branch's "add a seed'd [[claims.reg]]" is an edit
    check_reg_ownership refuses. The dma_init case gets the fix that exists.

    The refusal must also not offer `scene_writes_shared`: that key lives on a
    [[claims.reg]] the author cannot create here, so it is the same dead
    advice one sentence later."""
    r = run_on(tmp_path, FIX / "game/gfix_cov/scenes/s9.asm",
               map_dict=GFIX_COV_MAP)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "$2105" in r.stderr and "cov_init" in r.stderr
    assert "seed" in r.stderr, r.stderr            # it EXPLAINS seed...
    assert "`seed = true`" not in r.stderr, r.stderr        # ...but never asks for it
    assert "scene_writes = [" not in r.stderr, r.stderr
    assert "scene_writes_shared" not in r.stderr, r.stderr
    assert "move the write into the owning feature" in r.stderr


def test_every_owned_port_advice_is_an_edit_the_build_ACCEPTS(tmp_path):
    """The CLASS, not the three instances: take the edit each refusal prints
    and hand it to the validator that would receive it.

    Defect 2 of this change was "advice the gate prints that the build then
    rejects", swept on the holder-type axis only; a later review found two more axes.
    A string assertion per axis pins the axes known today, so this pins the
    PROPERTY instead — every `scene_writes = ["X"]` the gate advises is loaded
    through `schemas.load_feature` against the real owning claim, and must
    parse. The negative control below it proves the check can fail."""
    import schemas
    cases = [                       # (fixture, map, owning claim's registers)
        (FIX / "game/gfix/scenes/s3.asm", GFIX_MAP, ["INIDISP", "NMITIMEN"]),
        (FIX / "game/gfix_span/scenes/s4.asm", GFIX_MAP, ["ALU"]),
        (FIX / "game/gfix_cov/scenes/s8.asm", GFIX_COV_MAP, ["COLDATA_R"]),
        (FIX / "game/gfix_cov/scenes/s10.asm", GFIX_COV_MAP, ["COLDATA_R"]),
        (FIX / "game/gfix_cov/scenes/s9.asm", GFIX_COV_MAP, ["BGMODE"]),
    ]
    sub = schemas.load_substrate(SUPERFORGE / "allocator" / "substrate.toml")
    seen = 0
    for i, (asm, mp, registers) in enumerate(cases):
        r = run_on(tmp_path, asm, map_dict=mp)
        assert r.returncode == 1, r.stdout + r.stderr
        for name in re.findall(r'scene_writes = \["([A-Z0-9_]+)"\]', r.stderr):
            seen += 1
            d = tmp_path / f"adv{i}_{name.lower()}"
            d.mkdir()
            (d / "feature.toml").write_text(
                f'name = "{d.name}"\nrole = "fixture"\n\n[[claims.reg]]\n'
                f'name = "owner"\nregisters = {registers!r}\n'
                f'scene_writes = ["{name}"]\n'.replace("'", '"'))
            schemas.load_feature(d / "feature.toml", sub)   # must not raise
    assert seen >= 4, f"only {seen} advised edits found — did the text move?"
    # negative control: the name the OLD code would have printed for s8/s10 is
    # rejected by the same loader, so the assertion above is not vacuous.
    d = tmp_path / "adv_control"
    d.mkdir()
    (d / "feature.toml").write_text(
        'name = "adv_control"\nrole = "fixture"\n\n[[claims.reg]]\n'
        'name = "owner"\nregisters = ["COLDATA_R"]\n'
        'scene_writes = ["COLDATA"]\n')
    with pytest.raises(schemas.SchemaError, match="scene_writes names"):
        schemas.load_feature(d / "feature.toml", sub)


def test_a_seeded_reg_claim_against_a_dma_init_is_really_refused():
    """The premise the dma_init advice rests on, asserted against the
    validator rather than quoted from its source. If `seed` ever DID exempt a
    dma_init, the branch above would be withholding a fix that works."""
    sys.path.insert(0, str(SUPERFORGE / "allocator"))
    import allocate as AL
    import schemas
    reg = schemas.RegClaim(name="cpu_seed", registers=("BGMODE",), seed=True)
    di = schemas.DmaInitClaim(name="cov_init", channel=1,
                              registers=("BGMODE",))
    hd = schemas.HdmaClaim(name="cov_h", channels=1, registers=("BGMODE",),
                           band=(0, 224), phase="active")
    with pytest.raises(AL.AllocationError, match="does not exempt it"):
        AL.check_reg_ownership([(reg, "engine:a")], [],
                               [(di, "s", "engine:b")], "s")
    # ...and the hdma sibling IS exempted, which is why that branch keeps the
    # seed advice. One call each: the two arms of the same rule.
    AL.check_reg_ownership([(reg, "engine:a")], [(hd, "engine:b")], [], "s")


def test_covered_and_opened_port_stays_silent(tmp_path):
    """The silent sibling for M4b — race's BGMODE shape, covered AND opened.

    It proves M4b did not disable the arm. It does NOT pin which reading of
    the covered rule was built: being `declared` as well, it exits 0 under
    both. test_covered_reg_claimed_but_not_opened_fires is the discriminator."""
    r = run_on(tmp_path, FIX / "game/gfix_cov/scenes/s5.asm",
               map_dict=GFIX_COV_MAP)
    assert r.returncode == 0, r.stdout + r.stderr


def test_region_data_and_latch_ports_are_not_narrowed(tmp_path):
    """The latch/data half stays whole: CGDATA and its CGADD latch ride the
    cgram PLACEMENT, because a latch rides the claim on the RESOURCE its data
    port serves — hardware structure, not permission. Narrowing it would refuse
    every upload path.

    HONEST ABOUT WHICH MECHANISM: this rides `_scene_union`'s
    placement coverage and `satisfies_resource`, NOT `_transfer_covered`. Its
    two writes categorise `0 in-class`, and the M4b narrowing lives entirely
    on the in-class branch, so the docstring this replaces — "M4b's boundary" —
    named a mechanism the fixture never reaches. Worse, the placement sets
    `covered` and `res` in the same loop, so neither can be neutered alone and
    the fixture stayed green under both. s12 below is the firing sibling that
    gives this silence a cause; s11 isolates the other route.

    Both halves are asserted, so a tier that stopped EXAMINING data ports
    could not pass this by going quiet."""
    r = run_on(tmp_path, FIX / "game/gfix_cov/scenes/s6.asm",
               map_dict=GFIX_COV_MAP)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 data" in r.stdout and "1 latch" in r.stdout, r.stdout


def test_a_transfer_claims_NAME_covers_the_data_port_it_names(tmp_path):
    """The finding, the route that actually decides. s11 holds no placement:
    the only thing naming CGDATA is an hdma claim, and the write is silent
    because both union tiers union a transfer claim's registers into `names`,
    which is what `satisfies_resource` reads.

    This is the territory `_transfer_covered`'s deleted non-in-class arm
    duplicated — it put these ports into `covered` one rule earlier, changing
    no verdict anywhere. The arm was unfalsifiable; this is not."""
    r = run_on(tmp_path, FIX / "game/gfix_cov/scenes/s11.asm",
               map_dict=GFIX_COV_MAP)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 data" in r.stdout and "1 latch" in r.stdout, r.stdout


def test_an_unclaimed_data_port_and_its_latch_both_fire(tmp_path):
    """THE FIRING SIBLING for s6 and s11. Identical writes, and
    a closure that claims nothing. Without it, "data ports are not narrowed" is
    asserted only by files that exit 0 — which is also what a tier that had
    stopped checking them would produce."""
    r = run_on(tmp_path, FIX / "game/gfix_cov/scenes/s12.asm",
               map_dict=GFIX_COV_MAP)
    assert r.returncode == 1, r.stdout + r.stderr
    assert r.stderr.count("[reg]") == 2, r.stderr        # the data port AND its latch
    assert "$2122" in r.stderr and "$2121" in r.stderr
    assert "claim the `cgram` region" in r.stderr, r.stderr


def test_the_resource_route_owns_every_data_port_a_claim_can_name():
    """The property that makes `_transfer_covered`'s deleted non-in-class arm
    redundant, pinned so the deletion cannot rot.

    Exhaustively over REGISTER_FOOTPRINT: every non-in-class port any claimable
    name reaches is a DATA port, and is its own resource's RESOURCE_PORT_NAMES
    entry. So a transfer claim naming it puts that exact name into `names`, and
    `satisfies_resource` covers the port — and its latches — without the arm.

    Add a footprint name for a latch, a channel port, or an unnamed port and
    this goes red: that is the day the redundancy argument has to be re-derived
    rather than the day the coverage silently disappears."""
    for name in schemas.REGISTER_FOOTPRINT:
        for lo, hi in schemas.register_span(name):
            for p in range(lo, hi + 1):
                kind, info = NL._reg_category(p)
                if kind == "in-class":
                    continue
                assert kind == "data", (name, hex(p), kind)
                resource, port_name = info
                assert port_name in NL.RESOURCE_PORT_NAMES[resource], \
                    (name, hex(p), resource, port_name)


def test_covered_reg_claimed_but_not_opened_fires(tmp_path):
    """THE DISCRIMINATING SIBLING.

    rgfx_cov covers TM with a transfer claim AND opens TM on a [[claims.reg]],
    but does not list it in that claim's `scene_writes`. This is the ONE shape
    on which the two readings of the covered rule diverge:

        WEAK   "the same feature opens that register on a [[claims.reg]]"
               -> accept
        STRONG "...and lists it in that claim's scene_writes"
               -> refuse

    The STRONG reading was built, so this expects exit 1. It exists because
    s5 — the fixture the spec originally specified for this job — is
    `declared` AND `covered` and therefore exits 0 under both readings: it
    cannot fail, and a gate whose fixture cannot fail is the anti-pattern.

    If someone later switches the rule to the weak reading, this test is the
    thing that says so."""
    r = run_on(tmp_path, FIX / "game/gfix_cov/scenes/s7.asm",
               map_dict=GFIX_COV_MAP)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "$212C" in r.stderr and "TM" in r.stderr
    assert "OWNS this port" in r.stderr
    # BOTH owners are named: the reg claim that holds it without opening it,
    # and the transfer claim that covers it. The author needs to know both.
    assert "cov_hold" in r.stderr and "cov_tm" in r.stderr, r.stderr
    assert 'scene_writes = ["TM"]' in r.stderr


# --------------------------------------------------------------------------
# item 5 / M5 — the declaration-that-lies check
#
# `scene_writes` is a permission, and like `seed` it is a declaration that can
# LIE. Two rules, both zero-baseline on the shipped tree, both falsifiable:
#   1. a scene_writes register playtesting ALSO writes, not declared shared
#   2. a scene_writes_shared register playtesting does NOT write
#
# Runs at the feature-strict tier over path.parent.glob("*.asm"), which is the
# same derive-from-the-scanned-path move _feature_reg_context and
# _feature_port_owners already make. It does NOT fail on an owner with no
# `.asm` — measured, that is the normal case (5 of 11 owners), and the
# fail-loud rule the documents asked for would refuse 4 of 5 live invocations.
# Arming is disclosed by the summary-line count and PROVEN by the planted
# co-write in the in-tree guard below.
# --------------------------------------------------------------------------

def test_scene_writes_the_owner_also_writes_fires(tmp_path):
    """Rule 1. Identical ASM to the silent sibling next door; the only
    difference is one line of TOML, so the declaration is isolated as the
    thing under test.

    The write itself is NOT a finding — the feature-strict tier is not
    narrowed and BGMODE is on the claim — so exactly one finding is expected,
    and it is the declaration's."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_lies/rgfx_lies.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    assert r.stderr.count("[reg]") == 1, r.stderr
    assert "declaration that lies" in r.stderr
    assert "rl_mode" in r.stderr and "rgfx_lies" in r.stderr
    assert "MOSAIC" in r.stderr
    assert "rgfx_lies.asm:" in r.stderr          # names the co-write's SITE
    assert 'scene_writes_shared = ["MOSAIC"]' in r.stderr


def test_scene_writes_shared_declares_the_co_write_and_is_silent(tmp_path):
    """The escape works. This is sm_display's real shape, and it is what
    proves the rule was not simply disabled — a rule whose only silent case is
    "the rule did not run" teaches nothing."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_lies_shared/rgfx_lies_shared.asm")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 claim(s) validated" in r.stdout, r.stdout


def test_scene_writes_shared_with_no_co_write_fires(tmp_path):
    """Rule 2 — the same lie in the other direction. It silently widens the
    gate, because the co-write it excuses does not exist."""
    r = run_on(tmp_path, FIX / "engine/features/rgfx_lies_shared_bad"
                               "/rgfx_lies_shared_bad.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    assert r.stderr.count("[reg]") == 1, r.stderr
    assert "declaration that lies" in r.stderr
    assert "scene_writes_shared" in r.stderr and "M7SEL" in r.stderr
    assert "no `.asm`" in r.stderr


def test_rule_1_sees_a_co_write_to_a_DATA_register(tmp_path):
    """The finding, half one. `_owner_write_ports` used to keep IN-CLASS ports
    only, so `written` could never hold $2122 and rule 1 could not see this
    co-write at all — the gate was blind to a lie it exists to refuse, for a
    whole register class (OAMDATA, VMDATAL/H, CGDATA are all namable on a
    claim), while the summary line counted the claim as `validated`.

    Identical shape to rgfx_lies one register class over, so the only variable
    is the category filter."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_lies_data/rgfx_lies_data.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    assert r.stderr.count("[reg]") == 1, r.stderr
    assert "declaration that lies" in r.stderr
    assert "rl_cgd" in r.stderr and "CGDATA" in r.stderr
    assert "rgfx_lies_data.asm:" in r.stderr          # names the co-write SITE
    assert 'scene_writes_shared = ["CGDATA"]' in r.stderr


def test_rule_2_does_not_false_positive_on_a_DATA_register(tmp_path):
    """The finding, half two, and the one that BROKE THE BUILD: with the
    in-class filter, rule 2 asked "does any `.asm` here write CGDATA?" of a set
    that structurally could not contain a data port, answered no, and refused a
    TRUE declaration — with a diagnostic asserting something the file six lines
    away contradicted, advising the author to delete the declaration.

    The exit code is the load-bearing assertion; the count is asserted too
    because it is the sharper half of the finding — the arming disclosure
    reported this claim as `validated` while the examination could not see its
    register class."""
    r = run_on(tmp_path, FIX / "engine/features/rgfx_lies_data_shared"
                               "/rgfx_lies_data_shared.asm")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "no `.asm`" not in r.stderr, r.stderr
    assert "1 claim(s) validated" in r.stdout, r.stdout
    # ...and it was really EXAMINED: the site is in the census as a data write.
    assert "1 data" in r.stdout, r.stdout


def test_the_lies_check_scope_is_a_feature_toml_not_a_path_shape(tmp_path):
    """The check used to gate on the hardcoded path shape
    `parts[-4:-2] == ("engine", "features")`, so a feature directory anywhere
    else was silently skipped — `engine/toy/feat_a/` is a real one, carrying
    two `scene_writes` declarations, and the skip showed up only as a smaller
    number in the summary's count.

    The scope is now the thing the docstring always claimed: the scanned file's
    own directory holds a `feature.toml`. Both rules are asserted, so the test
    proves the whole check reaches this path rather than just its entry."""
    r = run_on(tmp_path, FIX / "toy/rgfx_lies_offpath/rgfx_lies_offpath.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    assert r.stderr.count("[reg]") == 2, r.stderr
    assert r.stderr.count("declaration that lies") == 2, r.stderr
    assert "MOSAIC" in r.stderr and "M7SEL" in r.stderr
    assert "no `.asm`" in r.stderr                      # rule 2 reached it too
    # ...and the `; REG-LINT: ok` on the MOSAIC write excused the OWNERSHIP
    # verdict without excusing the declaration one. Two different questions.
    assert "OWNS this port" not in r.stderr, r.stderr


def test_intree_guard_is_armed_against_a_planted_absent_co_write(tmp_path):
    """item 5, M5 rule 2 — the in-tree plant plant J did not have. Rule 1's plant (below) proves the shipped-tree invocation enforces
    the "owner also writes it" direction; nothing proved the other direction
    outside the fixture tree, and the two rules have different inputs — rule 1
    reads the intersection of the opened set with `written`, rule 2 reads its
    complement.

    room_bg's `room_layers` is the shape that makes this plantable: it opens
    BGMODE/TM, which room_bg.asm does NOT write (the disjoint shape). Declaring
    either as `scene_writes_shared` claims a co-write that is not there."""
    out = tmp_path / "rm"
    subprocess.run(
        [sys.executable, str(SUPERFORGE / "allocator" / "allocate.py"),
         "--game", str(SUPERFORGE / "game" / "room"),
         "--features-dir", str(SUPERFORGE / "engine" / "features"),
         "--out", str(out)], capture_output=True, text=True, check=True)
    plant = tmp_path / "engine" / "features" / "room_bg"
    plant.mkdir(parents=True)
    src = SUPERFORGE / "engine" / "features" / "room_bg"
    toml = (src / "feature.toml").read_text()
    anchor = 'scene_writes = ["BGMODE", "TM"]'
    assert anchor in toml, "room_layers' opened set moved"              # guard
    assert "scene_writes_shared" not in toml, "room_bg grew a co-write"  # guard
    (plant / "feature.toml").write_text(
        toml.replace(anchor, anchor + '\nscene_writes_shared = ["BGMODE"]', 1))
    shutil.copy(src / "room_bg.asm", plant / "room_bg.asm")
    # --partial-files: one planted file against a whole game's map — see the
    # sibling plant test above for why the whole-composition rom-backing check
    # has to be told this list is a subset (docs/37 §3).
    r = subprocess.run(
        [sys.executable, str(TOOL), "--map", str(out / "symbol_map.json"),
         "--partial-files", str(plant / "room_bg.asm")],
        capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "declaration that lies" in r.stderr, r.stderr
    assert "room_layers" in r.stderr and "BGMODE" in r.stderr
    assert "no `.asm`" in r.stderr                      # rule 2's wording
    # ...and the UNPLANTED original is silent in the same invocation shape.
    r2 = subprocess.run(
        [sys.executable, str(TOOL), "--map", str(out / "symbol_map.json"),
         "--partial-files", str(src / "room_bg.asm")],
        capture_output=True, text=True)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert "1 claim(s) validated" in r2.stdout, r2.stdout


def test_not_opening_the_register_at_all_is_silent(tmp_path):
    """The other fix for rule 1: do not open the register. A claim with no
    `scene_writes` entry for a register has always meant "mine alone", so the
    owner writing it is the default, not a lie."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_lies_ok/rgfx_lies_ok.asm")
    assert r.returncode == 0, r.stdout + r.stderr


def test_disjoint_opened_and_written_sets_are_silent(tmp_path):
    """room_bg's room_layers shape, and the REGRESSION GUARD against
    re-introducing claim-granular comparison.

    Nine registers, two opened, and the seven the owner writes are the OTHER
    seven. A whole-claim comparison calls that a lie; measured on the real
    tree, claim-granular baseline is 2 and register-granular is 1, and the
    spurious one is exactly this shape."""
    r = run_on(tmp_path, FIX / "engine/features/rgfx_lies_disjoint"
                               "/rgfx_lies_disjoint.asm")
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_summary_line_discloses_how_many_claims_were_validated(tmp_path):
    """The fail-loud requirement, discharged as a COUNT rather than as a
    refusal on absent ASM (which is measurably wrong: 5 of the 11 real claim
    owners have no `.asm` and 4 of the 5 live invocations pass one file).

    A zero must read as DISARMED rather than as clean, so the count prints
    unconditionally — including when it is zero."""
    r = run_on(tmp_path, FIX / "engine/features/rgfx_covered/rgfx_covered.asm")
    assert r.returncode == 0, r.stdout + r.stderr
    # rgfx_covered's claim carries no scene_writes, so nothing was validated —
    # and the line SAYS so rather than omitting the clause.
    assert "scene_writes: 0 claim(s) validated" in r.stdout, r.stdout


def test_intree_guard_is_armed_against_an_owned_but_unopened_scene_write(tmp_path):
    """item 5, M4/M4b: prove the SHIPPED-TREE invocation actually enforces the
    narrowed rule, not just that it goes green.

    test_shipped_tree_is_clean above says the tree has no findings. That is
    exactly what a disabled rule would also say, which is the toothless-gate
    failure mode tests/test_make_gates.py exists to warn about. So: copy a
    real scene file under the same path shape, plant a write to a port the
    scene's closure OWNS but nobody opened, and require the finding — with the
    REAL map, in the invocation shape the Makefile uses.

    $2130 CGWSEL is owned by rgb_gradient's `grad_math` claim, which does not
    open it. Before item 5 this exact plant was ACCEPTED, exit 0."""
    out = tmp_path / "mz"
    subprocess.run(
        [sys.executable, str(SUPERFORGE / "allocator" / "allocate.py"),
         "--game", str(SUPERFORGE / "game" / "microzero"),
         "--features-dir", str(SUPERFORGE / "engine" / "features"),
         "--out", str(out)], capture_output=True, text=True, check=True)
    d = tmp_path / "game" / "microzero" / "scenes"     # path shape matters:
    d.mkdir(parents=True)                              # reg_context reads it
    src = (SUPERFORGE / "game" / "microzero" / "scenes" / "race.asm").read_text()
    assert "rg_plant" not in src                       # the guard
    (d / "race.asm").write_text(
        src + "\nrg_plant:\n    sep #$20\n    .a8\n"
              "    lda #1\n    sta a:$2130\n    rts\n")
    # --partial-files: this invocation deliberately hands ONE planted file
    # a whole game's map, so the whole-composition rom-backing check has no
    # claim sites to find and would report all 24 claims unbacked. Saying
    # so is the flag's whole purpose; the summary line then reads SKIPPED
    # rather than clean (docs/37 §3).
    r = subprocess.run(
        [sys.executable, str(TOOL), "--map", str(out / "symbol_map.json"),
         "--partial-files", str(d / "race.asm")], capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "$2130" in r.stderr and "CGWSEL" in r.stderr
    assert "OWNS this port" in r.stderr and "grad_math" in r.stderr


def test_intree_guard_is_armed_against_a_planted_co_write(tmp_path):
    """item 5, M5: the same proof for the lies-check, and the reason the
    fail-loud requirement could be discharged as a COUNT.

    The check is silent for an owner with no `.asm`, which is correct but
    indistinguishable from "the feature files were not in this invocation".
    The summary-line count makes a zero READ as disarmed; only a plant proves
    a non-zero count is doing work. Copy a real feature dir, drop the one
    `scene_writes_shared` entry in the tree, require the finding.

    scene_mgr is the tree's one irreducible co-write: boot's $4200 write
    answers to the globals' union, scene_mgr is the only globals feature
    declaring NMITIMEN, so NMITIMEN must be opened — and scene_mgr must write
    it, masking NMI around the blank switch and restoring it after.

    THE SITE ASSERTION IS DERIVED, NOT PINNED. It read `scene_mgr.asm:149`
    until 2026-08-15, when the cut transition added lines above the
    mask and turned an unrelated engine edit into a red here — the gate was
    working, its output was right, and only this constant was wrong. A line
    number typed into a test is a copy of the source's layout that nothing
    keeps in step; what the test actually means is "the finding names the
    feature's own first NMITIMEN write", so it now finds that line the way
    the gate does."""
    out = tmp_path / "mz"
    subprocess.run(
        [sys.executable, str(SUPERFORGE / "allocator" / "allocate.py"),
         "--game", str(SUPERFORGE / "game" / "microzero"),
         "--features-dir", str(SUPERFORGE / "engine" / "features"),
         "--out", str(out)], capture_output=True, text=True, check=True)
    plant = tmp_path / "engine" / "features" / "scene_mgr"
    plant.mkdir(parents=True)
    src = SUPERFORGE / "engine" / "features" / "scene_mgr"
    toml = (src / "feature.toml").read_text()
    anchor = 'scene_writes_shared = ["NMITIMEN"]'
    assert anchor in toml, "the tree's one co-write declaration moved"   # guard
    (plant / "feature.toml").write_text(toml.replace(anchor, "", 1))
    shutil.copy(src / "scene_mgr.asm", plant / "scene_mgr.asm")
    # --partial-files: this invocation deliberately hands ONE planted file
    # a whole game's map, so the whole-composition rom-backing check has no
    # claim sites to find and would report all 24 claims unbacked. Saying
    # so is the flag's whole purpose; the summary line then reads SKIPPED
    # rather than clean (docs/37 §3).
    r = subprocess.run(
        [sys.executable, str(TOOL), "--map", str(out / "symbol_map.json"),
         "--partial-files", str(plant / "scene_mgr.asm")],
        capture_output=True, text=True)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "declaration that lies" in r.stderr, r.stderr
    assert "sm_display" in r.stderr and "NMITIMEN" in r.stderr
    # ...and it names the co-write SITE: the feature's own first write to
    # NMITIMEN, located in the source rather than remembered from it.
    asm = (src / "scene_mgr.asm").read_text().splitlines()
    site = next(n for n, line in enumerate(asm, 1)
                if "a:$4200" in line
                and line.split(";")[0].split()[0] in ("stz", "sta"))
    assert f"scene_mgr.asm:{site}" in r.stderr, (site, r.stderr)
    # ...and the UNPLANTED original is silent in the same invocation shape,
    # so the finding is attributable to the removed declaration and nothing
    # else. This pairing is what a bare "it fired" cannot establish.
    r2 = subprocess.run(
        [sys.executable, str(TOOL), "--map", str(out / "symbol_map.json"),
         "--partial-files", str(src / "scene_mgr.asm")],
        capture_output=True, text=True)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert "1 claim(s) validated" in r2.stdout, r2.stdout


# --------------------------------------------------------------------------
# bundled LOW
# --------------------------------------------------------------------------

def test_a_malformed_reg_override_says_so(tmp_path):
    """A `; REG-LINT:` comment that misses the strict grammar used to be
    INVISIBLE: the finding fired and said nothing about the escape hatch the
    author had typed three lines away.

    Note the framing, which the original finding got backwards: this fails
    SAFE. The underlying finding fires either way (measured on all three
    spellings, the spec), so the cost is a lost DIAGNOSTIC, not a silence.
    That is why the note is appended to the refusal rather than filed as its
    own finding — a malformed override is a failed attempt to excuse a
    violation, not a second violation. Both halves are asserted here, because
    asserting only the exit code would pass without the fix."""
    r = run_on(tmp_path, FIX / "engine/features/rgfx_ov_malformed"
                               "/rgfx_ov_malformed.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    assert r.stderr.count("[reg]") == 2, r.stderr      # NOT 3: no extra finding
    assert r.stderr.count("does not parse as an override") == 2, r.stderr
    assert "$2106" in r.stderr and "$2101" in r.stderr
    # the note points at the COMMENT's line, not the write's
    assert "comment at line 15" in r.stderr, r.stderr
    assert "comment at line 21" in r.stderr, r.stderr


def test_a_wellformed_reg_override_is_not_called_malformed(tmp_path):
    """The silent sibling: a reasoned override that PARSES must not pick up
    the new note. rgfx_override is the shipped well-formed case."""
    r = run_on(tmp_path,
               FIX / "engine/features/rgfx_override/rgfx_override.asm")
    assert "does not parse as an override" not in r.stderr, r.stderr


def test_a_bare_reg_override_keeps_its_own_finding(tmp_path):
    """The other silent sibling: the BARE form already has a finding of its
    own ("state WHY"), and must not also be reported as malformed — one
    mistake, one diagnostic."""
    r = run_on(tmp_path, FIX / "engine/features/rgfx_bare_override"
                               "/rgfx_bare_override.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "bare `; REG-LINT: ok`" in r.stderr
    assert "does not parse as an override" not in r.stderr, r.stderr


def test_window_desc_plural_branch_counts_unfoldable_operands(tmp_path):
    """The second half: `_window_desc`'s PLURAL branch had no test — the only
    assertion on it was the singular literal, which was itself copied by hand
    out of `_site_label`.

    Three writes whose ports will not fold share one standalone override's
    ±3-line window. None is nameable by rule 1 (an unfoldable write has no
    port to name), so rule 3 refuses, and the window must be described as a
    COUNT rather than by repeating the same sentence three times."""
    r = run_on(tmp_path, FIX / "engine/features/rgfx_ov_unfold_triple"
                               "/rgfx_ov_unfold_triple.asm")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "3 operands whose port cannot be folded" in r.stderr, r.stderr
    # the singular sentence must NOT appear — that is the branch this is not
    assert "an operand whose port cannot be folded" not in r.stderr, r.stderr


def test_site_label_has_exactly_one_caller_and_owns_the_sentence():
    """The first half. `_site_label` had NO caller and its literal lived
    twice; `_window_desc`'s singular branch now routes through it, so the
    sentence has one home. Asserted rather than left to review, because "two
    copies of one string" is precisely the thing that silently drifts."""
    src = (SUPERFORGE / "allocator" / "no_literals.py").read_text()
    sentence = "an operand whose port cannot be folded"
    # once in _site_label's return, and nowhere else as a bare literal
    assert src.count(f'"{sentence}"') == 1, (
        f"the singular label literal appears "
        f"{src.count(chr(34) + sentence + chr(34))} times — route the second "
        f"through _site_label")
    assert "_site_label(None)" in src, "_window_desc must call it"
