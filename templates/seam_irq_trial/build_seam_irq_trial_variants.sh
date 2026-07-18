#!/usr/bin/env bash
# build_seam_irq_trial_variants.sh — the -D variant ROMs the trial suite drives.
# (The generic make rule can't pass -D defines; mirrors the 2p rail's script.)
set -euo pipefail
cd "$(dirname "$0")/../.."

SRC=templates/seam_irq_trial/main.asm
INC="-I infrastructure/rom_template -I lib/macros -I engine -I templates/seam_irq_trial/assets"
CFG=infrastructure/rom_template/lorom_64k.cfg

build() {  # build <suffix> <defines...>
    local out="build/seam_irq_trial$1"; shift
    local defs=()
    for d in "$@"; do defs+=("-D$d"); done
    ca65 --cpu 65816 $INC "${defs[@]:+${defs[@]}}" "$SRC" -o "$out.o"
    ld65 -C "$CFG" "$out.o" -o "$out.sfc"
    echo "built $out.sfc  ($*)"
}

build _hdma     HDMA_ORIGIN=1     # the equivalence control (classic origin pair)
build _mistime  MISTIME=1         # VTIME=60 corruption control (non-vacuity)
build _hv       HV=1              # H+V trigger through the same HBlank gate
