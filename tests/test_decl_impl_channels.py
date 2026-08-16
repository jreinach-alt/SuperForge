"""Does the ROM program the channels its declarations describe? EVERY scene.

the spec's gap was that every collision proof in this repo is a statement
about the DECLARATIONS rather than about the ROM. Emitting the BBAD/DMAP bytes
from the declaration (ES_H_<CLAIM>_BBAD / _DMAP) closes the drift direction by
construction — the encoding has one source now, so the ASM cannot name one
register and drive another. What emission does NOT establish is the two
questions that remain about the ROM itself:

  ACCURACY     — is each declared channel actually programmed, at the channel
                 number the declaration names? A claim can be honest and its
                 arming code still never run, or run against the wrong claim's
                 _CH symbol. Neither is caught by emission.
  COMPLETENESS — is any channel ENABLED that no claim of the running scene
                 declares? This is the direction the four enter-time DMA users
                 sat in for a whole phase: driving a hard-coded channel 0
                 while being invisible to the occupancy gate. Emission cannot
                 see an undeclared channel, because there is no declaration to
                 emit from.

WHAT THESE TESTS READ — and why the first two versions of this file were wrong.

The assertion surface is the LIVE DMA CONTROLLER: `runner.snes_dma_state()`
returns all eight channels' real $43x0/$43x1 bytes and the real $420C mask,
read out of Mesen's `SnesDmaControllerState` via the DLL's GetConsoleState
export. That is the silicon, not a copy of it.

Version 1 asserted against the ROM's own WRAM HDMAEN shadow instead, because
the debugger's *peek* path genuinely cannot reach $4300-$431F or $420C (both
come back as open bus / zeros — independently reproduced,
a measured census). A later review armed a genuinely
undeclared HDMA channel 7 directly in $420C and
`test_no_undeclared_channel_is_enabled` PASSED, along with 233 of 235 tests.

Version 2 fixed the surface but not the SCOPE: it read ONE `snes_dma_state()`
at ONE instant in ONE scene (`race`, after `enter_race`) and took its
declaration set from `decl["race"]` alone. Nothing sampled `title`, nothing
sampled `results`, nothing sampled a second frame — and the scoping was
disclosed nowhere, so a reader was told the module covered "no channel is armed
that nothing declares", full stop. A later review armed an undeclared channel 6 in
`results::enter`, which fired race's leftover register configuration into $212C
(TM) on every scanline: the results screen rendered as total garbage, row-luma
spread 45 -> 128, and **266/266 tests passed**.

So this version samples EVERY SCENE IN THE MANIFEST — including the two that
declare no HDMA channel at all, which is where the undetected mutation lived —
and EVERY FRAME of a full title -> race -> results -> title loop, not one
instant per scene. Tests are parameterised over the scene; the per-frame
invariant runs across the whole drive, transitions included.

WHY THERE IS NO "UNCLAIMED SLOTS READ $00" TEST ANY MORE. The previous
`test_shadow_is_clear_outside_the_declared_channels` asserted that the shadow
bytes of unclaimed channels held $00. That leans on zero being the natural
state of RAM, which is exactly what CLAUDE.md rule 5 forbids assuming: on real
hardware this 128-byte block powers on holding random DRAM garbage, and the
severe form of the bug is a slot that was NEITHER zeroed NOR programmed whose
HDMAEN bit gets set — HDMA then drives an arbitrary PPU port from an arbitrary
address. The property that actually matters is about ENABLEMENT and PROVENANCE:
nothing is enabled whose live configuration did not come from a claim the
running scene declares. That is
`test_every_enabled_channel_was_programmed_by_a_declaring_claim`, and it holds
whatever garbage an unprogrammed slot happens to contain.

The zeroing is still checked — as the MITIGATION it is, by
`test_settled_scenes_hold_no_stale_configuration_from_the_previous_scene`,
which observes that scene_mgr's transition clear ran. Detector and mitigation
are separate on purpose: the detector must fail on the mutation even with the
mitigation reverted, or this change traded a detector for a mitigation.

The WRAM shadow assertions are KEPT, as a separate and clearly-labelled check
of the ARMING CODE's output rather than of the hardware. They still earn their
place: when a hardware assertion fails, the shadow check says whether the
arming code computed the wrong bytes or the MVN failed to deliver correct ones.
They are no longer load-bearing for any claim about what the silicon does.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tests"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402
import mz_drive as D  # noqa: E402

WR = MemoryType.SnesWorkRam
ROM = SUPERFORGE / "build" / "microzero.sfc"
MAP = SUPERFORGE / "build" / "mz" / "symbol_map.json"

CH_STRIDE = 16          # $4300 register file: 16 bytes per channel
OFF_DMAP = 0            # $43x0
OFF_BBAD = 1            # $43x1

SCENES = ("title", "race", "results")
SCENE_ID = {"title": 0, "race": 1, "results": 2}
# Frames of settled steady state to keep sampling in each scene beyond arrival.
SETTLE_FRAMES = 12


@pytest.fixture(scope="module")
def built():
    """Build the ROM the assertions read.

    Not optional: on a bare checkout build/ does not exist, and a fixture that
    merely READS the artifacts passes locally on a warm tree while failing in
    CI. That is what happened to this file on its first CI run — the same
    stale-artifact class as a corrupted symbol_map.json.
    Every other microzero test module shells out to make for this reason.
    """
    r = subprocess.run(["make", "microzero"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"make microzero failed:\n{r.stdout}\n{r.stderr}"


@pytest.fixture(scope="module")
def jmap(built):
    return json.loads(MAP.read_text())


@pytest.fixture(scope="module")
def syms(jmap):
    """Globals only — the scene_mgr control block and the HDMA shadow."""
    return {p["sym"]: p for p in jmap["globals"]}


@pytest.fixture(scope="module")
def scene_syms(jmap):
    """Per-scene symbol tables (scene placements + globals), for the drive."""
    return {n: {p["sym"]: p for p in jmap["scenes"][n]["placements"]
                + jmap["globals"]} for n in SCENES}


@pytest.fixture(scope="module")
def decl(jmap):
    return jmap["scenes"]


def _active(decl, scene):
    return [c for c in decl[scene]["channels"] if c["phase"] == "active"]


def _hdmaen_shadow(runner, syms) -> int:
    # ES_SM_NMI +2 is the WRAM byte the NMI writes to $420C. DP lives at 0, and
    # DP $00xx mirrors WRAM $7E00xx, so the WRAM read reaches it. NOT the
    # hardware register — see the module docstring.
    return runner.read_bytes(WR, syms["ES_SM_NMI"]["start"] + 2, 1)[0]


def _shadow(runner, syms) -> bytes:
    base = syms["ES_SM_HDMA"]["start"]
    return runner.read_bytes(WR, base, syms["ES_SM_HDMA"]["size"])


class Frame:
    """One frame's live DMA state, plus which scene the ROM says it is in."""

    __slots__ = ("n", "scene", "phase", "hdmaen", "chans")

    def __init__(self, n, scene, phase, hdmaen, chans):
        self.n, self.scene, self.phase = n, scene, phase
        self.hdmaen, self.chans = hdmaen, chans

    @property
    def armed(self):
        return {b for b in range(8) if self.hdmaen & (1 << b)}

    def __repr__(self):
        return (f"frame {self.n} (scene {self.scene}, phase {self.phase}, "
                f"HDMAEN=${self.hdmaen:02X})")


@pytest.fixture(scope="module")
def observed(built, syms, scene_syms):
    """Every frame of a full title -> race -> results -> title loop.

    Returns (runner, frames, shadows). `frames` is one record per emulated
    frame across the whole loop — transitions included — so the assertions
    below are statements about the ROM's whole life rather than about one
    sampled instant. `shadows` is one 128-byte WRAM shadow read per scene,
    taken at a settled frame of that scene.

    Reaching `results` needs the three laps the game asks for; that is the same
    drive tests/test_microzero_loop.py does, via the same oracle, and the whole
    sweep costs ~20 s for ~1400 frames.
    """
    lut = D.load_tool("gen_move_lut")
    runner = MesenRunner()
    runner.boot_rom(str(ROM))
    runner.debug_break()
    runner.frame_step(2)

    frames, shadows = [], {}

    def snap():
        cur, _nxt, phase = runner.read_bytes(WR, syms["ES_SM_CTL"]["start"], 3)
        d = runner.snes_dma_state()
        frames.append(Frame(len(frames), cur, phase, d.hdmaen,
                            tuple((c.dmap, c.bbad) for c in d.channels)))

    def step(n=1, **kw):
        for _ in range(n):
            runner.frame_step(1, **kw)
            snap()

    def settle(scene, limit=700):
        """Frame-step until the phase machine has settled INTO `scene`, then
        sample SETTLE_FRAMES more and record the scene's shadow."""
        want = SCENE_ID[scene]
        for _ in range(limit):
            if D.scene_now(runner, syms) == (want, 0):
                step(SETTLE_FRAMES)
                shadows[scene] = _shadow(runner, syms)
                return
            step(1)
        raise AssertionError(
            f"{scene} never settled in {limit} frames — stuck at "
            f"{D.scene_now(runner, syms)}. Every scene-scoped read from here "
            f"would be uninitialised WRAM, not game state.")

    try:
        settle("title")
        step(2, start=True)
        settle("race")
        # three laps hand off to results (race_logic requests the scene)
        sim = D.sim_from_rom(runner, scene_syms["race"], lut)
        for _ in range(900):
            kw = D.track_buttons(sim, lut)
            runner.frame_step(1, **kw)
            sim.frame(left=kw.get("left", False), right=kw.get("right", False),
                      b=kw.get("b", False), down=kw.get("down", False))
            snap()
            if sim.lap >= 3:
                break
        assert sim.lap >= 3, "never completed three laps — results unreachable"
        settle("results")
        # results only accepts START once its tally has caught up to the score
        # (results.asm gates the scene request on US_R_DONE), so waiting for it
        # is required rather than defensive — and the wait is itself ~40 more
        # settled results frames of channel coverage.
        done = scene_syms["results"]["US_R_DONE"]["start"]
        for _ in range(400):
            if runner.read_bytes(WR, done, 1)[0]:
                break
            step(1)
        else:
            raise AssertionError("the results tally never latched done")
        step(2, start=True)
        settle("title")          # the revisit: every scene entered twice
        yield runner, frames, shadows
    finally:
        runner.stop()


def _settled(frames, scene):
    """Frames where the phase machine is RUNNING `scene` (transition done)."""
    return [f for f in frames if f.scene == SCENE_ID[scene] and f.phase == 0]


# -- the sample itself must be real before anything asserted on it counts ----

def test_the_sample_covers_every_scene_and_more_than_one_instant(observed):
    """Non-vacuity for the whole module.

    Version 2 of this file was wrong about SCOPE, not about correctness, and a
    scope regression is invisible: every parameterised test below would still
    pass if the drive silently stopped reaching `results`. So the coverage is
    asserted first, by name, and the numbers are floors rather than exact
    counts (the drive is frame-anchored but lap timing depends on the
    controller).
    """
    _runner, frames, shadows = observed
    assert set(shadows) == set(SCENES), (
        f"the drive only reached {sorted(shadows)} — a scene that is never "
        f"entered is a scene whose channel declarations are never checked")
    for scene in SCENES:
        s = _settled(frames, scene)
        assert len(s) >= SETTLE_FRAMES, (
            f"only {len(s)} settled frames sampled in {scene}; a single "
            f"instant is what let a later review mutation through")
    assert len(frames) > 500, f"only {len(frames)} frames sampled in total"
    # ...and at least one scene must actually arm something, or every
    # COMPLETENESS assertion below is `set() <= set()`.
    assert any(f.armed for f in frames), (
        "no frame in the entire loop had a single HDMA channel enabled — "
        "either the ROM arms nothing or HDMAEN is being misread")


# -- the ctypes mirror must be reading the struct it thinks it is -----------

def test_console_state_layout_anchor(observed):
    """GetConsoleState's mirrored offsets land on the fields they name.

    Every assertion below reads `SnesState` — a plain C++ aggregate with no
    stable ABI — through hardcoded byte offsets (vendor/mesen_runner.py,
    re-derivable with tools/mesen_state_offsets.cpp). A wrong offset that
    happens to read plausible bytes would be a subtler version of exactly the
    bug this file exists to fix, so the layout is ANCHORED rather than assumed.

    The anchor is `InternalRegs`, and it is chosen because it can be predicted
    with NO reference to the DMA subsystem — which is what the DMA assertions
    are for, and would make a DMA-derived anchor circular:

      * NMITIMEN == $81. `vendor/rom/init.inc:47` boots with `stz $4200`, and
        the only other writer is scene_mgr (`$81` = NMI + auto-joypad on).
        So NMI on, auto-joypad on, both IRQs off.
      * EnableFastRom is True — `lda #$01 / sta $420D` in init.inc:56.
      * H/V timers are still their power-on $1FF (Mesen2
        InternalRegisters.cpp:31-32); microzero never writes $4207-$420A.
      * EmulationMode is False — init.inc does CLC/XCE into native mode, and
        nothing ever leaves it. This one pins the CPU sub-struct, which is
        where `cpu_pc` / `cpu_k` are read from for the per-SITE attribution in
        tests/test_dma_init_forced_blank.py.

    `InternalRegs` sits immediately after `Dma` in the struct (1238 + 162 =
    1400), so pinning it pins the DMA base too. The DMA side additionally gets
    a structural check on every single read
    (mesen_runner._validate_snes_state_layout: C++ bools must be 0/1, DMAP's
    transfer mode must be 0-7), which a misaligned read fails immediately.
    """
    runner, _frames, _shadows = observed
    ir = runner.snes_internal_regs()
    assert ir.nmitimen == 0x81, (
        f"NMITIMEN reads ${ir.nmitimen:02X}; the ROM writes $81 (init.inc "
        f"$4200=0, scene_mgr $4200=$81) — either the ROM changed or the "
        f"mirrored SnesState offsets no longer match this Mesen2 core "
        f"(re-derive with tools/mesen_state_offsets.cpp)")
    assert ir.enable_nmi and ir.enable_auto_joypad_read
    assert not ir.enable_h_irq and not ir.enable_v_irq
    assert ir.enable_fast_rom, (
        "EnableFastRom is False, but init.inc writes MEMSEL=$01 — offsets "
        "suspect (tools/mesen_state_offsets.cpp)")
    assert (ir.h_timer, ir.v_timer) == (0x1FF, 0x1FF), (
        f"H/V timers read (${ir.h_timer:04X}, ${ir.v_timer:04X}); microzero "
        f"never writes $4207-$420A so both must still hold Mesen's power-on "
        f"$1FF — offsets suspect")

    snap = runner.snes_state_snapshot()
    assert snap.emulation_mode is False, (
        "SnesCpuState.EmulationMode reads True, but init.inc switches to "
        "native mode with CLC/XCE and never switches back — the CPU "
        "sub-struct offsets are suspect (tools/mesen_state_offsets.cpp)")
    assert 0x8000 <= snap.cpu_pc <= 0xFFFF, (
        f"CPU PC reads ${snap.cpu_pc:04X}; microzero executes from LoROM "
        f"$8000-$FFFF, so this offset is not PC")

    # The buffer really is a live SnesState and not a stale copy: the master
    # clock is at offset 0, so it must be stable while the runner is parked
    # (the fixture leaves it frame-stepping) and must advance by one frame's
    # worth of master cycles across exactly one frame_step. NTSC is 1364 mc
    # per scanline x 262 lines = 357,368 mc/frame; the bound is deliberately
    # loose (interlace/short-scanline variation) but excludes both "did not
    # move" and "moved by an unrelated amount".
    parked = {runner.snes_state_snapshot().master_clock for _ in range(3)}
    assert len(parked) == 1, (
        f"MasterClock moved while the emulator was parked ({parked}) — the "
        f"read is not settled or offset 0 is not MasterClock")
    before = parked.pop()
    runner.frame_step(1)
    delta = runner.snes_state_snapshot().master_clock - before
    assert 300_000 < delta < 420_000, (
        f"MasterClock advanced {delta} across one frame_step; one NTSC frame "
        f"is ~357,368 master cycles — offset 0 is not MasterClock")


# -- ACCURACY: the hardware programs what the declaration says --------------

@pytest.mark.parametrize("scene", SCENES)
def test_every_active_claim_is_programmed_as_declared(observed, decl, scene):
    """Each active claim's channel holds its declared DMAP and BBAD in silicon,
    on EVERY settled frame of the scene that declares it.

    Reads the live $43x0/$43x1 pair out of the DMA controller and compares it
    against the declared encoding in symbol_map.json, at the offset the
    DECLARED channel number picks out. An arming path that used the wrong
    claim's _CH symbol lands its bytes in another channel's registers and fails
    here even though both claims are individually well-formed; so does a
    correctly-computed shadow that never reaches the register file.
    """
    _runner, frames, _shadows = observed
    claims = _active(decl, scene)
    for f in _settled(frames, scene):
        for c in claims:
            dmap, bbad = f.chans[c["ch"]]
            assert (dmap, bbad) == (c["dmap"], c["bbad"]), (
                f"{scene}/{c['name']} at {f}: ch{c['ch']} holds "
                f"DMAP=${dmap:02X} BBAD=${bbad:02X} (-> ${0x2100 | bbad:04X}) "
                f"in hardware, declared ${c['dmap']:02X}/${c['bbad']:02X} "
                f"(-> ${0x2100 | c['bbad']:04X}) for {','.join(c['registers'])}")
    if scene == "race":
        assert len(claims) == 7, (
            f"expected the race scene's 7 active claims, got "
            f"{[c['name'] for c in claims]}")


@pytest.mark.parametrize("scene", SCENES)
def test_every_active_claim_is_actually_enabled(observed, decl, scene):
    """A declared channel that nothing enables is a declaration about nothing.

    HDMAEN is what makes an armed channel real; a claim whose bit is clear is
    holding a channel number and a register the allocator is proving things
    about while the silicon ignores it. Read from the real $420C, on every
    settled frame — a channel that is armed on arrival and quietly dropped
    later fails here too.
    """
    _runner, frames, _shadows = observed
    for f in _settled(frames, scene):
        for c in _active(decl, scene):
            assert f.hdmaen & (1 << c["ch"]), (
                f"{scene}/{c['name']} declares ch{c['ch']} but at {f} the "
                f"hardware HDMAEN is ${f.hdmaen:02X} — that bit is clear, so "
                f"the claim is not armed")


# -- COMPLETENESS: the hardware arms nothing it did not declare -------------

@pytest.mark.parametrize("scene", SCENES)
def test_no_undeclared_channel_is_enabled(observed, decl, scene):
    """The direction emission cannot cover, in every scene of the manifest.

    Emitting BBAD from a declaration proves nothing about a transfer that has
    no declaration. This asserts the inverse: the set of bits in the REAL $420C
    is EXACTLY the set of channels the scene's active-phase claims name.

    Equality, not inclusion. `armed <= declared` passes trivially when `armed`
    is empty, which is the state `title` and `results` are legitimately in AND
    the state a misaligned struct read produces
    inclusion form passing at two wrong DMA base offsets where the misread
    HDMAEN was $00 (N5b). Under equality, `race` (7 channels) is the
    non-vacuity guard for the whole family, and `title`/`results` still fail
    the moment anything arms a channel they do not declare.

    The mutation this exists to catch: `lda #(1 << 6) / sta z:ES_SM_NMI+2` at
    the top of `results::enter`, which armed race's leftover TM configuration
    on every scanline of the results screen while all 266 tests passed.
    """
    _runner, frames, _shadows = observed
    declared = {c["ch"] for c in _active(decl, scene)}
    for f in _settled(frames, scene):
        assert f.armed == declared, (
            f"{scene} at {f}: the hardware HDMAEN arms {sorted(f.armed)} but "
            f"its active-phase claims declare {sorted(declared)} "
            f"(undeclared: {sorted(f.armed - declared)}, "
            f"declared-but-off: {sorted(declared - f.armed)})")


def test_every_enabled_channel_was_programmed_by_a_declaring_claim(observed,
                                                                   decl):
    """THE invariant, on every frame of the loop including mid-transition.

    For each bit set in the live $420C: some claim of the scene the ROM says it
    is running must name that channel, AND the channel's live (DMAP, BBAD) must
    be that claim's declared encoding. Only `active`-phase claims qualify —
    `vblank` and `forced_blank` claims are GP-DMA and are never supposed to
    appear in HDMAEN at all, so a channel enabled while holding a dma_init
    claim's encoding (HDMA pointed at VMDATA every scanline) fails here.

    This is deliberately NOT phrased as "unclaimed slots read $00". The
    128-byte register shadow powers on holding random DRAM garbage on real
    hardware (CLAUDE.md rule 5), so the severe form of the bug is a slot that
    was neither zeroed nor programmed whose HDMAEN bit gets set — HDMA driving
    an arbitrary PPU port from an arbitrary address. A test that leans on zero
    being the natural state cannot see that; a test about ENABLEMENT and
    PROVENANCE sees it whatever the garbage happens to be.

    It is also the reason the engine's transition-time shadow clear is
    mitigation and not the detector: revert the clear and this test still fails
    on the N1 mutation, because ch6 would then be enabled holding race's
    encoding, which `results` does not declare.
    """
    _runner, frames, _shadows = observed
    by_scene = {}
    for name, sid in SCENE_ID.items():
        m = {}
        for c in _active(decl, name):
            m.setdefault(c["ch"], set()).add((c["dmap"], c["bbad"]))
        by_scene[sid] = m
    bad = []
    for f in frames:
        allowed = by_scene[f.scene]
        for ch in f.armed:
            if f.chans[ch] not in allowed.get(ch, set()):
                bad.append((f, ch, f.chans[ch], sorted(allowed.get(ch, set()))))
    assert not bad, (
        f"{len(bad)} frame/channel pairs where an ENABLED channel holds a "
        f"configuration no active claim of the running scene declares:\n"
        + "\n".join(
            f"  {f}: ch{ch} live DMAP=${d:02X} BBAD=${b:02X} "
            f"(-> ${0x2100 | b:04X}); scene declares {want or 'NOTHING'} "
            f"for that channel"
            for f, ch, (d, b), want in bad[:8]))


@pytest.mark.parametrize("scene", SCENES)
def test_unclaimed_channels_are_clear_in_hardware(observed, decl, scene):
    """A channel no claim of ANY phase names holds no configuration at all.

    A programmed-but-unarmed channel is one stray $420C write away from driving
    a PPU port nobody declared, and it is invisible to the occupancy gate
    because there is no claim to occupy anything. Reads the real register file,
    so it also covers a channel programmed directly rather than through the
    shadow the MVN copies.

    Scoped to SETTLED frames. Between the forced-blank switch and the first
    armed NMI of the new scene, the hardware register file still holds the
    OUTGOING scene's bytes — the transition clears the WRAM shadow, and the MVN
    that delivers it runs at the next VBlank. Measured: that window is one
    frame, it sits in fade-in, and HDMAEN is $00 throughout it, so nothing can
    act on the residue. The invariant that covers that window is
    test_every_enabled_channel_was_programmed_by_a_declaring_claim, which holds
    on every frame.
    """
    _runner, frames, _shadows = observed
    claimed = {c["ch"] for c in decl[scene]["channels"]}
    claimed |= {c["ch"] for c in decl[scene]["dma_init"]}
    for f in _settled(frames, scene):
        for ch in range(8):
            if ch in claimed:
                continue
            dmap, bbad = f.chans[ch]
            assert (dmap, bbad) == (0, 0), (
                f"{scene} at {f}: ch{ch} is claimed by nothing yet its "
                f"hardware registers hold DMAP=${dmap:02X} BBAD=${bbad:02X} "
                f"(-> ${0x2100 | bbad:04X})")


def test_settled_scenes_hold_no_stale_configuration_from_the_previous_scene(
        observed, decl):
    """The MITIGATION: scene_mgr's transition clear actually ran.

    `sm_init` zeroed the 128-byte channel-register shadow at BOOT ONLY. The
    transition cleared `$420C` and the HDMAEN shadow byte but left the register
    file holding the outgoing scene's live HDMA configuration, so any later
    scene that armed a channel number a previous scene had used inherited that
    scene's registers for it — which is what turned a later review mutation from
    inert into "results renders as total garbage" (N1, and a later review
    correction to a later review: the all-zeros ch7 slot a later review armed terminated
    immediately and was pixel-identical to baseline).

    Concretely: `race` programs ch1..ch6, `results` declares only ch0. Before
    the fix, ch1..ch6 still read race's DMAP/BBAD at the results screen. This
    asserts they read as unprogrammed, in BOTH the WRAM shadow and the live
    register file.

    This is a mitigation check, not the detector, and it is the one assertion
    in the module that does compare against $00 — legitimately, because it is
    asserting that a specific CLEAR executed, not that RAM is naturally zero.
    """
    _runner, frames, _shadows = observed
    prev = {"title": None, "race": "title", "results": "race"}
    for scene, before in prev.items():
        if before is None:
            continue
        stale = {c["ch"] for c in decl[before]["channels"]}
        mine = {c["ch"] for c in decl[scene]["channels"]}
        mine |= {c["ch"] for c in decl[scene]["dma_init"]}
        inherited = sorted(stale - mine)
        if not inherited:
            continue
        for f in _settled(frames, scene):
            for ch in inherited:
                assert f.chans[ch] == (0, 0), (
                    f"{scene} at {f}: ch{ch} still holds "
                    f"DMAP=${f.chans[ch][0]:02X} BBAD=${f.chans[ch][1]:02X} "
                    f"from the {before} scene — scene_mgr's transition did not "
                    f"clear the channel-register shadow (sm_hdma_shadow_clear)")


# -- the ARMING CODE's output (WRAM shadow), as a failure localiser ---------

@pytest.mark.parametrize("scene", SCENES)
def test_hdma_shadow_matches_the_declared_encoding(observed, syms, decl, scene):
    """The 128-byte shadow the arming code produces agrees with the declaration.

    NOT a hardware assertion — this reads the WRAM block sm_nmi_core MVNs to
    $4300. It is kept because it splits a hardware failure in two: if the
    hardware test above fails and this one passes, the arming code was right
    and the delivery path (the MVN, or a $420C write) is broken; if both fail,
    the arming code computed the wrong bytes.
    """
    runner, _frames, shadows = observed
    sh = shadows[scene]
    for c in _active(decl, scene):
        i = c["ch"] * CH_STRIDE
        assert (sh[i + OFF_DMAP], sh[i + OFF_BBAD]) == (c["dmap"], c["bbad"]), (
            f"{scene}/{c['name']}: shadow slot ch{c['ch']} holds "
            f"DMAP=${sh[i + OFF_DMAP]:02X} BBAD=${sh[i + OFF_BBAD]:02X}, "
            f"declared ${c['dmap']:02X}/${c['bbad']:02X}")


def test_the_hdmaen_shadow_agrees_with_the_hardware_register(observed, syms):
    """sm_nmi_core is the only per-frame writer of $420C, so the two must match.

    A disagreement localises to the DELIVERY path: something other than
    sm_nmi_core armed (or disarmed) a channel. This is the assertion that
    caught a later review's reproduction of a later review's hardware-only mutation
    (`ora #$80` between the shadow load and `sta a:$420C`): shadow $7F vs
    hardware $FF, i.e. "the delivery path added a bit".
    """
    runner, _frames, _shadows = observed
    assert _hdmaen_shadow(runner, syms) == runner.snes_dma_state().hdmaen, (
        "the HDMAEN shadow and the hardware $420C disagree — sm_nmi_core is "
        "the only per-frame writer of $420C, so something else armed a channel")


# -- the declaration layer itself must stay self-consistent ----------------

def test_declared_bbad_matches_the_declared_register_names(decl):
    """The emitted BBAD must be the first declared register's port, and the
    mode's span must cover exactly the declared names.

    This is the pure-declaration half, and it is cheap: it catches a
    hand-edited symbol_map or an emitter change that stops deriving the byte
    from the footprint table, which would silently un-anchor every runtime
    assertion above.
    """
    sys.path.insert(0, str(SUPERFORGE / "allocator"))
    from schemas import REGISTER_FOOTPRINT, bbad_span  # noqa: E402

    for scene, sm in decl.items():
        for c in [*sm["channels"], *sm["dma_init"]]:
            ports = tuple(REGISTER_FOOTPRINT[r][0] for r in c["registers"])
            assert bbad_span(c["bbad"], c["dmap"]) == ports, (
                f"{scene}/{c['name']}: BBAD ${c['bbad']:02X} + DMAP mode "
                f"{c['dmap'] & 7} drives "
                f"{[f'${p:04X}' for p in bbad_span(c['bbad'], c['dmap'])]}, "
                f"but {c['registers']} are at {[f'${p:04X}' for p in ports]}")
