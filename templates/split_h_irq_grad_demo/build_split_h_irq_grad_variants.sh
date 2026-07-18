#!/usr/bin/env bash
# build_split_h_irq_grad_variants.sh — the -D variant ROMs the test suite drives.
# (The generic make rule can't pass -D defines; mirrors the 2p rail's script.)
set -euo pipefail
cd "$(dirname "$0")/../.."

SRC=templates/split_h_irq_grad_demo/main.asm
INC="-I infrastructure/rom_template -I lib/macros -I engine -I templates/split_h_irq_grad_demo/assets"
CFG=infrastructure/rom_template/lorom_64k.cfg

build() {  # build <suffix> <defines...>
    local out="build/split_h_irq_grad_demo$1"; shift
    local defs=()
    for d in "$@"; do defs+=("-D$d"); done
    ca65 --cpu 65816 $INC "${defs[@]:+${defs[@]}}" "$SRC" -o "$out.o"
    ld65 -C "$CFG" "$out.o" -o "$out.sfc"
    echo "built $out.sfc  ($*)"
}

build _freeze    FREEZE=1                        # stills: gradient test + owner render
build _fznograd  FREEZE=1 NO_GRAD=1              # equivalence left side + gradient flip control
build _hdma      FREEZE=1 HDMA_ORIGIN=1          # equivalence right side (classic origin pair)
build _tear      FREEZE=1 NO_GRAD=1 IRQ_INTERLEAVE=1  # H4 latch-interleave tear control
