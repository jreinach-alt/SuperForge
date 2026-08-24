"""The frame-assumption lint's own tests — tools/tick_lint.py.

A gate nobody has tried to break is exactly the indirect-evidence trap
CLAUDE.md rule 2 warns about, so every check here runs against a
DELIBERATELY-VIOLATING fixture under tests/fixtures/tick_lint/ and against a
clean control. Three shapes matter most:

  * a violation must be REFUSED (the gate has teeth),
  * a BARE `TICK: ok` must itself be refused (the stamp is not the reason),
  * an override must bind exactly ONE site. This tree declares its rates in
    tight runs, so the superseded three-line window silenced neighbours whose
    reason was written for the word next door; `binding_state.toml` and
    `override_binding.asm` carry both shapes, and each fixture site is
    checked to have been inside that window so the tests fail the day they
    stop being regressions,
  * the two rules that separate a UNIT from a WORD must hold: `EDGE = 2
    ; frame line` is a border and `ROLL_FIX = 8 ; the 8.8 fraction width` is
    a shift, and neither is a clock. Those two false positives are why the
    equate check uses a tighter vocabulary than the state check, and if that
    ever regresses the baseline fills with noise and the gate stops being
    read.

The last group runs the gate against the LIVE tree through the real
`make tick-check` recipe, so a baseline that drifts away from the tree is a
red here rather than a surprise later. It also pins the reconciliation
`docs/96` §3 reports: the state check reproduces `docs/95` §5.2's 135
exactly, and the 27 rails with it.
"""
import json
import subprocess
import sys
from pathlib import Path

SUPERFORGE = Path(__file__).resolve().parent.parent
FIX = SUPERFORGE / "tests" / "fixtures" / "tick_lint"
sys.path.insert(0, str(SUPERFORGE / "tools"))

import tick_lint as TL  # noqa: E402


def rules(name):
    return [f.rule for f in TL.lint_file(str(FIX / name))]


def lines_for(name, rule):
    return [f.line for f in TL.lint_file(str(FIX / name)) if f.rule == rule]


# --- the checks have teeth --------------------------------------------------

def test_clean_state_is_clean():
    assert rules("clean_state.toml") == []


def test_declared_frame_state_is_refused():
    # i-frames, an animation clock, an 8.8 rate, and a "this frame's" step.
    assert lines_for("frame_state.toml", "tick-state") == [3, 5, 7, 9, 10, 20, 23]


def test_bare_companion_declaration_inherits_the_unit():
    """`stepy` (line 10) has NO comment of its own — it shares `stepx`'s.
    It is exactly as frame-coupled, and the three of these in the live tree
    are the whole difference between docs/95's 135 and the 132 its own
    stated rule mechanises to."""
    assert 10 in lines_for("frame_state.toml", "tick-state")


def test_per_frame_routine_is_refused_by_name():
    assert lines_for("frame_engine.asm", "tick-routine") == [7]


def test_frame_unit_equates_are_refused():
    # MXL_STEP_FRAMES (by name) and ROLL_PEAK_CAP (`4.0 px/frame`, by unit).
    assert lines_for("frame_engine.asm", "tick-constant") == [2, 3]


def test_a_frame_that_is_a_border_is_not_a_clock():
    """`EDGE = 2  ; frame line` and `ROLL_FIX = 8  ; the 8.8 fraction width`
    are the two false positives the loose state vocabulary produced. The
    equate check must NOT take either."""
    assert 4 not in lines_for("frame_engine.asm", "tick-constant")
    assert 5 not in lines_for("frame_engine.asm", "tick-constant")


def test_a_routine_that_merely_runs_each_frame_is_not_a_clock():
    """`obj_place` says "called once per frame" in its header and does not
    COUNT in frames. A doc-phrase rule swept in 45 of these; the name rule
    does not."""
    assert 10 not in lines_for("frame_engine.asm", "tick-routine")


def test_ntsc_frame_constant_and_frame_ntsc_read_are_refused():
    assert lines_for("frame_substrate.py", "tick-substrate") == [2, 3, 5]


# --- the override convention ------------------------------------------------

def test_a_reasoned_override_suppresses():
    assert 13 not in lines_for("frame_state.toml", "tick-state")
    # `ok_step:` (line 13) with its reason on the indented line beneath it.
    assert 13 not in lines_for("frame_engine.asm", "tick-routine")


def _within_old_window(name, line, window=3):
    """Would the SUPERSEDED three-line window have silenced this site? The
    binding tests below are only regression fixtures if the answer is yes, so
    the old rule is re-derived here rather than asserted from memory."""
    lines = (FIX / name).read_text().splitlines()
    return any(TL.RE_TICK_OK.search(lines[i])
               for i in range(max(0, line - 1 - window),
                              min(len(lines), line + window)))


def test_an_override_binds_the_declaration_it_sits_under():
    """The state.toml shape: the reason is written on the indented lines
    beneath the word it is about, so it binds THAT word and no other."""
    assert TL.override_anchor(
        (FIX / "binding_state.toml").read_text().splitlines(), 6) == 5
    for site in (5, 7, 9, 15, 18):
        assert site not in lines_for("binding_state.toml", "tick-state")


def test_an_override_no_longer_silences_the_declaration_beside_it():
    """`hurt` sits one line under `tse_acc`'s reason and `neighbour` three
    lines under `near`'s. Both were inside the old window and neither reason
    was written for them; both are counted now."""
    got = lines_for("binding_state.toml", "tick-state")
    assert got == [11, 22]
    for site in got:
        assert _within_old_window("binding_state.toml", site), \
            f"line {site} is not a regression fixture — the old window " \
            f"would not have silenced it either"


def test_a_column_zero_block_heads_one_declaration_and_does_not_reach_back():
    """The assembly shape: a derivation block above the equate it derives.
    It binds the FIRST declaration below it — not the second (`PATROL_BASE`),
    and not the one above it (`MO_LIFE_FRAMES`)."""
    lines = (FIX / "override_binding.asm").read_text().splitlines()
    assert TL.override_anchor(lines, 3) == 4      # heads TURN_BASE
    assert TL.override_anchor(lines, 9) == 10     # heads MO_LIFE_PAL
    got = lines_for("override_binding.asm", "tick-constant")
    assert got == [5, 7]
    for site in got:
        assert _within_old_window("override_binding.asm", site)


def test_one_override_binds_at_most_one_site():
    """The property the whole binding exists for, stated directly: no line
    may be claimed by two different stamps, and no stamp may claim two."""
    for name in ("binding_state.toml", "override_binding.asm",
                 "frame_state.toml", "frame_engine.asm"):
        lines = (FIX / name).read_text().splitlines()
        anchors = [TL.override_anchor(lines, i + 1)
                   for i, l in enumerate(lines) if TL.RE_TICK_OK.search(l)]
        assert len(anchors) == len(set(anchors)), name


def test_a_bare_override_is_itself_a_finding():
    got = TL.lint_file(str(FIX / "frame_state.toml"))
    bare = [f for f in got if f.rule == "bare-override"]
    assert [f.line for f in bare] == [24]
    # and it does NOT suppress the site it is stamped on
    assert 23 in lines_for("frame_state.toml", "tick-state")


# --- the live tree ----------------------------------------------------------

def test_make_tick_check_is_clean():
    r = subprocess.run(["make", "tick-check"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 NEW finding(s)" in r.stdout


def _live_findings():
    r = subprocess.run(
        [sys.executable, str(SUPERFORGE / "tools" / "tick_lint.py"),
         "engine", "game", "tools", "allocator", "tests", "--json"],
        cwd=SUPERFORGE, capture_output=True, text=True)
    return json.loads(r.stdout)


def _baseline():
    return json.loads(
        (SUPERFORGE / "reports" / "tick_lint_baseline.json").read_text())


def test_baseline_matches_the_tree_exactly():
    """The baseline must be neither stale nor padded: every entry in it must
    still be a live finding. A baseline with dead entries is how a gate's
    population quietly stops meaning anything.

    Compared on the CONTENT key, which is what the baseline is held by."""
    live = {TL.baseline_key(f) for f in _live_findings()}
    stale = {TL.baseline_key(b) for b in _baseline()} - live
    assert not stale, f"baseline entries that are no longer findings: {stale}"


# --- the baseline is keyed by content, not by line --------------------------

def test_a_baseline_entry_carries_no_line_number():
    """A line a reader never checks is a line that rots. The entry names its
    SITE instead, which greps — and cannot go stale when the file moves."""
    for b in _baseline():
        assert "line" not in b, b
        assert b.get("site"), f"entry with no site: {b}"
        assert isinstance(b.get("ordinal"), int), b


def test_every_finding_names_a_site():
    """A finding with no site would key as (file, rule, '', 0) and collapse
    with every other siteless finding of its rule in that file — a silent
    suppression. Every check must name what it found."""
    for f in _live_findings():
        assert f["site"], f


def test_the_baseline_key_is_unique_per_entry():
    """`ordinal` exists so a file naming the same site twice keeps two
    entries. If two live findings ever shared a key, the baseline would hold
    one and silence both."""
    live = _live_findings()
    keys = [TL.baseline_key(f) for f in live]
    assert len(set(keys)) == len(keys), "colliding baseline keys"


def test_a_pure_line_shift_is_not_a_finding(tmp_path):
    """The property the re-key exists for, stated directly.

    Insert a comment line ABOVE a finding and its line number moves. Under
    the superseded (file, line, rule) key that produced a phantom NEW finding
    for a site nobody touched; under the content key the entry matches where
    it moved to, and only a genuinely NEW site is new."""
    src = FIX / "frame_engine.asm"
    body = src.read_text().splitlines()
    before = TL.number_sites(TL.lint_file(str(src)))
    keys_before = {TL.baseline_key(f) for f in before}
    lines_before = {(f.rule, f.line) for f in before}

    shifted = tmp_path / "frame_engine.asm"
    shifted.write_text("\n".join(["; a new header line", ""] + body) + "\n")
    after = TL.number_sites(TL.lint_file(str(shifted)))
    # Same sites, all of them moved down two lines.
    assert {(f.rule, f.line) for f in after} == {
        (r, ln + 2) for (r, ln) in lines_before}
    # ...and the same content keys, once the path is normalised away.
    keys_after = {(src.name, r, s, o) for (_f, r, s, o) in
                  (TL.baseline_key(f) for f in after)}
    assert keys_after == {(src.name, r, s, o) for (_f, r, s, o) in keys_before}


def test_a_genuinely_new_site_still_is_new(tmp_path):
    """The other direction: the key must not be so loose that a new site
    lands on an existing entry. A second equate with the same shape but a
    different name is a key the baseline does not hold."""
    src = FIX / "frame_engine.asm"
    before = {TL.baseline_key(f) for f in TL.lint_file(str(src))}
    grown = tmp_path / "frame_engine.asm"
    grown.write_text(src.read_text() + "NEW_DELAY_FRAMES = 9\n")
    after = {TL.baseline_key(f) for f in TL.lint_file(str(grown))}
    new = {(r, s, o) for (_f, r, s, o) in after} - {
        (r, s, o) for (_f, r, s, o) in before}
    assert new == {("tick-constant", "NEW_DELAY_FRAMES", 0)}


def test_a_repeat_of_the_same_site_is_new_by_ordinal(tmp_path):
    """`ordinal` is what stops a run of identical sites absorbing an addition.
    A file already holding N of one site holds ordinals 0..N-1; the N+1th is
    a key nobody held."""
    src = FIX / "frame_substrate.py"
    before = {TL.baseline_key(f) for f in TL.lint_file(str(src))}
    grown = tmp_path / "frame_substrate.py"
    extra = "EXTRA = 357368\n"  # TICK: ok — this literal is the lint's own test INPUT, written into a tmp file so there is a repeat of an existing site to find; nothing here is clocked by it
    grown.write_text(src.read_text() + extra)
    after = {TL.baseline_key(f) for f in TL.lint_file(str(grown))}
    new = {(r, s, o) for (_f, r, s, o) in after} - {
        (r, s, o) for (_f, r, s, o) in before}
    assert len(new) == 1
    (rule, site, ordinal), = new
    assert rule == "tick-substrate" and ordinal == max(
        o for (_f, r, s, o) in before if r == "tick-substrate"
        and s == site) + 1


def test_a_superseded_baseline_is_refused_not_silently_ignored(tmp_path):
    """A baseline in the old (file, line, rule) shape suppresses NOTHING, so
    every held site reads as new and the tree looks broken. It must be
    refused by name, with the regeneration command."""
    stale = tmp_path / "old_shape.json"
    stale.write_text(json.dumps(
        [{"file": "engine/x.asm", "line": 3, "rule": "tick-routine",
          "message": "m", "severity": "error"}]))
    r = subprocess.run(
        [sys.executable, str(SUPERFORGE / "tools" / "tick_lint.py"),
         "engine", "--baseline", str(stale)],
        cwd=SUPERFORGE, capture_output=True, text=True)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "superseded" in r.stderr and "--write-baseline" in r.stderr


def test_state_check_reproduces_docs95_135_across_27_rails():
    """docs/95 §5.2 reports 135 declared frame-unit words across 27 of the 37
    rails. That is the number this gate exists to bound, so it is pinned:
    if a rail gains one, this fails and somebody decides in front of a
    reviewer."""
    base = json.loads(
        (SUPERFORGE / "reports" / "tick_lint_baseline.json").read_text())
    st = [b for b in base if b["rule"] == "tick-state"]
    assert len(st) == 135
    assert len({b["file"] for b in st}) == 27
