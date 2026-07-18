#!/usr/bin/env bash
# Build the meteor_event -D variant ROMs (the generic `make meteor_event` rule
# can't pass -D defines). Run from the MATERIALIZED kit root, AFTER
# `make meteor_event` (so build/ + assets exist). These are the NON-VACUITY
# controls the rendered-output acceptance gate (tests/test_meteor_event.py)
# builds on — each MUST FAIL the matching assertion the default ROM PASSES.
#
#   meteor_event_nocap.sfc   -DNO_CAPTURE : the BG->OBJ capture is compiled out.
#       draw_capture_sprites emits ONLY the player (no captured ground), so when
#       ST_CAPTURE blacks the Mode-1 BG the ground band VANISHES to black. The
#       capture-alignment test (the OBJ ground band must match the BG ground
#       band) MUST FAIL on this ROM and PASS on the default — proving the
#       capture assertion is not vacuous.
#
#   meteor_event_nofreeze.sfc -DNO_FREEZE : input still moves the player during
#       the "freeze". play_input runs in ST_FREEZE, so holding RIGHT keeps the
#       camera scrolling while frozen. The freeze test (the rendered player /
#       camera does NOT move across freeze frames while input is held) MUST FAIL
#       on this ROM — proving the freeze assertion is not vacuous.
#
# --- Phase 2 controls ---
#   meteor_event_noscale.sfc  -DNO_SCALE : the grow ramp is compiled out, so the
#       Mode-7 meteor stays at its static scale and never gets bigger. The grow
#       test (rendered meteor bbox t1 > t0) MUST FAIL on this ROM.
#
#   meteor_event_nograd.sfc   -DNO_GRADIENT : the red impact glow is compiled out
#       (color math never enabled, BOT_R stays 0), so NO red appears in the lower
#       band. The glow test (lower-band red rises then recedes) MUST FAIL on it.
#
#   meteor_event_norelease.sfc -DNO_RELEASE : the swap-back never runs and control
#       is never returned — the ROM stays in ST_RESTORE on the Mode-7 scene with
#       input frozen. The control-released test (held RIGHT advances the player
#       after the event) MUST FAIL on this ROM.
set -euo pipefail
INC="-I infrastructure/rom_template -I lib/macros -I engine -I templates/meteor_event/assets"
CFG=infrastructure/rom_template/lorom_64k.cfg
SRC=templates/meteor_event/main.asm
mkdir -p build

ca65 --cpu 65816 $INC -D NO_CAPTURE=1 $SRC -o build/meteor_event_nocap.o
ld65 -C $CFG build/meteor_event_nocap.o -o build/meteor_event_nocap.sfc
echo "built build/meteor_event_nocap.sfc"

ca65 --cpu 65816 $INC -D NO_FREEZE=1 $SRC -o build/meteor_event_nofreeze.o
ld65 -C $CFG build/meteor_event_nofreeze.o -o build/meteor_event_nofreeze.sfc
echo "built build/meteor_event_nofreeze.sfc"

ca65 --cpu 65816 $INC -D NO_SCALE=1 $SRC -o build/meteor_event_noscale.o
ld65 -C $CFG build/meteor_event_noscale.o -o build/meteor_event_noscale.sfc
echo "built build/meteor_event_noscale.sfc"

ca65 --cpu 65816 $INC -D NO_GRADIENT=1 $SRC -o build/meteor_event_nograd.o
ld65 -C $CFG build/meteor_event_nograd.o -o build/meteor_event_nograd.sfc
echo "built build/meteor_event_nograd.sfc"

ca65 --cpu 65816 $INC -D NO_RELEASE=1 $SRC -o build/meteor_event_norelease.o
ld65 -C $CFG build/meteor_event_norelease.o -o build/meteor_event_norelease.sfc
echo "built build/meteor_event_norelease.sfc"

ca65 --cpu 65816 $INC -D NO_TUMBLE=1 $SRC -o build/meteor_event_notumble.o
ld65 -C $CFG build/meteor_event_notumble.o -o build/meteor_event_notumble.sfc
echo "built build/meteor_event_notumble.sfc"
