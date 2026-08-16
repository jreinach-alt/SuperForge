#!/usr/bin/env bash
# SuperForge's silent-corruption gates, run automatically after an edit (PostToolUse
# hook). It runs THIS repo's two sub-second gates and REPORTS rather than
# blocks (see BLOCK vs REPORT below).
#
# WHY A HOOK AT ALL. Both gates it runs are sub-second and both catch classes
# whose symptom is far from the cause:
#
#   width-check  the silent-BRK class. A missing/wrong .a8/.a16 assembles a
#                stray $00 that the CPU executes as BRK. No assembler warning,
#                a ROM that links, and a failure that surfaces as corrupted
#                state somewhere else entirely. CLAUDE.md rule 6; baseline ZERO.
#   time-check   the load-sensitivity class. A wall-clock wait in a test makes
#                it pass on a quiet box and flake on a busy one, which reads as
#                a defect in whatever the test touches. CLAUDE.md rule 2 /
#                docs/45; baseline EMPTY.
#
# Catching either at edit time costs ~1.4 s. Catching it at `make gates` costs
# a context switch; catching it after a push costs a landing.
#
# BLOCK vs REPORT, and the choice is deliberate. The obvious design exits 2 to
# BLOCK the agent until the finding is fixed. This one prints the finding and
# exits 0. The reason is that a blocking hook fires
# on every intermediate edit, including the half-written state between two
# edits of a pair that are only correct together — and a gate that punishes
# work-in-progress gets disabled, which costs more than it saves. The gates are
# still HARD gates where they matter: `make gates`, the pre-push hook
# (`tools/git-hooks/pre-push` runs width-check + time-check among the four) and
# `make bare-check`. This hook is an early WARNING on the same two, not a
# second authority.
#
# SAFE-NO-OP everywhere it cannot run: no Makefile, no such target, or the
# gate's own tool missing. It must never be the reason a session cannot work in
# a partial checkout.
set -uo pipefail   # NOTE: no -e — each gate's exit code is inspected explicitly.

# The hook is invoked from the repo root by the harness; be explicit anyway, so
# a cwd that drifted does not silently turn this into a no-op.
cd "$(dirname "${BASH_SOURCE[0]}")/../.." 2>/dev/null || exit 0
[ -f Makefile ] || exit 0

input="$(cat 2>/dev/null || true)"

found=0

run_gate() {   # $1 = make target, $2 = the one-line "what this means"
  grep -q "^$1:" Makefile 2>/dev/null || return 0
  local out rc
  out=$(make "$1" 2>&1); rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "" >&2
    echo "  $1 FAILED — $2" >&2
    echo "$out" | tail -25 >&2
    found=1
  fi
}

# --- 65816 sources: the width gate -----------------------------------------
# .asm and .inc only. An .inc is included INTO an .asm, so a macro's sep/rep
# contract is a width finding in every file that expands it.
case "$input" in
  *.asm*|*.inc*)
    run_gate "width-check" \
      "a width-tracking finding. A bare .a8/.a16 that disagrees with an arrival is a finding, not a pass (CLAUDE.md rule 6). Baseline is ZERO — keep it there."
    ;;
esac

# --- tests and tools: the time-coupling gate --------------------------------
# Scoped to what the gate itself scans (tests/ + tools/), so an engine-only
# edit does not pay for it.
case "$input" in
  *tests/*.py*|*tools/*.py*|*vendor/*.py*|*conftest.py*)
    run_gate "time-check" \
      "a NEW wall-clock coupling in tests/ or tools/. Wait in EMULATED frames (wait_frames / wait_until / Machine.advance); when the PICTURE is the assertion, land on an absolute frame (boot_to_frame). Override is '# WALL-CLOCK: ok — <reason>' and the reason is REQUIRED. docs/45."
    ;;
esac

if [ "$found" -ne 0 ]; then
  echo "" >&2
  echo "  ^ found at edit time, NOT blocking. These are hard gates in" >&2
  echo "    'make gates', the pre-push hook and 'make bare-check' — fix it" >&2
  echo "    now rather than at the landing." >&2
fi

exit 0
