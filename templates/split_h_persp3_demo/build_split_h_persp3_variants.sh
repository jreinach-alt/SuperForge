#!/usr/bin/env bash
# Build the split_h_persp3_demo -D variant ROMs (the generic `make
# split_h_persp3_demo` rule can't pass -D defines). Run from the MATERIALIZED kit
# root, AFTER `make split_h_persp3_demo` (so build/ exists).
#
#   split_h_persp3_demo_onecam.sfc  -DONE_CAM : C1 NON-VACUITY control. All three
#       bands use camera A's scale -> a SINGLE uniform camera fills the screen,
#       the "three distinct camera periods" assertion (C1) MUST FAIL.
set -euo pipefail
cd "$(dirname "$0")/../.."
INC="-I infrastructure/rom_template -I lib/macros -I engine -I templates/split_h_persp3_demo/assets"
CFG="infrastructure/rom_template/lorom_64k.cfg"
SRC="templates/split_h_persp3_demo/main.asm"
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

build_variant split_h_persp3_demo_onecam ONE_CAM=1
