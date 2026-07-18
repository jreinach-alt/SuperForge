#!/usr/bin/env bash
# Build the m7_oshoot -D variant ROMs (the generic `make m7_oshoot` rule can't
# pass -D defines). Run from the MATERIALIZED kit root, AFTER `make m7_oshoot`
# (so build/ + assets exist). These are the NON-VACUITY controls the rendered-
# output acceptance gate (tests/test_m7_oshoot.py) builds on.
#
#   m7_oshoot_projfwd.sfc  -DBULLET_PROJ_FORWARD=1 : the S3 PROJECTION non-vacuity
#       control. Bullets are projected with the FORWARD (screen->texel) matrix
#       [[A,B],[C,D]] instead of its inverse (the TRANSPOSE [[A,C],[B,D]]), so a
#       bullet over WORLD-floor SWIMS onto the WALLS as the plane rotates. The
#       rendered-floor S3 tests (#2 bullet-on-floor, #3 glue-through-rotation)
#       MUST FAIL on this ROM and PASS on the default — proving they are not
#       vacuous (they discriminate a correct projection from a wrong one).
#
#   m7_oshoot_nobulcol.sfc -DNO_BULLET_COLLISION=1 : the S5 bullet<->enemy
#       COLLISION non-vacuity control. The world-space overlap is compiled out,
#       so bullets pass THROUGH enemies (the enemy survives at every angle). The
#       S5 hit-through-rotation test (#4) MUST FAIL on this ROM (enemy not killed,
#       KILLS stays 0) — proving the collision assertion is not vacuous.
#
#   m7_oshoot_nocol.sfc    -DNO_COLLISION=1 : the WALL-collision negative control
#       (kept from the m7_dungeon brick). The player walks through arena walls /
#       obstacles — proves the world-space wall-collision assertion can fail.
set -euo pipefail
INC="-I infrastructure/rom_template -I lib/macros -I engine -I templates/m7_oshoot/assets"
CFG=infrastructure/rom_template/lorom_64k.cfg
SRC=templates/m7_oshoot/main.asm
mkdir -p build

ca65 --cpu 65816 $INC -D BULLET_PROJ_FORWARD=1 $SRC -o build/m7_oshoot_projfwd.o
ld65 -C $CFG build/m7_oshoot_projfwd.o -o build/m7_oshoot_projfwd.sfc
echo "built build/m7_oshoot_projfwd.sfc"

ca65 --cpu 65816 $INC -D NO_BULLET_COLLISION=1 $SRC -o build/m7_oshoot_nobulcol.o
ld65 -C $CFG build/m7_oshoot_nobulcol.o -o build/m7_oshoot_nobulcol.sfc
echo "built build/m7_oshoot_nobulcol.sfc"

ca65 --cpu 65816 $INC -D NO_COLLISION=1 $SRC -o build/m7_oshoot_nocol.o
ld65 -C $CFG build/m7_oshoot_nocol.o -o build/m7_oshoot_nocol.sfc
echo "built build/m7_oshoot_nocol.sfc"

# S3 FROZEN-BULLET test build: bullets freeze at their spawn world spot so the
# glue-through-rotation test (#3) can sweep the plane through many headings while
# a FIXED world bullet must stay glued to the SAME rendered floor spot.
ca65 --cpu 65816 $INC -D DBG_FROZEN_BULLET=1 $SRC -o build/m7_oshoot_freeze.o
ld65 -C $CFG build/m7_oshoot_freeze.o -o build/m7_oshoot_freeze.sfc
echo "built build/m7_oshoot_freeze.sfc"

# S3 FROZEN-BULLET + FORWARD-matrix: the non-vacuity control for the glue test.
# The frozen bullet SWIMS onto the walls as the plane rotates (the forward matrix
# rotates the wrong way) — the glue test MUST FAIL on this build.
ca65 --cpu 65816 $INC -D DBG_FROZEN_BULLET=1 -D BULLET_PROJ_FORWARD=1 $SRC -o build/m7_oshoot_freeze_fwd.o
ld65 -C $CFG build/m7_oshoot_freeze_fwd.o -o build/m7_oshoot_freeze_fwd.sfc
echo "built build/m7_oshoot_freeze_fwd.sfc"
