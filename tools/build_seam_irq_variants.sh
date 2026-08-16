#!/usr/bin/env bash
# Build seam_irq_trial's -D control variants. The generic make rule cannot
# pass a define, so they live here — the tools/build_svd_nowin.sh shape.
#
# TWO controls, and each is one half of the trial's evidence:
#
#   sit_origin   SIT_HDMA_ORIGIN=1  the GOLD control: the classic origin
#                channel pair (non-repeat [112,X,Y][1,X,Y][0] tables, in the
#                HDMAEN mask) instead of the IRQ + pre-armed GP-DMA path — the
#                same static scene through the mechanism every prior rail
#                ships. The headline assertion: default vs control
#                framebuffers BYTE-IDENTICAL on an absolute frame. No IRQ, no
#                SF_IRQ_VECTOR (this build exercises header.inc's NMI_STUB
#                default), no VTIME write.
#
#   sit_mistime  SIT_MISTIME=1      the NON-VACUITY control: VTIME=60, so the
#                SAME fire lands in scanline 60's HBlank and content lines
#                60..111 render with band 2's warm origin. The SAME
#                full-frame metric that calls default==gold identical must
#                FLIP here — without this build, "the pictures match" could
#                be satisfied by a comparison too dull to see a mistimed
#                seam. It is a separate BINARY because a control the code
#                under test could write is not a control (the svd_nowin
#                ruling).
#
# The -DHV build (H+V trigger through the same spin gate) is NOT built: H+V
# buys nothing once the handler spin-gates on the HBlank flag (measured
# identical completion), and a variant whose only claim is a settled
# equivalence does not earn its six registration sites.
#
# Run from the repo root, AFTER `make seam_irq_trial` (the assets and the
# emitted map must exist).
set -euo pipefail

BUILD=build
MAP=$BUILD/sit
VROM=vendor/rom
SRC=game/seam_irq_trial/main.asm

INC="-I $MAP -I $VROM -I game/seam_irq_trial
     -I engine/features/scene_mgr -I engine/features/fade
     -I engine/features/irq -I engine/features/sit_floor
     -I engine/features/sit_cam"

if [ ! -f "$MAP/symbol_map.json" ]; then
    echo "build_seam_irq_variants: run 'make seam_irq_trial' first ($MAP is missing)" >&2
    exit 1
fi

build_variant() {
    local name="$1"; shift
    # shellcheck disable=SC2086
    ca65 --cpu 65816 $INC --bin-include-dir "$BUILD/assets" "$@" \
        -o "$BUILD/$name.o" "$SRC"
    ld65 -C "$VROM/lorom_512k.cfg" -o "$BUILD/$name.sfc" "$BUILD/$name.o"
    python3 tools/fix_checksum.py "$BUILD/$name.sfc" >/dev/null
    echo "built $BUILD/$name.sfc"
}

case "${1:-all}" in
    origin)  build_variant sit_origin  -D SIT_HDMA_ORIGIN=1 ;;
    mistime) build_variant sit_mistime -D SIT_MISTIME=1 ;;
    all)     build_variant sit_origin  -D SIT_HDMA_ORIGIN=1
             build_variant sit_mistime -D SIT_MISTIME=1 ;;
    *) echo "usage: $0 [origin|mistime|all]" >&2; exit 2 ;;
esac
