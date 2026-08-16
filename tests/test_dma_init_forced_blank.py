"""D7's `forced_blank` precondition, machine-checked at the firing instant.

Decision D7 is why `claims.dma_init` needs no mutual
exclusion between claims that share channel 0: every enter-time upload fires
while scene_mgr has NMI masked and HDMAEN cleared, so no HDMA channel and no
VBlank-phase transfer can be mid-flight and time-share the register file. That
was verified by READING the ASM (`vendor/rom/init.inc:47-48`,
`engine/features/scene_mgr/scene_mgr.asm`) and recorded as *owed* runtime work:
nothing enforced it, and a future feature that called an enter-time upload
routine from `tick:` would silently void the whole justification.

This is the machine check. It reaches the exact instant D7 talks about — the
MDMAEN write that fires a transfer — with a Mesen debugger breakpoint on
writes to $420B, and reads the live DMA controller + NMITIMEN at that break
(GetConsoleState; see vendor/mesen_runner.py). It is not a sample of a nearby
moment: execution is stopped ON the store, before the transfer runs.

HOW A BREAK IS ATTRIBUTED. At the break the firing site has already programmed
the channel it is about to fire, so the channel's live (DMAP, BBAD) pair IS the
claim's declared encoding, and the MDMAEN mask in A says which channel. So
attribution runs off the declaration (`symbol_map.json`), not off a
hand-written table of source line numbers: `(ch, dmap, bbad)` selects the
ENCODING, and the encoding carries the phase.

That is attribution to an encoding, NOT to a claim, and several claims share
one encoding by construction: race's `font_up`, `car_up` and `sky_up` are all
2-register VMDATAL/VMDATAH uploads on channel 0, so all three encode as
ch0 / DMAP $01 / BBAD $18 — five race dma_init claims collapse to three
encodings. An earlier version of this module claimed in its own docstring that
"no two claims in a scene share an encoding, so the attribution cannot be
quietly ambiguous", which was simply false, and the consequence was that
suppressing `sky_up`'s MDMAEN write entirely left the test named
`..._was_observed_firing` GREEN.

So per-CLAIM coverage is established from the FIRING SITE instead, in two
halves that need each other:

  * statically — every declared dma_init claim must have at least one
    `sta $420B` site in the gated sources whose mask names its `ES_D_*_CH`
    symbol. This is what catches a claim nothing fires at all.
  * dynamically — the number of DISTINCT code sites observed firing each
    encoding must equal the number of static sites belonging to the claims
    that share it. This is what catches a site that exists but never executes
    (jumped over, guarded by a condition that is never true).

The site identity is (program bank, PC) from the CPU sub-struct of the same
single GetConsoleState the channel state comes from, so it is one instant.

WHY THE SAMPLE IS A FIXED SIZE. The hunt used to stop early, as soon as every
declared `forced_blank` encoding had been seen. Because the TITLE scene also
fires all three of them, `want <= seen` could be satisfied before the ROM ever
reached the race scene, and the tail then closed — so whether the module
noticed a `dma_init` routine called from `race::tick` depended on scheduling.
A later review measured six runs and four different verdicts on one mutation, and in
NEITHER full `make test` run did the named precondition test fire; one run
reported the whole module green on the exact mutation D7 forbids (N5). The
early exit is gone: the sample always runs to SAMPLE_FIRES, which costs ~5 s,
and `test_the_sample_extended_into_race_steady_state` fails loudly if the
window did not reach the regime the violation would live in.

WHAT IT ASSERTS.
  1. Every fire attributed to a `forced_blank` (dma_init) claim happened with
     NMITIMEN == 0 and the real HDMAEN == 0. That is D7's precondition.
  2. Every declared dma_init claim has a firing site, and every such site was
     OBSERVED firing — so the test cannot pass by never reaching the uploads,
     per claim rather than per encoding.
  3. The sample reached race's steady state (NMI on, scene running), so a
     tick-fired dma_init is inside the window rather than past its end.
  4. At least one VBlank-phase fire was observed WITH NMI enabled — so the test
     is demonstrably able to tell the two classes apart, rather than asserting
     "NMI happens to be off all the time".
  5. Every fire matches some declared claim: an enter-time GP-DMA that nothing
     declares fails here too.
"""
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SUPERFORGE / "vendor"))
sys.path.insert(0, str(SUPERFORGE / "tests"))

from mesen_runner import MemoryType, MesenRunner  # noqa: E402

WR = MemoryType.SnesWorkRam
ROM = SUPERFORGE / "build" / "microzero.sfc"
MAP = SUPERFORGE / "build" / "mz" / "symbol_map.json"

MDMAEN = 0x420B
TITLE, RACE, RESULTS = 0, 1, 2

# The sample is a FIXED number of fires — see the docstring's "WHY THE SAMPLE IS
# A FIXED SIZE". Race entry's mode7 seed loop alone fires ~256 times and entry
# in total is ~300, so 430 always carries the sample ~130 fires past entry into
# steady state (measured: 137-152 race-scene fires with NMI enabled). At ~12 ms
# per break that is ~5 s.
SAMPLE_FIRES = 430
# Fires that must be observed in race's steady state (scene running, NMI on)
# for the precondition assertion to be about anything. Measured 137+; the floor
# is set well below that so host load cannot make it flaky, and well above zero
# so a window that closes at entry fails.
MIN_RACE_STEADY_FIRES = 30
# The hunt's outer guard, in EMULATED frames — not wall seconds. MEASURED: the
# 430 fires cost 160 emulated frames, and no single break was ever more than 1
# frame from the last. 3600 frames is a minute of the ROM's own time, a 22x
# margin, and — unlike the 180 s wall deadline it replaces — host load cannot
# shrink it. That is the whole trade: a smaller multiple counted in frames is
# strictly safer than a larger one counted in seconds, because only one of the
# two can be eaten by a busy box.
BUDGET_FRAMES = 3600
# Per-break budget, same units. Observed worst gap 1 frame; 300 is a 300x
# margin AND the loop's real termination condition when the breakpoint stops
# firing, so it wants to be generous rather than tight.
BREAK_FRAMES = 300

# The gated sources, mirroring the Makefile's MZ_ASM — the set no_literals runs
# over, which is the set that may legally touch a channel at all.
GATED_ASM = ([SUPERFORGE / "game" / "microzero" / "main.asm"]
             + sorted((SUPERFORGE / "game" / "microzero" / "scenes").glob("*.asm"))
             + sorted((SUPERFORGE / "engine" / "features").glob("*/*.asm")))


@pytest.fixture(scope="module")
def built():
    r = subprocess.run(["make", "microzero"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"make microzero failed:\n{r.stdout}\n{r.stderr}"


@pytest.fixture(scope="module")
def decl(built):
    return json.loads(MAP.read_text())["scenes"]


@pytest.fixture(scope="module")
def globals_syms(built):
    return {p["sym"]: p for p in json.loads(MAP.read_text())["globals"]}


def _encodings(scene_decl):
    """(ch, dmap, bbad) -> (claim names, phase) for every claim in a scene.

    Several claims legitimately share one encoding (see the module docstring),
    so this keeps the whole NAME SET rather than first-wins. It still fails
    loudly on a cross-PHASE collision, because that one really would make the
    phase attribution below a guess: a fire with that encoding could be either
    an enter-time upload or a VBlank transfer, and the precondition applies to
    only one of them.
    """
    out = {}
    for c in [*scene_decl["channels"], *scene_decl["dma_init"]]:
        key = (c["ch"], c["dmap"], c["bbad"])
        if key in out and out[key][1] != c["phase"]:
            raise AssertionError(
                f"claims {sorted(out[key][0])} and {c['name']} share the "
                f"encoding ch{key[0]}/DMAP ${key[1]:02X}/BBAD ${key[2]:02X} "
                f"but sit in different phases ({out[key][1]} vs {c['phase']}) "
                f"— a fire with that encoding cannot be attributed to a phase")
        names, _ph = out.setdefault(key, (set(), c["phase"]))
        names.add(c["name"])
    return out


def _static_firing_sites():
    """{claim name -> number of `sta $420B` sites} across the gated sources.

    Parsed with `no_literals`' own primitives, so the notion of "a firing site
    whose mask names claim X" is the one the build gate enforces rather than a
    second, drifting definition. The channel rule requires each mask to be
    built from ES symbols (not any particular count of them); nearly every
    site here loads `lda #(1 << ES_[HD]_<CLAIM>_CH)` and resolves to exactly
    one claim — the one exception is the deliberate all-H multi-channel
    co-fire (the seam pair, sit_cam.asm), which the walk below SKIPS with its
    rationale in place. A multi-name site involving any ES_D_* claim is still
    a module-wide error.
    """
    sys.path.insert(0, str(SUPERFORGE / "allocator"))
    import no_literals as NL  # noqa: E402

    sites = Counter()
    unresolved = []
    for p in GATED_ASM:
        lines = p.read_text().splitlines()
        aliases = NL._enable_aliases(lines)
        for i, raw in enumerate(lines, start=1):
            m = NL.STORE_RE.match(NL._strip(raw))
            if not m:
                continue
            # _enable_port, not the human description: asking WHICH port
            # through prose would rebuild the textual coupling the predicate
            # exists to remove. It also means an alias-spelled MDMAEN store
            # (`FIRE = $420B` / `sta a:FIRE`) is now counted as a firing site.
            port, _why = NL._enable_port(m.group("dest"), aliases)
            if port != "$420B":
                continue
            op = m.group("op").lower()
            if op == "stz":
                continue
            imms, _verdict = NL._provenance(lines, i - 1, NL._REG_OF[op])
            hits = {(c, n.lower()) for _ln, v in imms
                    for c, n in re.findall(r"ES_([HD])_(\w+)_CH(?!\w)", v)}
            names = {n for _c, n in hits}
            if len(names) > 1 and all(c == "H" for c, _n in hits):
                # A deliberate multi-channel CO-FIRE of hdma-class claims: one
                # MDMAEN write arming several co-declared channels at once (the
                # seam pair in sit_cam.asm, where the one write IS the
                # mechanism). Channel-mask provenance there is the
                # channel rule's jurisdiction (no_literals); this census only
                # attributes SINGLE-claim firing sites, because per-claim
                # dma_init coverage is what it exists to establish. A multi-
                # name site involving any ES_D_* claim stays unresolved below.
                continue
            if len(names) != 1:
                unresolved.append((p.relative_to(SUPERFORGE), i, sorted(names)))
                continue
            sites[names.pop()] += 1
    assert not unresolved, (
        "these MDMAEN firing sites do not resolve to exactly one claim, so "
        "per-claim coverage cannot be established from them: "
        + ", ".join(f"{p}:{i} -> {n}" for p, i, n in unresolved)
        + ". Every site must load its mask as `lda #(1 << ES_?_<CLAIM>_CH)`.")
    return sites


@pytest.fixture(scope="module")
def fires(built, decl, globals_syms):
    """A FIXED-SIZE sample of MDMAEN writes from boot through race steady state.

    Returns the fire list plus the attribution tables. Each fire carries the
    attributed encoding, the firing SITE (bank, PC), the scene the phase machine
    says it is in, and the live NMITIMEN and HDMAEN at the instant of the store.
    """
    # Attribution needs the union of every scene's encodings: a break can land
    # in any scene, and the scene the ROM is in mid-switch is ambiguous by
    # construction (scene_mgr sets `cur = next` before calling enter).
    known = {}
    for sm in decl.values():
        for k, (names, ph) in _encodings(sm).items():
            n, _p = known.setdefault(k, (set(), ph))
            n |= names
    ctl = globals_syms["ES_SM_CTL"]["start"]

    runner = MesenRunner()
    runner.boot_rom(str(ROM))
    out = []
    try:
        runner.debug_break()
        # START drives title -> race, whose enter fires all five dma_init
        # claims. Latched before the hunt so the transition happens inside it.
        runner.set_input(0, start=True)
        hunt_start = runner.ppu_frame_count()
        with runner.breakpoints([(MemoryType.SnesMemory, MDMAEN, "write")]):
            while (len(out) < SAMPLE_FIRES
                   and runner.ppu_frame_count() - hunt_start < BUDGET_FRAMES
                   and runner.run_to_break(max_frames=BREAK_FRAMES)):
                s = runner.snes_state_snapshot()
                mask = s.cpu_a & 0xFF
                one = bin(mask).count("1") == 1
                ch = mask.bit_length() - 1 if one else None
                out.append({
                    "mask": mask,
                    "key": None if ch is None else (ch, s.dma.channels[ch].dmap,
                                                    s.dma.channels[ch].bbad),
                    "site": s.site,
                    "scene": runner.read_bytes(WR, ctl, 1)[0],
                    "nmitimen": s.internal_regs.nmitimen,
                    "hdmaen": s.dma.hdmaen,
                })
    finally:
        runner.stop()
    assert out, "no MDMAEN write was ever observed — the breakpoint never fired"
    return {"fires": out, "known": known, "sites": _static_firing_sites()}


def _phase_of(fires, key):
    return fires["known"].get(key, (None, None))[1]


def _names_of(fires, key):
    return sorted(fires["known"].get(key, (set(), None))[0])


# -- the sample must be real before anything asserted on it counts -----------

def test_the_sample_reached_its_full_size(fires):
    """The fixed budget was actually spent, or the assertions below are partial.

    A short sample is not a failure of the ROM, but it IS a failure of the
    measurement, and it must be loud rather than silently narrowing every other
    assertion in the module.

    This equality is the reason the hunt's budgets are counted in EMULATED
    frames. Under the 180 s wall deadline it replaced, a loaded box could close
    the window early and red this assertion with nothing wrong in the ROM —
    an equality assertion gated on host speed, which is the suite's flake shape
    exactly. A frame budget cannot be shortened by host load, so
    a short sample now means the breakpoint stopped firing.
    """
    n = len(fires["fires"])
    assert n == SAMPLE_FIRES, (
        f"only {n} of {SAMPLE_FIRES} fires were sampled in {BUDGET_FRAMES} "
        f"emulated frames — the breakpoint stopped firing (the budget is "
        f"counted in the ROM's own frames, so host load cannot cause this), "
        f"and the precondition below was checked over a narrower window than "
        f"intended")


def test_the_sample_extended_into_race_steady_state(fires):
    """The window covers the regime a tick-fired dma_init would live in.

    This is the assertion the module was missing. D7's exposure is an
    enter-time upload routine being called from `tick:`, which fires with
    NMITIMEN=$81 and HDMAEN armed — i.e. in race's STEADY STATE, after entry
    has finished. A sample that stops at the end of scene entry cannot see it,
    and the old early-exit condition could be satisfied by the TITLE scene's
    fires before the ROM even reached race.
    """
    steady = [f for f in fires["fires"]
              if f["scene"] == RACE and f["nmitimen"] != 0]
    assert len(steady) >= MIN_RACE_STEADY_FIRES, (
        f"only {len(steady)} of {len(fires['fires'])} sampled fires happened "
        f"in the race scene with NMI enabled (floor: "
        f"{MIN_RACE_STEADY_FIRES}). The sample never left the scene-entry "
        f"window, so a dma_init routine called from race::tick would fire "
        f"outside it and this module would report green. Scene histogram: "
        + str(dict(Counter(f["scene"] for f in fires["fires"]))))


def test_every_observed_fire_named_exactly_one_channel(fires):
    """Every MDMAEN mask has exactly one bit — the attribution's precondition.

    Every firing site in the engine writes `lda #(1 << ES_?_<CLAIM>_CH)`, so a
    multi-bit mask means either a site firing two channels at once (which no
    declaration describes) or a harness reading CPU and DMA state from two
    different instants. Asserted here rather than inside the fixture so it
    reports as one named failure instead of an error on every test.
    """
    multi = [f for f in fires["fires"] if bin(f["mask"]).count("1") != 1]
    assert not multi, (
        "MDMAEN masks naming other than exactly one channel: "
        + ", ".join(f"${f['mask']:02X}" for f in multi[:8]))


def test_every_observed_fire_matches_a_declared_claim(fires):
    """A GP-DMA whose channel configuration nothing declares is an earlier phase’s bug.

    Four enter-time DMA users drove a hard-coded channel 0 for a whole phase
    while being invisible to the occupancy gate. This is that class, observed
    at the fire rather than inferred from the source.
    """
    unknown = {f["key"] for f in fires["fires"]} - set(fires["known"])
    assert not unknown, (
        "MDMAEN fired transfers whose channel configuration matches no "
        "declared claim: " + ", ".join(
            f"ch{k[0]} DMAP ${k[1]:02X} BBAD ${k[2]:02X} "
            f"(-> ${0x2100 | k[2]:04X})" for k in sorted(unknown)))


def test_dma_init_transfers_fire_with_nmi_masked_and_hdma_off(fires):
    """D7's precondition, at the instant each enter-time transfer fires.

    If a dma_init routine were ever called from `tick:` instead of `enter:`,
    the transfer would fire with NMITIMEN=$81 and HDMAEN armed, and channel 0
    would be simultaneously bgm's active HDMA channel and the upload's GP-DMA
    channel — a real collision the allocator cannot see, because dma_init
    claims are exempt from mutual exclusion precisely on the strength of this
    precondition. That is what fails here.
    """
    bad = [
        (_names_of(fires, f["key"]), f)
        for f in fires["fires"]
        if _phase_of(fires, f["key"]) == "forced_blank"
        and (f["nmitimen"] != 0 or f["hdmaen"] != 0)
    ]
    assert not bad, (
        "dma_init transfers fired while NMI and/or HDMA were live, which voids "
        "D7's no-exclusivity justification:\n" + "\n".join(
            f"  {'/'.join(names)} at site ${f['site'][0]:02X}:"
            f"${f['site'][1]:04X}: NMITIMEN=${f['nmitimen']:02X} "
            f"HDMAEN=${f['hdmaen']:02X}"
            for names, f in bad[:8]))


# -- non-vacuity, PER CLAIM rather than per encoding ------------

def test_every_declared_dma_init_claim_has_a_firing_site(fires, decl):
    """Every declared enter-time upload has code that fires it.

    The static half of per-claim coverage. `symbol_map.json` says the claim
    exists and the allocator has proved things about the channel it occupies; if
    no `sta $420B` in any gated source names that claim's `ES_D_*_CH` symbol,
    the declaration describes a transfer that cannot happen — and the runtime
    half below cannot tell, because a claim sharing its encoding with two others
    still sees fires with "its" encoding. This is the exact case a later review
    falsified: suppressing sky_up's MDMAEN writes entirely left the old
    per-encoding test green (N4).
    """
    want = {c["name"] for sm in decl.values() for c in sm["dma_init"]}
    missing = sorted(n for n in want if not fires["sites"].get(n))
    assert not missing, (
        f"these dma_init claims are declared but no MDMAEN firing site in any "
        f"gated source names them: {missing}. Sites found: "
        f"{dict(fires['sites'])}")


def test_every_dma_init_firing_site_was_observed_firing(fires, decl):
    """Every firing site that exists actually ran, per site.

    The runtime half. For each dma_init encoding, count the DISTINCT code sites
    observed firing it and compare against the number of static sites belonging
    to the claims that share that encoding. Equality — not `>=` — because
    `>=` is satisfied by one claim firing twice while another never fires, which
    is the hole this pair closes.

    Counting sites rather than encodings is what makes this per-claim: race's
    font_up, car_up and sky_up all encode as ch0/DMAP $01/BBAD $18 and together
    own four sites (font 1, car 1, sky 2), so a claim whose site is jumped over
    drops the observed count below four even though its encoding keeps firing.
    """
    static = Counter()
    owners = defaultdict(set)
    for sm in decl.values():
        for c in sm["dma_init"]:
            key = (c["ch"], c["dmap"], c["bbad"])
            if c["name"] in owners[key]:
                continue                  # same claim declared in two scenes
            owners[key].add(c["name"])
            static[key] += fires["sites"].get(c["name"], 0)

    observed = defaultdict(set)
    for f in fires["fires"]:
        if _phase_of(fires, f["key"]) == "forced_blank":
            observed[f["key"]].add(f["site"])

    bad = []
    for key, n in sorted(static.items()):
        got = observed.get(key, set())
        if len(got) != n:
            bad.append((key, n, got))
    assert not bad, (
        "the number of distinct MDMAEN firing sites observed does not match "
        "the number the source contains, so at least one declared upload never "
        "ran:\n" + "\n".join(
            f"  ch{k[0]} DMAP ${k[1]:02X} BBAD ${k[2]:02X} "
            f"(claims {sorted(owners[k])}): {n} site(s) in the source, "
            f"{len(got)} observed "
            + str(sorted(f'${b:02X}:${p:04X}' for b, p in got))
            for k, n, got in bad))


def test_every_declared_dma_init_encoding_was_observed_firing(fires):
    """The weaker per-ENCODING check, kept because its failure is clearer.

    If a whole encoding never fires, the two tests above will also fail, but
    this one names the encoding directly, which is the faster read when an
    entire upload path is dead. Its NAME says encoding, because encoding is
    what it checks — the old name promised per-claim coverage it could not
    deliver.
    """
    want = {k for k, (_n, ph) in fires["known"].items() if ph == "forced_blank"}
    seen = {f["key"] for f in fires["fires"]}
    missing = want - seen
    assert not missing, (
        "these declared dma_init encodings never fired during the run, so the "
        "precondition was not actually checked for them: " + ", ".join(
            f"{'/'.join(_names_of(fires, k))} (ch{k[0]} DMAP ${k[1]:02X} "
            f"BBAD ${k[2]:02X})" for k in sorted(missing)))


def test_vblank_phase_transfers_were_observed_with_nmi_enabled(fires):
    """The discriminator check: the test can tell the two phases apart.

    A run in which NMI happened to be masked for every observed fire would
    satisfy the precondition test trivially. A VBlank-phase claim firing with
    NMITIMEN != 0 proves the sample really does span both regimes, so "NMI was
    off" above is a property of dma_init and not of the sampling window.
    """
    vb = [f for f in fires["fires"]
          if _phase_of(fires, f["key"]) in ("vblank", "active")]
    assert vb, "no vblank/active-phase transfer was observed at all"
    assert any(f["nmitimen"] != 0 for f in vb), (
        "every observed vblank-phase transfer fired with NMI masked — the "
        "sample never left the scene-switch window, so the forced_blank "
        "assertion is not discriminating between the phases")
