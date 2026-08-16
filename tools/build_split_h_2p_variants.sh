#!/usr/bin/env bash
# Build the split_h_2p_demo -D proof variants. The generic make rule cannot
# pass -D, so these live here — the same shape tools/build_split_v_variants.sh
# has, and for the same reason.
#
# WHY A CONTROL BUILD AT ALL. The rail's headline claims are that the two bands
# carry two INDEPENDENT cameras — different positions AND different, oppositely
# rotating headings — and that band 2's line-0 stray HDMA unit is masked by
# channel priority. Each of those is weak on its own: a rail with one camera
# mirrored into both bands would satisfy "the floors look different", and
# "line 0 looks fine" says nothing unless something can make it wrong. So each
# claim gets a build that MAKES IT FAIL:
#
#   sh2_same_heading  SH2_SAME_HEADING=1  camera 2's heading := camera 1's, at
#                     the start AND on every step, so both bands stream the
#                     SAME pose. The per-band heading recovered off the
#                     framebuffer must then be EQUAL in the two bands, where
#                     the shipping ROM's must differ and move oppositely.
#                     Positions still differ, so this kills the rotation signal
#                     WITHOUT killing the position one.
#
#   sh2_same_cam      SH2_SAME_ORIGIN=1 SH2_SAME_HEADING=1  both folded, so the
#                     two cameras are ONE camera for all time (same start, same
#                     heading, therefore the same move-LUT velocity every
#                     frame). The two bands' recovered states must be
#                     identical. This is the "two cameras" claim's control.
#
#   sh2_sp_forward    SH2_SP_FORWARD=1  the PROJECTION's control.
#                     mpp_band_coeffs negates sin, which turns R(-theta) into
#                     R(theta) — the FORWARD floor matrix. The markers still
#                     move, still stay on screen and still look like a plausible
#                     crowd; they simply stop standing on the world tile the
#                     floor draws under them. That is the failure that survives
#                     a casual look, which is exactly why it needs a build:
#                     measured over the rail's whole 256-state camera cycle, the
#                     shipping ROM's markers land at most 4 world px from their
#                     own texel and this one's land a median of ~80..115 away —
#                     a SAMPLE median of a wandering quantity (measured 106
# here, 114 in the test module, 80 in a third run), so the
#                     test asserts a floor of 32 rather than any one figure.
#
#   sh2_sp_tieroff    SH2_SP_TIEROFF=1  every marker gets the middle size tier,
#                     so apparent size stops tracking depth. Without it, "far
#                     markers are drawn smaller" is a claim about a table
#                     nothing can contradict.
#
#   sh2_sp_culloff    SH2_SP_CULLOFF=1  removes both per-band SEAM guards, so a
#                     band-1 marker's box draws down into band 2's half of the
#                     picture and vice versa. The two bands are two CAMERAS, so
#                     that is not a clip artefact but one camera's sprite drawn
#                     inside another camera's view — and the palettes make it
#                     legible: white below the seam, magenta above it.
#
#   sh2_badorder      SH2_BADORDER=1  swaps WHICH CHANNEL each band's index
#                     table is bound to, so band 2's pair sits ABOVE band 1's
#                     and its skip-prefix entry's stray line-0 unit WINS the
#                     line-0 HBlank. PPU line 0 must then render band 2's skip
#                     pose instead of band 1's. Nothing else changes: both
#                     channels are DMAP $43 to the same BBAD, so the swap is
#                     exactly the priority inversion and nothing more.
#                     (a bad-band-order control, expressed as a binding swap
#                     because here the channel NUMBERS are declared, not
#                     allocated in call order.)
#
# SH2_SAME_ORIGIN ALONE IS NO LONGER A CONTROL, and that is a consequence of
# the cameras moving rather than an omission. Cameras that never changed x
# would have their start positions folded, moving band 2 off the warm stripe
# permanently and killing the red channel. These cameras DRIVE along their
# headings, so folding
# only the starts leaves two different velocities and the trajectories diverge
# again within a few frames. The define survives and is composed into
# sh2_same_cam, where folding the heading too makes the fold stick.
#
# Run from the repo root, AFTER `make split_h_2p_demo` (the assets and the
# emitted map must exist). No TAD objects: this rail is silent.
set -euo pipefail

BUILD=build
MAP=$BUILD/sh2
VROM=vendor/rom
SRC=game/split_h_2p_demo/main.asm

INC="-I $MAP -I $VROM -I game/split_h_2p_demo
     -I engine/features/scene_mgr -I engine/features/fade
     -I engine/features/input -I engine/features/input2
     -I engine/features/sh2_floor -I engine/features/sh2_cam
     -I engine/features/oam_sprites -I engine/features/m7_persp_project
     -I engine/features/sh2_swarm -I engine/features/sh2_obj"

if [ ! -f "$MAP/symbol_map.json" ]; then
    echo "build_split_h_2p_variants: run 'make split_h_2p_demo' first ($MAP is missing)" >&2
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

# THE AUTONOMOUS BUILD. The shipping ROM is the pad-driven one, whose
# cameras stand still until a pad moves them; -D SH2_AUTOCAM restores the
# autonomous rotate + drive. It is NOT a non-vacuity control — it is the build
# whose subject IS the autonomous camera model, so every test in
# tests/test_split_h_2p_demo.py whose claim is about rotation, drive or the
# DASB bank stamp reads this one, and the two folding controls below are built
# on top of it so they fold something that is still moving.
build_variant sh2_autocam      -D SH2_AUTOCAM=1
build_variant sh2_same_heading -D SH2_AUTOCAM=1 -D SH2_SAME_HEADING=1
build_variant sh2_same_cam     -D SH2_AUTOCAM=1 -D SH2_SAME_ORIGIN=1 -D SH2_SAME_HEADING=1
build_variant sh2_badorder     -D SH2_BADORDER=1
build_variant sh2_sp_forward   -D SH2_SP_FORWARD=1
build_variant sh2_sp_tieroff   -D SH2_SP_TIEROFF=1
build_variant sh2_sp_culloff   -D SH2_SP_CULLOFF=1
