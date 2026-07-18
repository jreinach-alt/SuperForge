#!/usr/bin/env bash
# Build the split_h_matrix_demo -D variant ROMs (the generic `make
# split_h_matrix_demo` rule can't pass -D defines). Run from the MATERIALIZED kit
# root, AFTER `make split_h_matrix_demo` (so build/ exists).
#
#   split_h_matrix_demo_nomatrix.sfc  -DNO_MATRIX_SPLIT=1 : the M1 NON-VACUITY
#       control. The seam is compiled out — BOTH bands use camera A's scale, so a
#       SINGLE camera fills the screen and the two-camera period-ratio assertion
#       (M1) MUST FAIL (both periods small, no ~4x ratio).
#   split_h_matrix_demo_autodemo.sfc  -DAUTODEMO=1 : self-running. The bottom
#       band's camera scale sweeps on the frame counter (patched into the WRAM
#       HDMA tables each VBlank) to show the band is LIVE — for inspection.
set -euo pipefail
cd "$(dirname "$0")/../.."
INC="-I infrastructure/rom_template -I lib/macros -I engine -I templates/split_h_matrix_demo/assets"
CFG="infrastructure/rom_template/lorom_64k.cfg"
SRC="templates/split_h_matrix_demo/main.asm"
mkdir -p build

build_variant () {
    local def="$1" out="$2"
    ca65 --cpu 65816 $INC -D "$def" "$SRC" -o "build/$out.o"
    ld65 -C "$CFG" "build/$out.o" -o "build/$out.sfc"
    echo "built build/$out.sfc  ($def)"
}

build_variant NO_MATRIX_SPLIT=1 split_h_matrix_demo_nomatrix
build_variant AUTODEMO=1        split_h_matrix_demo_autodemo
