#!/usr/bin/env bash
# build_split_h_2p_variants.sh — the -D variant ROMs the test suite drives.
# (The generic make rule can't pass -D defines; this script mirrors the
# split_h_persp_demo variant-build pattern.)
set -euo pipefail
cd "$(dirname "$0")/../.."

SRC=templates/split_h_2p_demo/main.asm
INC="-I infrastructure/rom_template -I lib/macros -I engine -I templates/split_h_2p_demo/assets"
CFG=infrastructure/rom_template/lorom_64k.cfg

CFG_STREAM=infrastructure/rom_template/lorom_stream.cfg   # ROTATE: 64-pose banks

build() {  # build <cfg> <suffix> <defines...>
    local cfg="$1" out="build/split_h_2p_demo$2"; shift 2
    local defs=()
    for d in "$@"; do defs+=("-D$d"); done
    ca65 --cpu 65816 $INC "${defs[@]}" "$SRC" -o "$out.o"
    ld65 -C "$cfg" "$out.o" -o "$out.sfc"
    echo "built $out.sfc  ($*)"
}

build "$CFG"        _freeze      FREEZE=1
build "$CFG"        _sameorigin  FREEZE=1 SAME_ORIGIN=1
build "$CFG"        _retarget    FREEZE=1 RETARGET=1
build "$CFG"        _latch       FREEZE=1 LATCH_VIOLATION=1
build "$CFG_STREAM" _rotate      ROTATE=1 POSES=256           # rotate DEFAULT: 256-pose per-band pairs
build "$CFG_STREAM" _rotate64    ROTATE=1                     # 64-pose classic shape (A/B build)
build "$CFG_STREAM" _rotfreeze   ROTATE=1 POSES=256 FREEZE=1  # rotate-in-place on the new default
build "$CFG"        _perband     FREEZE=1 PERBAND=1           # per-band pairs, static (mask/line-0 tests)
build "$CFG"        _badorder    FREEZE=1 PERBAND=1 PERBAND_BADORDER=1  # inverted-order control

# --- SPRITE STRESS RAIL (all ROTATE POSES=256; SP_N is WRAM-poked at $C0C0) ---
ROT="ROTATE=1 POSES=256"
PINCYC="FREEZE=1 SAME_ORIGIN=1 SP_PIN=1 SP_STATIC=1 SP_CYCLES=1 SPRITES=128"

# cycle instruments (HDMA dark, persp_cycles pattern; test pokes SP_N):
#   _spr_cyc     all-visible world, facing it (FULL projection path)
#   _spr_cycaway same world, cameras pinned 180 degrees away (v-cull path)
#   _spr_cycfar  far world (Chebyshev pre-cull path)
build "$CFG_STREAM" _spr_cyc     $ROT $PINCYC SP_H1=64  SP_H2=64  SP_VISWORLD=1
build "$CFG_STREAM" _spr_cycaway $ROT $PINCYC SP_H1=192 SP_H2=192 SP_VISWORLD=1
build "$CFG_STREAM" _spr_cycfar  $ROT $PINCYC SP_H1=64  SP_H2=64  SP_FARWORLD=1

# integrated auto-rotate+drive stress build (cadence grid; test pokes SP_N)
build "$CFG_STREAM" _spr_rot     $ROT SPRITES=128 SP_STATIC=1

# worst-case in-situ cadence: ALL sprites visible in BOTH bands, display +
# HDMA live (pinned still — projection cost is motion-independent)
build "$CFG_STREAM" _spr_pinvis  $ROT FREEZE=1 SAME_ORIGIN=1 SP_PIN=1 \
      SP_H1=64 SP_H2=64 SPRITES=128 SP_STATIC=1 SP_VISWORLD=1

# THE INTEGRATED SWEEP BUILD: joypad-driven players (auto-joypad, $4200=$81)
# + AI followers + tiers on the main world; SP_N poked per sweep point
build "$CFG_STREAM" _spr_sweep   $ROT SPRITES=128 SP_INPUT=1

# AI-only cycle instrument (tick = sp_ai_tick; pure per-follower cost)
build "$CFG_STREAM" _spr_cycai   $ROT FREEZE=1 SP_PIN=1 SP_H1=64 SP_H2=64 \
      SP_CYCLES=1 SP_CYCAI=1 SPRITES=128

# INTEGRATED tick instrument (AI + sync + projection + OAM commit on the
# main world — the headroom-rule measurement for the ship default)
build "$CFG_STREAM" _spr_cycint  $ROT FREEZE=1 SP_PIN=1 SP_H1=64 SP_H2=64 \
      SP_CYCLES=1 SP_CYCINT=1 SPRITES=128

# THE SHIPPED DEFAULT: largest N with +1/+1 lockstep AND >=15% modeled
# headroom (measured via _spr_cycint: N=24 -> 31%, N=32 -> 10%) — joypad
# players + 22 AI followers + tiers
build "$CFG_STREAM" _sprites     $ROT SPRITES=24 SP_INPUT=1

# ALTERNATE-FRAME REPROJECTION PROBE (owner feel-test question, NOT the
# default): halves reproject at 30 Hz over the 60 Hz display; fixed slot
# regions per half; AI halves tick alternately at full-speed accumulate
build "$CFG_STREAM" _spr_alt     $ROT SPRITES=64 SP_INPUT=1 SP_ALTFRAME=1

# glue-proof pin stills on the MAIN world (heading pairs searched by the
# asset generator for coverage + control discriminability) + the WRONG-MATRIX
# control (SP_FORWARD: forward floor matrix — the ring test must MISS)
PINGLUE="FREEZE=1 SP_PIN=1 SP_STATIC=1 SP_MIR=1 SPRITES=128"
build "$CFG_STREAM" _spr_pin_a   $ROT $PINGLUE SP_H1=150 SP_H2=134
build "$CFG_STREAM" _spr_pin_b   $ROT $PINGLUE SP_H1=197 SP_H2=68
build "$CFG_STREAM" _spr_pin_c   $ROT $PINGLUE SP_H1=108 SP_H2=88
build "$CFG_STREAM" _spr_pinfwd  $ROT $PINGLUE SP_H1=197 SP_H2=68 SP_FORWARD=1

# tier-ladder / seam-margin / overflow stills (tier world: 24-sprite ladder,
# 36-sprite boundary-row cluster, 3 margin dead-zone probes at 60..62)
PINTIER="FREEZE=1 SAME_ORIGIN=1 SP_PIN=1 SP_H1=64 SP_H2=64 SP_STATIC=1 SP_TIERWORLD=1 SPRITES=63"
build "$CFG_STREAM" _spr_tier    $ROT $PINTIER
build "$CFG_STREAM" _spr_tieroff $ROT $PINTIER SP_TIEROFF=1   # constant-tier control
build "$CFG_STREAM" _spr_culloff $ROT $PINTIER SP_CULLOFF=1   # margins-off control
