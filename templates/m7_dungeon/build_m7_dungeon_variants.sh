#!/usr/bin/env bash
# Build the m7_dungeon -D variant ROMs the S3 collision test uses (the generic
# `make m7_dungeon` rule can't pass -D defines). Run from the MATERIALIZED kit
# root (e.g. /tmp/s3_kit), AFTER `make m7_dungeon` (so build/ + assets exist).
#
#   m7_dungeon_nocol.sfc  -DNO_COLLISION=1  : the NEGATIVE CONTROL. The wall reject
#       is compiled out, so the hero WALKS THROUGH walls (footprint enters solid
#       cells). Proves the collision assertion is not vacuous — it CAN fail.
#   m7_dungeon_far.sfc    -DSPAWN_TX=43 -DSPAWN_TY=20 : spawns in a FAR maze cell
#       (the east 'D' branch, tile 43,20 px 348,164) so the test proves collision
#       holds far from the START cell, not just at spawn. S5: this cell is clear
#       of every enemy patrol beat (E0 row y=116, E1 col x=276, E2 row y=276) so
#       a patrolling enemy cannot knock the hero back and derail the collision
#       drive. (The old far spawn 34,14 px 276,116 sat ON E1's column beat.)
#       See make_dungeon.py MAZE.
set -euo pipefail
# The rail links the TAD audio build shape (lorom_tad_m7.cfg): the audio include
# path + the two TAD objects must match `make m7_dungeon`, or these variants would
# link a different memory map than the ROM under test. The TAD objects are built by
# the Makefile, so run this AFTER `make m7_dungeon` (its header says so).
INC="-I infrastructure/rom_template -I lib/macros -I engine -I lib/tad/audio-driver/ca65-api -I assets/audio -I templates/m7_dungeon/assets"
CFG=infrastructure/rom_template/lorom_tad_m7.cfg
TAD_OBJS="build/tad_audio_wrapper.o build/tad_audio_data.o"
SRC=templates/m7_dungeon/main.asm
mkdir -p build

ca65 --cpu 65816 $INC -D NO_COLLISION=1 $SRC -o build/m7_dungeon_nocol.o
ld65 -C $CFG build/m7_dungeon_nocol.o $TAD_OBJS -o build/m7_dungeon_nocol.sfc
echo "built build/m7_dungeon_nocol.sfc"

ca65 --cpu 65816 $INC -D SPAWN_TX=43 -D SPAWN_TY=20 $SRC -o build/m7_dungeon_far.o
ld65 -C $CFG build/m7_dungeon_far.o $TAD_OBJS -o build/m7_dungeon_far.sfc
echo "built build/m7_dungeon_far.sfc"

# S4 CULL variant: spawn in the GOAL cell (tile 44,44 -> px 356,356), far from
# the START-corridor enemies (px ~140..188,116). At >200px those enemies project
# off-screen and the ROM must PARK them (Y=$F0) — the deterministic cull test.
ca65 --cpu 65816 $INC -D SPAWN_TX=44 -D SPAWN_TY=44 $SRC -o build/m7_dungeon_goalspawn.o
ld65 -C $CFG build/m7_dungeon_goalspawn.o $TAD_OBJS -o build/m7_dungeon_goalspawn.sfc
echo "built build/m7_dungeon_goalspawn.sfc"

# S4-fix2 NON-VACUITY control: -DENEMY_PROJ_FORWARD compiles the OLD buggy
# world->screen projection that applied the FORWARD (screen->texel) matrix
# instead of its inverse, so enemies rotate the WRONG way and drift onto the
# WALLS under floor rotation. The rendered-floor regression test MUST FAIL on
# this ROM (enemy sprite centres land on wall-coloured pixels at rotated angles)
# and PASS on the fixed default — proving the floor test is not vacuous.
ca65 --cpu 65816 $INC -D ENEMY_PROJ_FORWARD=1 $SRC -o build/m7_dungeon_projfwd.o
ld65 -C $CFG build/m7_dungeon_projfwd.o $TAD_OBJS -o build/m7_dungeon_projfwd.sfc
echo "built build/m7_dungeon_projfwd.sfc"

# SPRITE-SIZE NON-VACUITY control: -DBUGGY_SPRITE_SIZE restores the old size bit
# (bit7 SET) on the hero + enemies, selecting the 32x32 LARGE size of OBSEL pair
# $62. A 32x32 hero reads a 4x4 tile block; its lower-left quadrant is tile 32 =
# the enemy CHR -> a phantom yellow diamond bleeds into the hero's lower body.
# The sprite-size regression test MUST FAIL on this ROM (size bit set + diamond
# pixels below the hero) and PASS on the fixed default — proving the test is not
# vacuous (it can tell a 16x16 hero from a 32x32 one).
ca65 --cpu 65816 $INC -D BUGGY_SPRITE_SIZE=1 $SRC -o build/m7_dungeon_bigspr.o
ld65 -C $CFG build/m7_dungeon_bigspr.o $TAD_OBJS -o build/m7_dungeon_bigspr.sfc
echo "built build/m7_dungeon_bigspr.sfc"

# ENEMY-COLOUR NON-VACUITY control (Wave-D dressing): -DENEMY_MISCOLOR loads a COOL
# (floor-blue) OBJ palette for the enemy instead of the demon's warm enemy_pal, so
# the demon renders BLUE and the rendered enemy-warm band reads 0 pixels. The enemy
# colour-band tests MUST FAIL on this ROM (0 enemy-warm pixels) and PASS on the real
# demon build — proving the retuned enemy colour band is not vacuous.
ca65 --cpu 65816 $INC -D ENEMY_MISCOLOR=1 $SRC -o build/m7_dungeon_miscolor.o
ld65 -C $CFG build/m7_dungeon_miscolor.o $TAD_OBJS -o build/m7_dungeon_miscolor.sfc
echo "built build/m7_dungeon_miscolor.sfc"
