#!/usr/bin/env bash
# Build the split_v_demo -D variant ROMs the D4/D5 tests use (the generic
# `make split_v_demo` rule can't pass -D defines). Run from the MATERIALIZED
# kit root, AFTER `make split_v_demo` (so build/ exists).
#
#   split_v_demo_nowin.sfc   -DNO_WINDOW=1 : the D5 NON-VACUITY control. The
#       window recipe is compiled out, so BG1 (camera A) fills the whole screen
#       and the two-region split COLLAPSES — the D1 two-region assertion MUST
#       FAIL on this ROM (proving the assertion is not vacuous).
#   split_v_demo_objclip.sfc -DOBJ_CLIP=1  : the D4 per-half OBJ-clip ROM. OBJ is
#       confined to the left half, so the P1 marker straddling the seam is
#       clipped — its across-seam portion vanishes.
set -euo pipefail
INC="-I infrastructure/rom_template -I lib/macros -I engine -I templates/split_v_demo/assets"
CFG=infrastructure/rom_template/lorom.cfg
SRC=templates/split_v_demo/main.asm
mkdir -p build

ca65 --cpu 65816 $INC -D NO_WINDOW=1 $SRC -o build/split_v_demo_nowin.o
ld65 -C $CFG build/split_v_demo_nowin.o -o build/split_v_demo_nowin.sfc
echo "built build/split_v_demo_nowin.sfc"

ca65 --cpu 65816 $INC -D OBJ_CLIP=1 $SRC -o build/split_v_demo_objclip.o
ld65 -C $CFG build/split_v_demo_objclip.o -o build/split_v_demo_objclip.sfc
echo "built build/split_v_demo_objclip.sfc"

ca65 --cpu 65816 $INC -D AUTODEMO=1 $SRC -o build/split_v_demo_autodemo.o
ld65 -C $CFG build/split_v_demo_autodemo.o -o build/split_v_demo_autodemo.sfc
echo "built build/split_v_demo_autodemo.sfc"

# split_v_demo_diagonal.sfc -DDIAGONAL=1 : the DIAGONAL coloured seam — WH0/WH2/WH3
# HDMA'd per scanline so the split + backdrop band SLANT. Pulls in the HDMA engine,
# so it links the 64 KB cfg.
ca65 --cpu 65816 $INC -D DIAGONAL=1 $SRC -o build/split_v_demo_diagonal.o
ld65 -C infrastructure/rom_template/lorom_64k.cfg build/split_v_demo_diagonal.o -o build/split_v_demo_diagonal.sfc
echo "built build/split_v_demo_diagonal.sfc"
