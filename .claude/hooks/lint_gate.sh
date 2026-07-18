#!/usr/bin/env bash
# Silent-corruption + clean-room gates, run automatically after edits (PostToolUse
# hook). Blocks (exit 2) on a new width-tracking / DP-allocation finding (the
# silent-BRK / silent-collision classes) OR a clean-room finding (a retail-name
# tripwire hit or an opaque/unattributed asset) so the agent fixes it immediately
# instead of letting it reach a commit/publish.
#
# SAFE-NO-OP until the `make` targets exist: this folder is authored before the
# engine/toolchain are copied in (B1), so each gate only fires once its target is
# present in the Makefile (run_gate guards on target presence). Pre-B1, or for an
# edit that touches none of the watched file classes, it exits 0 and does nothing.
set -uo pipefail   # NOTE: no -e — we inspect each gate's exit code explicitly.

input="$(cat 2>/dev/null || true)"

fail=0
run_gate() {  # $1 = make target, $2 = human message; SAFE-NO-OP if target absent
  if grep -q "^$1:" Makefile 2>/dev/null; then
    local out
    out=$(make "$1" 2>&1)
    if [ $? -ne 0 ]; then
      echo "$2" >&2
      echo "$out" | tail -25 >&2
      fail=1
    fi
  fi
}

# --- Width / DP gates: only on asm/inc edits (the silent-corruption classes). ---
case "$input" in
  *.asm*|*.inc*)
    run_gate "width-check" "width-check failed — a CPU 8/16-bit width-tracking finding. Fix it before continuing (AGENTS.md → Rigor: width discipline)."
    run_gate "zp-check"    "zp-check failed — a direct-page allocation collision. Resolve it before continuing."
    ;;
esac

# --- Clean-room gates: on any edit that could touch provenance — assets, data
# tables, the manifest, NOTICE/THIRDPARTY, docs, or the gate inputs. Previously
# the clean-room gate existed but NEVER RAN (the gap the recovery-gate closed);
# wiring it here catches leaks at edit time, not just at publish. provenance runs
# --no-regen here (fast coverage + attribution-chain check; the full byte-diff
# regen runs in `make check` / CI). Both SAFE-NO-OP if the targets are absent.
case "$input" in
  *.asm*|*.inc*|*.bin*|*.png*|*.zip*|*.toml*|*NOTICE*|*THIRDPARTY*|*.md*|*cleanroom_allow*)
    run_gate "cleanroom-check" "cleanroom-check failed — a retail/company/lineage name tripwire hit (committed text or zip-internal). Review the hit; if it is legitimate mechanism language, add a REVIEWED entry to tools/cleanroom_allow.txt (see docs/cleanroom_policy.md)."
    if grep -q "^provenance-check:" Makefile 2>/dev/null; then
      out=$(make provenance-check PROVENANCE_FLAGS=--no-regen 2>&1)
      if [ $? -ne 0 ]; then
        echo "provenance-check failed — an opaque/unregistered asset blob or a broken third-party attribution chain. Register it in tools/provenance_manifest.toml or fix NOTICE (see docs/cleanroom_policy.md)." >&2
        echo "$out" | tail -25 >&2
        fail=1
      fi
    fi
    ;;
esac

[ "$fail" -eq 0 ] && exit 0 || exit 2
