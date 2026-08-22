#!/usr/bin/env bash
# `make bare-check` — the local replacement for the push-triggered CI run.
#
# WHY THIS EXISTS. The push trigger came off first, and on 2026-08-22 the
# workflow file itself was deleted (docs/44 §6) — hosted minutes ran out
# repeatedly, a red run never reported back into the working session, and the
# failure mail was not worth what the runs bought. But a hosted run was not
# just a notification: it bought three properties that a local `make gates`
# structurally cannot have, and this script exists to buy them back.
#
#   1. BARE-RUNNER ISOLATION. A CI runner builds with no sibling checkouts on
#      disk, which is what keeps anything outside this repository from silently
#      becoming a build dependency. Reproduced here by running the whole gate
#      block inside a MOUNT NAMESPACE with an empty directory bound over every
#      path named in SF_REFERENCE_TREE, so those paths are unreachable for the
#      duration and cannot leak afterwards (a namespace dies with its process —
#      there is no restore step to forget). The list is EMPTY by default: this
#      repository builds with nothing beside it on disk, so on an ordinary
#      machine there is nothing to hide and the fresh clone alone carries the
#      property.
#
#   2. NO STALE TREE. A defect once slipped past three local runs in a row:
#      the no_literals channel rules broke the gated probe_vblank build, and
#      every local `make test` passed because a stale build/probe_vblank.sfc
#      made the target a no-op. Reproduced here by running in a FRESH CLONE,
#      which has no build/ at all.
#
#   3. A SECOND OBSERVER against "green here != green anywhere else".
#      Reproduced by
#      cloning: the clone contains ONLY COMMITTED CONTENT, so a tree with
#      uncommitted work is refused by name rather than quietly passing on
#      files no one else will ever have.
#
# WHAT IS NOT REPRODUCED — stated rather than implied. See docs/44.
#   - a genuinely different machine (this runs on the dev box)
#   - a genuinely absent toolchain (ca65/Mesen are reused; see "TOOLCHAIN")
#   - a different OS image
#   There is no longer any escape hatch behind this: the hosted workflow was
#   deleted on 2026-08-22, so nothing in this tree buys those three. When a
#   change's failure mode is "works here, not on a clean machine", build it on
#   a clean machine by hand and say so in the landing note.
#
# TOOLCHAIN. The clone runs its OWN tools/setup.sh, so the "does a fresh clone
# come up" path is exercised for real — but setup.sh is a VERIFY-THEN-INSTALL
# script, so on this box it finds ca65/ld65, Pillow, pytest and the already-built
# /tmp/Mesen2 core and installs nothing. That is deliberate: a ~10-minute Mesen
# rebuild per run makes the gate unusable, and an unusable gate gets skipped.
# The residue is that "no toolchain" is verified as "setup.sh's verification
# path passes", not as "it bootstrapped from nothing".
#
# USAGE
#   make bare-check                 # the gate
#   make bare-check XDIST=4         # more suite workers (default 2)
#   BARE_CHECK_ALLOW_DIRTY=1 ...    # skip the uncommitted-work refusal. ONLY
#                                   # for the falsification tests, which need to
#                                   # reach the gates with a planted tree.
#   BARE_CHECK_DIR=/path            # where to clone (default /tmp/superforge-bare-check)
#   BARE_CHECK_KEEP=1               # keep the clone for post-mortem
#   SF_REFERENCE_TREE=/path         # an optional reference tree to bind away
#                                   # for the run (colon-separate several).
#                                   # UNSET BY DEFAULT, and there is no default
#                                   # path: this repository builds with nothing
#                                   # beside it, so normally there is
#                                   # nothing to hide. Set it when a checkout
#                                   # that MIGHT satisfy an include path lives
#                                   # beside this one and you want the gate to
#                                   # prove the build never reached it.
#
# EXIT CODES
#   0  every gate green
#   1  a gate failed
#   2  refused before running anything (uncommitted work, or clone != tip)

set -uo pipefail

# --------------------------------------------------------------------------
# phase 2: the run itself, re-executed inside the mount namespace.
# Kept at the top so the namespace re-exec below is a plain `exec "$0" --inside`.
# --------------------------------------------------------------------------
if [ "${1:-}" = "--inside" ]; then
    CLONE="$2"
    XDIST="$3"
    PARTS="$CLONE/build/bare_check_parts"
    mkdir -p "$PARTS"

    cd "$CLONE" || exit 1

    # Every configured path must be EMPTY (the bind landed) or absent. A
    # non-empty one means the bind silently did not happen. With nothing
    # configured this passes trivially, which is correct: there was nothing
    # to hide, and the fresh clone is the whole isolation story.
    assert_isolated() {
        local rc=0 p
        local IFS=:
        for p in $SF_REFERENCE_TREE; do
            [ -n "$p" ] || continue
            [ -d "$p" ] || continue
            if [ -n "$(ls -A "$p" 2>/dev/null)" ]; then
                echo "bare-check: $p IS VISIBLE — isolation NOT held"
                rc=1
            fi
        done
        return $rc
    }

    step() {                    # step <name> <command...>
        local name="$1"; shift
        printf '\n=== bare-check: %s ===\n' "$name"
        "$@"
        local rc=$?
        printf '%s\t%s\n' "$name" "$rc" >> "$PARTS/steps.tsv"
        return $rc
    }

    overall=0

    # --- toolchain verification, from the clone's own script ---------------
    # Property 1. `|| true` on the step so a setup failure is REPORTED as a
    # failed step rather than aborting before the gates write any parts —
    # a bare-check that dies silently is worse than one that says which step died.
    step setup bash tools/setup.sh || overall=1

    # --- the gate block, in `make gates` order -----------------------------
    # `make gates` IS the ordered block (Makefile `gates:`), it writes
    # build/gates_summary.txt with a per-gate verdict, and it prints the ROM
    # md5s. Running it rather than re-listing its members here means a gate
    # added to `make gates` is picked up by bare-check automatically — the
    # opposite of the registration-list problem `make rail-registered` exists
    # for, where the same fact has to be repeated at N sites and rots at N-1.
    if [ "$overall" -eq 0 ]; then
        # BARE_CHECK_GATES exists for tests/test_bare_check.py, which plants
        # real violations and must see this pipeline go red WITHOUT paying the
        # ~8-minute gate block per plant. It is recorded in the artifact and
        # shouted in the verdict line, so a run that used it can never be
        # mistaken for a landing-gate run.
        step gates $BARE_CHECK_GATES XDIST="$XDIST" || overall=1
    else
        printf 'gates\tskipped\n' >> "$PARTS/steps.tsv"
    fi

    # --- the extra assertions the workflow used to carry -------------------
    # These lived in ci.yml's steps, NOT in `make gates`, and were restated
    # here so they would survive the workflow. They did: ci.yml was deleted on
    # 2026-08-22 and this is now the only place they run. Sizes first: a ROM
    # that links but comes out the wrong size is a mapping bug the md5 pin
    # cannot name.
    #
    # STATED GAP (docs/44 §6): this list is rail-scoped, and `make gates`'s
    # build list is not. Eight variant/control ROMs the block builds were
    # measured ONLY in ci.yml — svd_nowin, shd_autodemo, shp_autodemo,
    # rs_probe, sit_origin, sit_mistime, shg_nograd, shg_origin — so as of
    # 2026-08-22 they are measured nowhere. (`sh2-variants` is unnamed here
    # too, but it was never in ci.yml either — that one is older than this
    # change.) Do not quietly widen the list to "fix" it: which list is the
    # authority is the open question, and a silent widening answers it by
    # accident.
    # ...but only when the full block actually ran. A substituted gate block
    # (tests/test_bare_check.py) builds one target, so "microzero.sfc is not
    # 524288 bytes" would be true and meaningless — a gate that fails for a
    # reason it did not test is noise, and noise is how a gate gets ignored.
    if [ "$BARE_CHECK_GATES" != "make gates" ]; then
        printf 'rom-sizes\tskipped\n' >> "$PARTS/steps.tsv"
        printf 'probe-cpu-md5\tskipped\n' >> "$PARTS/steps.tsv"
        assert_isolated || exit 1
        printf 'isolated\t0\n' >> "$PARTS/steps.tsv"
        exit $overall
    fi

    sizes_rc=0
    for spec in toy:32768 microzero:524288 room:524288 breaker:524288 \
                shmup:524288 platformer:524288 split_v_fight:524288 \
                m7_dungeon:524288 split_h_2p_demo:524288 \
                mode7_explore:524288 platformer_stream:524288 \
                hud_game:524288 scroller:524288 camera_follow:524288 \
                maze:524288 jumper:524288 patrol:524288 sprite_game:524288 \
                stomper:524288 scroll_run:524288 \
                brawler:524288 split_h_matrix_demo:524288 \
                split_h_persp3_demo:524288 split_v_demo:524288 \
                split_v_seamtrial:524288 split_h_demo:524288 \
                split_h_persp_demo:524288 racer:524288 \
                mode7_chamber:524288 railshooter:524288 m7_oshoot:524288 \
                mode7_flight:524288 \
                rpg:524288 boss:524288 boss_saucer:524288 \
                meteor_event:524288 seam_irq_trial:524288 \
                split_h_irq_grad_demo:524288; do
        rom="${spec%%:*}"; want="${spec##*:}"
        if [ -f "build/$rom.sfc" ]; then
            got=$(stat -c%s "build/$rom.sfc")
        else
            got="(not built)"
        fi
        printf '%s\t%s\t%s\n' "$rom" "$want" "$got" >> "$PARTS/sizes.tsv"
        if [ "$got" != "$want" ]; then
            echo "bare-check: SIZE $rom.sfc expected $want, got $got"
            sizes_rc=1
        fi
    done
    printf 'rom-sizes\t%s\n' "$sizes_rc" >> "$PARTS/steps.tsv"
    [ "$sizes_rc" -eq 0 ] || overall=1

    # The vendored-reference integrity pin: the fastest single check that
    # vendor/probe_ref still assembles to the bytes it always has. This is the
    # isolation gate's sharpest edge — probe_cpu is built entirely from
    # vendored sources, with nothing outside this tree on disk.
    probe_rc=0
    if make build/probe_cpu.sfc >/dev/null 2>&1; then
        actual=$(md5sum build/probe_cpu.sfc | cut -d' ' -f1)
    else
        actual="(build failed)"
    fi
    expected=11e935608b4df193597b9db51d75294e
    printf 'probe_cpu\t%s\t%s\n' "$expected" "$actual" >> "$PARTS/probe.tsv"
    if [ "$actual" != "$expected" ]; then
        echo "bare-check: probe_cpu md5 drift — expected $expected, got $actual"
        probe_rc=1
    fi
    printf 'probe-cpu-md5\t%s\n' "$probe_rc" >> "$PARTS/steps.tsv"
    [ "$probe_rc" -eq 0 ] || overall=1

    # --- every configured path must have been unreachable -------------------
    # Asserted, not assumed: the isolation property is the whole point, and a
    # bind that silently did not happen would make this gate weaker than a CI
    # runner while claiming to be equivalent.
    if assert_isolated; then
        printf 'isolated\t0\n' >> "$PARTS/steps.tsv"
    else
        printf 'isolated\t1\n' >> "$PARTS/steps.tsv"
        overall=1
    fi

    exit $overall
fi

# --------------------------------------------------------------------------
# phase 1: refuse, clone, verify, then hand off to phase 2 in a namespace
# --------------------------------------------------------------------------
SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
REPO="$(cd "$(dirname "$SCRIPT")/.." && pwd)"
CLONE_ROOT="${BARE_CHECK_DIR:-/tmp/superforge-bare-check}"
CLONE="$CLONE_ROOT/repo"
XDIST="${XDIST:-2}"
SF_REFERENCE_TREE="${SF_REFERENCE_TREE:-}"
BARE_CHECK_GATES="${BARE_CHECK_GATES:-make gates}"
export SF_REFERENCE_TREE BARE_CHECK_GATES
REPORT="$REPO/build/bare_check.json"

cd "$REPO" || exit 2
mkdir -p "$REPO/build"

SHA="$(git rev-parse HEAD 2>/dev/null)"
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
T0=$(date +%s)

refuse() {                      # refuse <headline> [detail-line...]
    local reason="$1"; shift
    printf '\n================================================================\n'
    printf 'bare-check: REFUSED — %s\n' "$reason"
    printf '================================================================\n'
    local line
    for line in "$@"; do printf '  %s\n' "$line"; done
    python3 - "$REPORT" "$SHA" "$BRANCH" "$STARTED" "$reason" <<'PY'
import json, sys
path, sha, branch, started, reason = sys.argv[1:6]
json.dump({"schema": 1, "verdict": "REFUSED", "reason": reason,
           "sha": sha, "branch": branch, "started_utc": started},
          open(path, "w"), indent=2)
open(path, "a").write("\n")
PY
    printf '\nrecorded: %s\n' "$REPORT"
    exit 2
}

# --- the refusal that matters most ----------------------------------------
# A clone contains only COMMITTED content. If the tree is dirty, the thing this
# gate checked is not the thing you have, and saying so is more valuable than
# any verdict it could otherwise print.
DIRTY="$(git status --porcelain)"
if [ -n "$DIRTY" ] && [ "${BARE_CHECK_ALLOW_DIRTY:-0}" != "1" ]; then
    DIRTY_LINES=()
    while IFS= read -r l; do DIRTY_LINES+=("    $l"); done <<< "$DIRTY"
    refuse "YOUR CHANGES ARE NOT COMMITTED" \
        "bare-check clones the repo, so it can only ever see committed content." \
        "These paths are not in HEAD ($SHA) and would NOT be checked:" \
        "" "${DIRTY_LINES[@]}" "" \
        "Commit (and push) first, then re-run. There is no partial mode:" \
        "a green bare-check on a dirty tree would be a lie about what shipped." \
        "(BARE_CHECK_ALLOW_DIRTY=1 bypasses this — it exists for the" \
        " falsification tests, which must reach the gates with a planted tree.)"
fi

echo "bare-check: cloning $REPO @ $SHA"
rm -rf "$CLONE_ROOT"
mkdir -p "$CLONE_ROOT"
# --no-local is REQUIRED, not a preference. A local clone hardlinks the object
# store and does NOT copy .git/shallow, so cloning this repo (which is itself a
# shallow session clone) produced a tree whose HEAD was right and whose history
# was unreadable: `git rev-list HEAD` died with "Could not read <sha>". The git
# transport handles a shallow source correctly. Measured cost: ~4 s, 19 MB.
if ! git clone --quiet --no-local "$REPO" "$CLONE" 2>&1; then
    refuse "the clone failed" "git clone --no-local $REPO $CLONE returned non-zero"
fi

CLONE_SHA="$(git -C "$CLONE" rev-parse HEAD 2>/dev/null)"
if [ "$CLONE_SHA" != "$SHA" ]; then
    refuse "the clone is not at the tip" \
        "working repo HEAD: $SHA" \
        "clone HEAD:        $CLONE_SHA" \
        "The gate would have checked a different commit than the one you have."
fi
echo "bare-check: clone at $CLONE_SHA (verified == working tree HEAD)"

# --- run it, with any configured sibling paths bound away -----------------
# unshare -m needs privileges. When it is unavailable the gate still RUNS — it
# just records isolated:false, so the artifact never claims an isolation
# property it did not have. A silently-degraded gate is the failure mode this
# whole mechanism exists to prevent.
EMPTY="$CLONE_ROOT/empty"
mkdir -p "$EMPTY"

TO_HIDE=""
OLD_IFS="$IFS"; IFS=:
for p in $SF_REFERENCE_TREE; do
    [ -n "$p" ] && [ -d "$p" ] && TO_HIDE="$TO_HIDE $p"
done
IFS="$OLD_IFS"

ISOLATED=true
if [ -z "$TO_HIDE" ]; then
    # The default, and the ordinary case: nothing configured, or nothing
    # configured is present. The fresh clone is the whole isolation story.
    echo "bare-check: no sibling paths to hide — running in the fresh clone"
    "$SCRIPT" --inside "$CLONE" "$XDIST"
    RC=$?
elif unshare -m true 2>/dev/null; then
    echo "bare-check: hiding$TO_HIDE for the run (mount namespace)"
    binds=""
    for p in $TO_HIDE; do binds="$binds mount --bind '$EMPTY' '$p' &&"; done
    unshare -m --propagation private bash -c \
        "$binds exec '$SCRIPT' --inside '$CLONE' '$XDIST'"
    RC=$?
else
    ISOLATED=false
    echo "bare-check: WARNING — cannot unshare;$TO_HIDE stays VISIBLE."
    echo "            The isolation property will be recorded as NOT held."
    "$SCRIPT" --inside "$CLONE" "$XDIST"
    RC=$?
fi

T1=$(date +%s)

# --- the artifact ----------------------------------------------------------
# The replacement for "cite a CI run id": a recorded, quotable result naming the
# exact SHA it checked. docs/branching.md's landing rule points at this file.
python3 - "$REPORT" "$CLONE" "$SHA" "$BRANCH" "$STARTED" "$((T1 - T0))" \
         "$RC" "$ISOLATED" "$XDIST" "$SF_REFERENCE_TREE" "$BARE_CHECK_GATES" <<'PY'
import json, pathlib, re, subprocess, sys

(report, clone, sha, branch, started, elapsed, rc,
 isolated, xdist, isolate_paths, gate_cmd) = sys.argv[1:12]
clone = pathlib.Path(clone)
parts = clone / "build" / "bare_check_parts"

def lines(name):
    p = parts / name
    return p.read_text().splitlines() if p.exists() else []

steps = {}
for ln in lines("steps.tsv"):
    if "\t" in ln:
        k, v = ln.split("\t", 1)
        steps[k] = ("pass" if v == "0" else "skipped" if v == "skipped"
                    else f"FAIL(exit {v})")

# `make gates` writes its own per-gate table; parse it so the artifact names
# the gate that failed rather than only "gates failed".
gates = {}
gs = clone / "build" / "gates_summary.txt"
if gs.exists():
    for ln in gs.read_text().splitlines():
        m = re.match(r"\s*(\S+)\s+(ok|FAILED|skipped)\b", ln)
        if m:
            gates[m.group(1)] = "pass" if m.group(2) == "ok" else m.group(2)

sizes = {}
for ln in lines("sizes.tsv"):
    f = ln.split("\t")
    if len(f) == 3:
        sizes[f[0]] = {"expected": f[1], "actual": f[2],
                       "ok": f[1] == f[2]}

probe = {}
for ln in lines("probe.tsv"):
    f = ln.split("\t")
    if len(f) == 3:
        probe = {"expected": f[1], "actual": f[2], "ok": f[1] == f[2]}

md5s = {}
for rom in ("toy", "microzero", "room", "breaker", "shmup", "platformer",
            "split_v_fight", "m7_dungeon", "split_h_2p_demo",
            "mode7_explore", "platformer_stream", "hud_game", "scroller",
            "camera_follow", "maze", "jumper", "patrol", "sprite_game",
            "stomper", "scroll_run", "brawler",
            "split_h_matrix_demo", "split_h_persp3_demo", "split_v_demo",
            "split_v_seamtrial", "split_h_demo", "split_h_persp_demo",
            "racer", "mode7_chamber", "railshooter", "m7_oshoot", "mode7_flight", "rpg",
            "boss", "boss_saucer", "meteor_event", "seam_irq_trial",
            "split_h_irq_grad_demo"):
    p = clone / "build" / f"{rom}.sfc"
    if p.exists():
        md5s[rom] = subprocess.run(["md5sum", str(p)], capture_output=True,
                                   text=True).stdout.split()[0]
    else:
        md5s[rom] = None

# The suite summary line pytest prints last ("N passed, M skipped in T s").
suite = None
log = clone / "build" / "pytest.log"
if log.exists():
    for ln in reversed(log.read_text(errors="replace").splitlines()):
        if re.search(r"\b\d+ (passed|failed|error)", ln):
            suite = ln.strip()
            break

doc = {
    "schema": 1,
    "verdict": "GREEN" if rc == "0" else "RED",
    "exit_code": int(rc),
    "sha": sha,
    "branch": branch,
    "started_utc": started,
    "elapsed_s": int(elapsed),
    "xdist": int(xdist),
    "gate_command": gate_cmd,
    "isolation": {
        # Named honestly: what this run actually held, not what a hosted
        # runner would hold.
        "fresh_clone": True,
        "isolated": isolated == "true",
        "isolate_paths": [p for p in isolate_paths.split(":") if p],
        "not_reproduced": ["different machine", "absent toolchain",
                           "different OS image"],
    },
    "steps": steps,
    "gates": gates,
    "rom_sizes": sizes,
    "rom_md5": md5s,
    "probe_cpu_md5": probe,
    "suite": suite,
}
pathlib.Path(report).write_text(json.dumps(doc, indent=2) + "\n")

print()
print("=" * 64)
if gate_cmd != "make gates":
    print(f"bare-check: *** NOT A LANDING-GATE RUN *** gate command was "
          f"{gate_cmd!r}, not 'make gates'")
bad = [k for k, v in {**steps, **gates}.items() if v.startswith("FAIL")]
if rc == "0":
    hid = [p for p in isolate_paths.split(":") if p]
    iso = ("no sibling paths configured" if not hid else
           f"{len(hid)} sibling path(s) "
           f"{'hidden' if isolated == 'true' else 'VISIBLE'}")
    print(f"bare-check: GREEN — {sha[:12]} on a fresh clone, {iso}, {elapsed}s")
else:
    print(f"bare-check: RED — {sha[:12]}: "
          f"{', '.join(bad) if bad else 'see the log above'} ({elapsed}s)")
if suite:
    print(f"  suite: {suite}")
print(f"  recorded: {report}")
print("=" * 64)
PY

if [ "${BARE_CHECK_KEEP:-0}" != "1" ] && [ "$RC" -eq 0 ]; then
    rm -rf "$CLONE_ROOT"
else
    [ "$RC" -eq 0 ] || echo "bare-check: clone kept for post-mortem at $CLONE"
fi

exit "$RC"
