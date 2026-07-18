#!/usr/bin/env bash
# Build the split_h_demo -D variant ROMs the D1/D3/D4 non-vacuity controls use
# (the generic `make split_h_demo` rule can't pass -D defines). Run from the
# MATERIALIZED kit root, AFTER `make split_h_demo` (so build/ exists).
#
#   split_h_demo_nosplit.sfc  -DNO_SPLIT=1 : the D1 NON-VACUITY control. The
#       mode/TM split is compiled out, so the whole screen is a single Mode-7
#       floor with NO tile band — the D1 top-band tile signature MUST be ABSENT.
#   split_h_demo_nocolor.sfc  -DNO_COLORBAND=1 : the D4 non-vacuity control. The
#       COLDATA companion band is compiled out — the D4 colour-band pixel change
#       vs. this build MUST be present (this build is the "no band" reference).
#   split_h_demo_freeze.sfc   -DFREEZE_BAR=1 : the D3 non-vacuity control. The
#       bar fill is pinned constant — the D3 two-state fill-difference MUST FAIL.
#   split_h_demo_autodemo.sfc -DAUTODEMO=1  : self-running (frame-driven bar
#       sweep) for controller-free inspection.
set -euo pipefail
INC="-I infrastructure/rom_template -I lib/macros -I engine -I templates/split_h_demo/assets"
CFG=infrastructure/rom_template/lorom_64k.cfg
SRC=templates/split_h_demo/main.asm
mkdir -p build

build_variant () {
    local def="$1" out="$2"
    ca65 --cpu 65816 $INC -D "$def" $SRC -o "build/$out.o"
    ld65 -C $CFG "build/$out.o" -o "build/$out.sfc"
    echo "built build/$out.sfc  ($def)"
}

build_variant NO_SPLIT=1     split_h_demo_nosplit
build_variant NO_COLORBAND=1 split_h_demo_nocolor
build_variant FREEZE_BAR=1   split_h_demo_freeze
build_variant AUTODEMO=1     split_h_demo_autodemo
#   split_h_demo_threeband.sfc  -DTHREEBAND=1 : sf_split_h_bands demo — a 3-band
#       TM split (BG3 / BG1+BG3 / BG1) so THREE distinct horizontal regions
#       render (the N-band compiler done-condition).
build_variant THREEBAND=1    split_h_demo_threeband
#   split_h_demo_bright.sfc     -DBRIGHT_BAND=1 : archetype-D brightness band on
#       INIDISP (top full $0F, bottom dimmed $08) — exercises SF_SPLIT_BRIGHT.
#       Test pairs it against the default (no brightness band) for non-vacuity.
build_variant BRIGHT_BAND=1  split_h_demo_bright
#   split_h_demo_toggle.sfc     -DTOGGLE_SPLIT=1 : lifecycle — P1 A cycles the
#       mode/TM split OFF (sf_split_h_off) then back ON (re-arm). Test reads the
#       top-band instrument signature present -> gone -> back.
build_variant TOGGLE_SPLIT=1 split_h_demo_toggle
