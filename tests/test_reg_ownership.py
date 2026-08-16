"""C4 — CPU-written register ownership (docs/09 §2.1), the tenth claim class.

The headline is the REFUSAL: window_iris and rgb_gradient want CGWSEL/CGADSUB
for incompatible purposes, and composing them in one scene must stop the build.
Everything else here exists to keep that refusal honest — that it fires for the
stated reason, that it does not fire on the compositions we ship, and that the
vocabulary teaches itself when misused.

On test surface: these are allocator tests, so the output region IS the
allocator's verdict + diagnostic text, not a proxy for it. The ROM-level half
of this change's contract lives in test_room_window.py (the lantern still
renders) and in the unchanged md5s asserted by test_make_gates.py.
"""
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "allocator"))

from allocate import AllocationError, allocate  # noqa: E402
from schemas import (B_BUS_REGISTERS, REGISTER_FOOTPRINT, SchemaError,  # noqa: E402
                     StateDecl, load_feature, load_manifest, load_substrate)

SUB = load_substrate(SUPERFORGE / "allocator" / "substrate.toml")
FEATURES = SUPERFORGE / "engine" / "features"
NO_STATE = StateDecl((), {})


def feature(tmp_path, name, body="", role="fixture"):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "feature.toml").write_text(f'name = "{name}"\nrole = "{role}"\n{body}')
    return load_feature(d / "feature.toml", SUB)


def manifest(tmp_path, features):
    p = tmp_path / "game.toml"
    names = ", ".join(f'"{n}"' for n in features)
    p.write_text(f'[[scene]]\nid = "s"\nfeatures = [{names}]\n')
    return load_manifest(p)


def _all_shipping():
    return {f.name: f for f in
            (load_feature(fp, SUB) for fp in sorted(FEATURES.glob("*/feature.toml")))}


def compose(tmp_path, feats):
    """allocate() over these FeatureDecls in one scene, no globals.

    The registry carries every shipping feature so `depends` resolves (
    race_logic depends on mode7_persp/mode7_stream), but the SCENE names only
    what was passed — and anything passed shadows the shipping copy by name,
    which is how the stripped-claim variants below work.
    """
    reg = _all_shipping() | {f.name: f for f in feats}
    return allocate(SUB, reg, NO_STATE,
                    manifest(tmp_path, [f.name for f in feats]))


def real(*names):
    """Load the SHIPPING feature declarations, not a paraphrase of them.

    The refusal has to be provoked by what the tree actually declares. A
    hand-written imitation of window_iris would test the imitation.
    """
    return [load_feature(FEATURES / n / "feature.toml", SUB) for n in names]


# -- the headline: the first real two-claimants-one-register case -----------

def test_window_iris_and_rgb_gradient_in_one_scene_refuse(tmp_path):
    """THE acceptance test for this change.

    Both features are shipping code in different games. window_iris writes
    CGWSEL = $20 ("math outside the window, subtract"); rgb_gradient writes
    CGWSEL = $00 ("math always, add the fixed colour"). Nothing refused before
    this class existed — verified by test_the_pair_composed_cleanly_before_c4
    below, which reconstructs the pre-C4 state rather than asserting it from
    memory.
    """
    with pytest.raises(AllocationError) as e:
        compose(tmp_path, real("window_iris", "rgb_gradient", "room_rom"))
    msg = str(e.value)
    # names BOTH features and the register — the brief's explicit bar
    assert "window_iris" in msg and "rgb_gradient" in msg
    assert "CGWSEL" in msg
    assert "one owner per scene" in msg


def test_the_pair_composed_cleanly_before_c4(tmp_path):
    """The refusal is NEW, not a pre-existing collision being relabelled.

    Strip the reg claims off both features and the composition allocates —
    which is what the tree did before this change, because their declared
    claims were WH0/WH1 versus COLDATA_R/G/B: different ports, so
    _register_conflicts saw nothing. Without this test "it refuses" could be
    true for a reason that predates the class.
    """
    iris, grad, rom = real("window_iris", "rgb_gradient", "room_rom")
    pre = [f.__class__(**{**f.__dict__, "reg": ()}) for f in (iris, grad, rom)]
    alloc = compose(tmp_path, pre)          # must NOT raise
    assert alloc.scenes["s"].regs == []


def test_refusal_survives_on_coldata_alone(tmp_path):
    """A SECOND independent ground, so the refusal is not one check deep.

    window_iris CPU-writes COLDATA as a persistent subtract constant while
    claiming only WH0/WH1; rgb_gradient drives the COLDATA planes per
    scanline. Drop the CGWSEL/CGADSUB overlap and the reg-x-transfer check
    still refuses — a per-line transfer destroys a value the CPU write needs
    to hold, which no phase model can see.
    """
    iris, grad, rom = real("window_iris", "rgb_gradient", "room_rom")
    trimmed = tuple(c.__class__(name=c.name, registers=("COLDATA",), seed=c.seed)
                    for c in iris.reg)
    iris = iris.__class__(**{**iris.__dict__, "reg": trimmed})
    with pytest.raises(AllocationError) as e:
        compose(tmp_path, [iris, grad, rom])
    msg = str(e.value)
    assert "COLDATA" in msg and "$2132" in msg      # the mask intersection
    assert "claims.hdma" in msg


# -- it must not refuse what we ship ---------------------------------------

@pytest.mark.parametrize("game", ["microzero", "room"])
def test_shipping_games_still_allocate(game, repo_tree_read_lock):
    """A class that refuses microzero or room is worse than no class.

    Runs the real CLI over the real game, so this covers the scene-enter
    attribution (backdrop/bg_text/mode7_floor/split_band) as well as the eight
    original census rows.

    UNDER THE SHARED TREE LOCK, and conftest's own comment predicted exactly
    this test: "if a future test asserts on the CONTENT of a live-tree
    allocation rather than on a refusal, it needs LOCK_SH too." It reads the
    LIVE engine/features/ while test_register.py plants and removes
    `zz_fixture` there under the EXCLUSIVE lock, so at -n 4 the allocator can
    walk a directory that vanishes underneath it:
    `FileNotFoundError: engine/features/zz_fixture/feature.toml`, reported
    against this test, which did nothing wrong. Observed on a bare-check run
    2026-08-06.
    """
    with repo_tree_read_lock():
        out = subprocess.run(
            [sys.executable, str(SUPERFORGE / "allocator" / "allocate.py"),
             "--game", str(SUPERFORGE / "game" / game),
             "--features-dir", str(FEATURES),
             "--out", str(SUPERFORGE / "build" / f"regtest_{game}")],
            capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "allocation OK" in out.stdout


def test_race_scene_ownership_is_reported():
    """The report is C4's deliverable: the class emits no symbol, so ownership
    is only visible if it is written down. Reads the generated report."""
    rep = (SUPERFORGE / "build" / "regtest_microzero" / "allocation_report.txt")
    text = rep.read_text()
    race = text.split("scene 'race'")[1]
    assert "REGISTERS" in race
    for owner in ("sky_band", "rgb_gradient", "mode7_persp", "player_car",
                  "race_logic", "scene_mgr"):
        assert owner in race, f"{owner} ownership missing from the report"
    assert "seed BGMODE,TM" in race          # split_band's seed, marked as one


# -- the seed field --------------------------------------------------------

def test_seed_composes_with_the_hdma_that_overrides_it(tmp_path):
    """race.asm's "HDMA overrides per line" made checkable.

    Without `seed`, split_band's own enter-time BGMODE/TM writes would refuse
    against split_band's own HDMA claims and take the race scene with them.
    """
    a = feature(tmp_path, "seeder", '[[claims.reg]]\nregisters = ["BGMODE"]\n'
                                    'seed = true\n')
    b = feature(tmp_path, "driver",
                '[[claims.hdma]]\nregisters = ["BGMODE"]\nband = "scene"\n'
                'phase = "active"\nchannels = 1\n')
    compose(tmp_path, [a, b])               # must NOT raise


def test_seed_with_nothing_overriding_it_is_rejected(tmp_path):
    """A seed says "another declared claim overwrites this base value". If
    none does, the declaration is a lie and the build says so — otherwise
    `seed` would be a way to opt out of the class."""
    a = feature(tmp_path, "liar", '[[claims.reg]]\nregisters = ["BGMODE"]\n'
                                  'seed = true\n')
    with pytest.raises(AllocationError, match="declares `seed = true` but no"):
        compose(tmp_path, [a])


def test_seed_does_not_exempt_a_dma_init(tmp_path):
    """dma_init is a one-shot enter-time ESTABLISHER, not an ongoing
    overrider, so two of them still fight over one port."""
    a = feature(tmp_path, "sd", '[[claims.reg]]\nregisters = ["CGWSEL"]\n'
                                'seed = true\n')
    b = feature(tmp_path, "di", '[[claims.dma_init]]\nchannel = 0\n'
                                'registers = ["CGWSEL"]\n')
    with pytest.raises(AllocationError, match="one-shot enter-time"):
        compose(tmp_path, [a, b])


def test_two_owners_refuse_regardless_of_who_is_global(tmp_path):
    """Ownership is checked over the global+scene UNION (F2, the cross-scope
    silent-composition hole). scene_mgr owns INIDISP globally, so a
    scene-scoped second writer must still refuse."""
    scene_mgr, = real("scene_mgr")
    rival = feature(tmp_path, "dimmer",
                    '[[claims.reg]]\nregisters = ["INIDISP"]\n')
    man = manifest(tmp_path, ["dimmer"])
    man = man.__class__(globals_=("scene_mgr",), scenes=man.scenes,
                        edges=man.edges)
    with pytest.raises(AllocationError, match="INIDISP"):
        allocate(SUB, {"scene_mgr": scene_mgr, "dimmer": rival}, NO_STATE, man)


# -- phase-blindness: the design decision, asserted ------------------------

def test_ownership_is_phase_blind_unlike_hdma(tmp_path):
    """The load-bearing decision, and the one that must not be "unified" away.

    _register_exclusive lets vblank claims compose, because they are
    serialised NMI-queue entries — a property of the QUEUE. A CPU writer is
    PREEMPTED by the NMI, not queued. So two reg claims conflict with no
    reference to when they run. If someone reuses _register_exclusive here,
    this test is what goes red.

    The concrete stake: race_logic uses the ALU on the main thread. Under
    HDMA's rule a vblank-side ALU user would compose with it, i.e. the
    hardware-multiplier defect would pass through the class built to catch it.
    """
    rl, = real("race_logic")
    nmi_user = feature(tmp_path, "nmi_mul",
                       '[[claims.reg]]\nregisters = ["ALU"]\n')
    with pytest.raises(AllocationError, match="ALU"):
        compose(tmp_path, [rl, nmi_user])


# -- vocabulary: accepted spellings, rejected ones, teaching errors --------

def test_reg_claim_accepts_the_names_the_census_needed(tmp_path):
    """The six BG names C4 required and the two CPU-bus ones."""
    f = feature(tmp_path, "vocab",
                '[[claims.reg]]\nregisters = ["BG1SC", "BG2SC", "BG3SC", '
                '"BG4SC", "BG12NBA", "BG34NBA", "NMITIMEN", "ALU"]\n')
    assert len(f.reg) == 1 and len(f.reg[0].registers) == 8


def test_unknown_register_name_is_rejected_with_the_vocabulary(tmp_path):
    """A typo is not a resource: an unrecognised name would otherwise opt the
    claim out of every check it should have joined."""
    with pytest.raises(SchemaError) as e:
        feature(tmp_path, "typo", '[[claims.reg]]\nregisters = ["CGWSELL"]\n')
    assert "CGWSELL" in str(e.value)
    assert "CGWSEL" in str(e.value)          # the real name is offered back


def test_reg_claim_rejects_unknown_fields(tmp_path):
    """No phase/band/channel/mode on this class — a CPU write is not a
    transfer. Accepting them silently would invite the phase model back."""
    for bad in ('phase = "active"', "band = \"scene\"", "channels = 1",
                "mode = 0"):
        with pytest.raises(SchemaError):
            feature(tmp_path, f"bad{abs(hash(bad))}",
                    f'[[claims.reg]]\nregisters = ["BGMODE"]\n{bad}\n')


# -- the B-bus guard ------------------------------------------------------

@pytest.mark.parametrize("cls,extra", [
    ("hdma", 'band = "scene"\nphase = "active"\nchannels = 1\n'),
    ("dma_init", "channel = 0\n"),
])
def test_cpu_bus_name_on_a_transfer_claim_is_rejected(tmp_path, cls, extra):
    """BBAD is only the port's LOW byte, widened by hardware to $2100|BBAD.

    So a $42xx name on a transfer claim does not fail — it silently retargets a
    REAL, different register. ALU ($4202) would drive $2102 OAMADDL. The error
    must SHOW that aliasing, because the whole hazard is that it is invisible.
    """
    with pytest.raises(SchemaError) as e:
        feature(tmp_path, f"bbad_{cls}",
                f'[[claims.{cls}]]\nregisters = ["ALU"]\n{extra}')
    msg = str(e.value)
    assert "$4202" in msg and "$2102" in msg
    assert "claims.reg" in msg               # points at the right class


def test_every_transfer_target_in_the_tree_is_b_bus_addressable():
    """The invariant the guard rests on, asserted over the SHIPPING tree
    rather than over a fixture — this is what would catch a future feature
    slipping a CPU-bus name onto an hdma claim through some other path."""
    for fp in sorted(FEATURES.glob("*/feature.toml")):
        f = load_feature(fp, SUB)
        for c in (*f.hdma, *f.dma_init):
            off = [r for r in c.registers if r not in B_BUS_REGISTERS]
            assert not off, f"{f.name}/{c.name} targets {off} off the B bus"


def test_cpu_bus_names_are_exactly_the_three_we_intend():
    """A new CPU-bus name is a design decision (it needs the ALU-style
    aliasing analysis), so it should not arrive unnoticed.

    The tripwire fired at the 2026-08-14 sweep-tail landing, exactly as
    designed: HVIRQ arrived WITH the spanned-name analysis in schemas.py's
    comment block, and this pin is the acknowledgment."""
    cpu_bus = sorted(set(REGISTER_FOOTPRINT) - set(B_BUS_REGISTERS))
    assert cpu_bus == ["ALU", "HVIRQ", "NMITIMEN"]


def test_alu_is_one_name_not_a_multiplier_and_a_divider():
    """Mesen2 AluMulDiv.cpp holds ONE _state that multiply and divide mutually
    destroy (:94 case 0x4203 clobbers DivResult; :106 case 0x4206 clobbers
    MultOrRemainderResult). (port, mask) cannot express cross-PORT aliasing —
    _register_conflicts only fires on equal ports — so separate WRMPYA/WRDIVL
    names would compose while physically fighting. One name has nothing to
    alias; this guards against someone "completing" the vocabulary."""
    assert "ALU" in REGISTER_FOOTPRINT
    for tempting in ("WRMPYA", "WRMPYB", "WRDIVL", "WRDIVH", "WRDIVB",
                     "RDDIVL", "RDDIVH", "RDMPYL", "RDMPYH"):
        assert tempting not in REGISTER_FOOTPRINT, (
            f"{tempting} splits the ALU into ports that would compose while "
            f"destroying each other — see REGISTER_FOOTPRINT's ALU comment")


# --------------------------------------------------------------------------
# scene_writes / scene_writes_shared (item 5) — the DECLARATION-side half
#
# Test surface note: these are declaration validators, so the output region is
# the build's refusal + its diagnostic text, the same surface the rest of this
# module asserts on. The RULE half — a scene write to an owned-but-unopened
# port — is a writer-side gate whose output is an exit code and stderr, and it
# is tested by running the real tool as a subprocess in test_reg_gate.py.
# --------------------------------------------------------------------------

def test_scene_writes_outside_registers_refuses(tmp_path):
    """A claim may only open a register it HOLDS. Opening one it does not is a
    permission granted over another feature's resource, and the allocator's
    one-declarer-per-port rule would then have nothing to attach it to."""
    with pytest.raises(SchemaError, match="scene_writes names"):
        feature(tmp_path, "swbad",
                '[[claims.reg]]\nname = "c"\nregisters = ["BGMODE"]\n'
                'scene_writes = ["TM"]\n')


def test_scene_writes_shared_outside_scene_writes_refuses(tmp_path):
    """scene_writes_shared says "and I write it too" — only meaningful about a
    register scene code was permitted to write in the first place."""
    with pytest.raises(SchemaError, match="scene_writes_shared names"):
        feature(tmp_path, "swsbad",
                '[[claims.reg]]\nname = "c"\nregisters = ["BGMODE", "TM"]\n'
                'scene_writes = ["BGMODE"]\nscene_writes_shared = ["TM"]\n')


def test_unknown_name_in_scene_writes_refuses_with_the_same_vocabulary(tmp_path):
    """`scene_writes` routes through `_parse_registers` with a
    `key=`, so a typo there gets the SAME "a typo is not a resource" error as
    a typo in `registers` — not a second error vocabulary.

    WRDIVL is the live example: the spec and the spec both used it to justify
    span expansion, and it is not a REGISTER_FOOTPRINT name at all (the ALU is
    one name — see test_alu_is_one_name_not_a_multiplier_and_a_divider), so
    the declaration those documents described would have been refused."""
    with pytest.raises(SchemaError, match="unknown register name"):
        feature(tmp_path, "swtypo",
                '[[claims.reg]]\nname = "c"\nregisters = ["ALU"]\n'
                'scene_writes = ["WRDIVL"]\n')


def test_scene_writes_defaults_to_empty_and_parses_when_given(tmp_path):
    """The silent sibling: the fields are OPTIONAL and additive. A claim
    without them is byte-identical in behaviour to one written before they
    existed — which is what makes M1 inert."""
    f = feature(tmp_path, "swok",
                '[[claims.reg]]\nname = "plain"\nregisters = ["BGMODE"]\n')
    assert f.reg[0].scene_writes == () and f.reg[0].scene_writes_shared == ()
    f = feature(tmp_path, "swok2",
                '[[claims.reg]]\nname = "opened"\n'
                'registers = ["INIDISP", "NMITIMEN"]\n'
                'scene_writes = ["NMITIMEN"]\nscene_writes_shared = ["NMITIMEN"]\n')
    c = f.reg[0]
    assert c.registers == ("INIDISP", "NMITIMEN")
    assert c.scene_writes == ("NMITIMEN",)
    assert c.scene_writes_shared == ("NMITIMEN",)


def test_an_unknown_key_on_a_reg_claim_still_refuses(tmp_path):
    """_table rejects unknown keys, and the two new optional entries must not
    have opened the table up: `scene_write` (singular typo) is not a field."""
    with pytest.raises(SchemaError, match="unknown key"):
        feature(tmp_path, "swkey",
                '[[claims.reg]]\nname = "c"\nregisters = ["BGMODE"]\n'
                'scene_write = ["BGMODE"]\n')
