#!/usr/bin/env bash
# Build the split_v_fight -D variant ROMs (the generic make rule can't pass -D).
# Run from the MATERIALIZED kit root, AFTER `make split_v_fight`.
#
#   split_v_fight_autodemo.sfc  -DAUTODEMO=1 : self-running — the two fighters
#       march wall-to-wall THROUGH each other, swapping sides and back, so the
#       seamless separate/merge and the side-SWAP play out on their own (no controller).
#
#   The SEAMLESS proof is done with STATIC -DHOLD=n builds (freeze the swept
#   variable -> no capture-timing race). HOLD=n freezes the fighters symmetric at
#   +-n px about centre and lets `spread` ease to its fixed point:
#     split_v_fight_hold_merge.sfc  -DHOLD=20  : dx=40  -> spread settles at 0
#         (fully MERGED — must pixel-match the no-split reference below).
#     split_v_fight_hold_split.sfc  -DHOLD=100 : dx=200 -> spread settles at 36
#         (SPLIT — the beveled bar is visible, fighters in opposite halves).
#     split_v_fight_nowin.sfc  -DNOWIN=1 -DHOLD=20 : the no-split REFERENCE
#         (window off + BG3 off the main screen; one camera, no divider). The
#         hold_merge frame diffs to ~0 against this — the seamlessness proof.
#     split_v_fight_cross.sfc  -DHOLD=-100 : a CROSSED / swapped static state
#         (negative HOLD puts FX1 to the RIGHT of FX2 -> dx=200, split). Proves
#         the split follows a side-switch: blue (left fighter) in the LEFT half,
#         red (right fighter) in the RIGHT half — colours swapped, framing correct.
set -euo pipefail
INC="-I infrastructure/rom_template -I lib/macros -I engine -I templates/split_v_fight/assets"
CFG=infrastructure/rom_template/lorom_64k.cfg
SRC=templates/split_v_fight/main.asm
mkdir -p build

build_variant() {
    local name="$1"; shift
    ca65 --cpu 65816 $INC "$@" $SRC -o "build/$name.o"
    ld65 -C $CFG "build/$name.o" -o "build/$name.sfc"
    echo "built build/$name.sfc"
}

build_variant split_v_fight_autodemo   -D AUTODEMO=1
build_variant split_v_fight_hold_merge -D HOLD=20
build_variant split_v_fight_hold_split -D HOLD=100
build_variant split_v_fight_nowin      -D NOWIN=1 -D HOLD=20
build_variant split_v_fight_cross      -D HOLD=-100
