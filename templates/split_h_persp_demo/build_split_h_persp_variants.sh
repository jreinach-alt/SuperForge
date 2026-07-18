#!/usr/bin/env bash
# Build the split_h_persp_demo -D variant ROMs (the generic `make
# split_h_persp_demo` rule can't pass -D defines). Run from the MATERIALIZED kit
# root, AFTER `make split_h_persp_demo` (so build/ exists).
#
#   split_h_persp_demo_noseam.sfc  -DNO_SEAM : P4 NON-VACUITY. Skip the band-2
#       splice so BOTH bands render camera A -> the "two bands differ" (P1) FAILS.
#   split_h_persp_demo_latch.sfc   -DLATCH_VIOLATION : free-running latch-
#       violation demo (camera A rotating). NOT the P5 comparison build — camera
#       A's rotation alone moves the jitter metric, confounding a comparison
#       against a frozen baseline (PR #223 review M3).
#   split_h_persp_demo_stilllatch.sfc -DFREEZE -DHOLD_B -DLATCH_VIOLATION : the
#       P5 negative-control build. Both cameras frozen + the code-side write-
#       twice to a shared-latch register during active display -> the floor
#       TEARS vs the frozen clean `still` build on the SAME jitter metric —
#       a frozen-vs-frozen comparison that attributes the tear to the latch
#       violation, not to scene motion.
#   split_h_persp_demo_holdb.sfc   -DHOLD_B : camera A auto-rotates, camera B held
#       at pose 0 -> P1 camera-A-independent (TOP band changes, BOTTOM constant).
#   split_h_persp_demo_freeze.sfc  -DFREEZE : camera A frozen, camera B zoom-loops
#       -> P1 camera-B-independent (TOP band constant, BOTTOM changes).
#   split_h_persp_demo_still.sfc   -DFREEZE -DHOLD_B : both cameras static, but the
#       double buffer still flips + the splice re-applies every frame -> the P3
#       temporal-stability POSITIVE build (band-2 identical across frames) and the
#       deterministic build for the seam / clean / structural tests.
#   split_h_persp_demo_stillnoseam.sfc -DFREEZE -DHOLD_B -DNO_SEAM : camera A
#       everywhere AND frozen -> the deterministic camera-A baseline the P1
#       distinctness assertion compares camera B (the still build) against,
#       and P2's noseam control (the seam-pair metric must go quiet).
#   split_h_persp_demo_stillfixed.sfc  -DFREEZE -DHOLD_B -DFIXED_BUFFER_SPLICE :
#       the P3 NEGATIVE control. Same static scene, but the splice targets the
#       FIXED buffer 0 (ignoring pv_buffer) -> the 30 Hz double-buffer desync
#       flicker returns -> the temporal-stability assertion MUST FAIL.
set -euo pipefail
cd "$(dirname "$0")/../.."
INC="-I infrastructure/rom_template -I lib/macros -I engine -I templates/split_h_persp_demo/assets"
CFG="infrastructure/rom_template/lorom_64k.cfg"
SRC="templates/split_h_persp_demo/main.asm"
mkdir -p build

build_variant () {
    local out="$1"; shift
    local defs=()
    local d
    for d in "$@"; do defs+=(-D "$d"); done
    ca65 --cpu 65816 $INC "${defs[@]}" "$SRC" -o "build/$out.o"
    ld65 -C "$CFG" "build/$out.o" -o "build/$out.sfc"
    echo "built build/$out.sfc  ($*)"
}

build_variant split_h_persp_demo_noseam     NO_SEAM=1
build_variant split_h_persp_demo_stillnoseam FREEZE=1 HOLD_B=1 NO_SEAM=1
build_variant split_h_persp_demo_latch      LATCH_VIOLATION=1
build_variant split_h_persp_demo_stilllatch FREEZE=1 HOLD_B=1 LATCH_VIOLATION=1
build_variant split_h_persp_demo_holdb      HOLD_B=1
build_variant split_h_persp_demo_freeze     FREEZE=1
build_variant split_h_persp_demo_still      FREEZE=1 HOLD_B=1
build_variant split_h_persp_demo_stillfixed FREEZE=1 HOLD_B=1 FIXED_BUFFER_SPLICE=1
#   split_h_persp_demo_stillsame.sfc  -DFREEZE -DHOLD_B -DSAME_CENTER : the C1
#       NON-VACUITY control. Camera B's per-band ORIGIN (M7X/M7Y centre + M7HOFS/
#       M7VOFS scroll) is folded onto camera A's, via the SAME CH2/CH3 splice
#       channels -> band-2 samples camera A's world region (only the scale/angle
#       matrix differs) -> the C1 "band-2 is a different-coloured world region"
#       assertion FAILS. Proves C1 measures WORLD POSITION, not the channel.
build_variant split_h_persp_demo_stillsame  FREEZE=1 HOLD_B=1 SAME_CENTER=1
#   split_h_persp_demo_sky.sfc  -DSKY_HORIZON : ITEM B horizon knob. A TM ($212C)
#       HDMA band turns the Mode-7 floor OFF for lines 0..SKY_H-1 so the CGRAM[0]
#       backdrop shows as a SKY band above the horizon (vs the default floor-to-
#       edge). split_h_persp_demo_stillsky adds -DFREEZE -DHOLD_B for a
#       deterministic still frame the sky/floor framebuffer test samples.
build_variant split_h_persp_demo_sky        SKY_HORIZON=1
build_variant split_h_persp_demo_stillsky   FREEZE=1 HOLD_B=1 SKY_HORIZON=1
