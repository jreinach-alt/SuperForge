#!/usr/bin/env bash
# SuperForge (asm-first) toolchain bootstrap script.
#
# Brings up everything needed to build a 65816 .sfc ROM with ca65/ld65 and
# verify it on the cycle-accurate Mesen2 emulator. Designed for fast agent
# startup — checks each tool before any network operation, so a warm
# environment finishes in seconds.
#
# What it sets up:
#   1. cc65 toolchain  — ca65 assembler + ld65 linker (the build pipeline)
#   2. Python deps     — Pillow (asset image work), pytest (test runner)
#   3. MesenCore.so    — Mesen2 native core (cached deploy, else build from source)
#   3b. fullsnes       — Nocash SNES hardware reference (best-effort, never committed)
#   4. MesenRunner     — confirm the test harness imports against the core
#   5. Smoke ROM       — assemble + link + RUN the hand-written smoke ROM, and
#                        confirm it reads back its "SFDB" debug magic on a real
#                        emulator run. This is the end-to-end pipeline gate:
#                        a clean assemble is NOT enough.
#
# Usage: bash tools/setup.sh
#
# Exit codes: 0 = toolchain ready + smoke ROM verified on the emulator,
#             1 = a required tool could not be installed, or the smoke ROM
#                 did not read back its magic.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Guard: this script needs the FULL repo tree (engine/, infrastructure/).
# If you are reading this inside the parent project's staging dir
# (asm_repo_staging/), the engine subset isn't here yet — materialize a
# complete tree first.
if [ ! -f "$PROJECT_ROOT/infrastructure/rom_template/header.inc" ] || \
   [ ! -f "$PROJECT_ROOT/engine/engine_state.inc" ]; then
    echo "ERROR: incomplete tree — engine/ or infrastructure/ is missing."
    echo "Run me from a cloned/materialized repo root. From the parent"
    echo "project's staging dir, materialize first:"
    echo "    bash tools/dryrun_split.sh /tmp/kit && cd /tmp/kit && bash tools/setup.sh"
    exit 1
fi

MESEN_BUILD_DIR="/tmp/Mesen2"
MESEN_SO_PATH="$MESEN_BUILD_DIR/InteropDLL/obj.linux-x64/MesenCore.so"
MESEN_CACHED="$SCRIPT_DIR/Mesen/MesenCore.so"

# Hand-written smoke ROM (Test ROM Pattern) + the shared ROM template that
# supplies header.inc / init.inc / lorom.cfg via the -I include path.
SMOKE_ASM="$PROJECT_ROOT/tests/smoke.asm"
ROM_TEMPLATE_DIR="$PROJECT_ROOT/infrastructure/rom_template"
SMOKE_CFG="$ROM_TEMPLATE_DIR/lorom.cfg"
SMOKE_O="$(mktemp -d)/smoke.o"
SMOKE_SFC="$(dirname "$SMOKE_O")/smoke.sfc"

PASS=0
FAIL=0

pass() { echo "  [OK] $1"; PASS=$((PASS + 1)); }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }

# --- Proxy detection for apt ---
# Cloud/container environments often route traffic through an egress proxy
# set in http_proxy/https_proxy. apt does not inherit these from sudo by
# default, so we write an apt config snippet if a proxy is detected and apt
# doesn't already have one.
configure_apt_proxy() {
    local apt_proxy_conf="/etc/apt/apt.conf.d/99proxy"
    if [ -f "$apt_proxy_conf" ]; then
        return 0  # already configured
    fi
    if [ -n "${http_proxy:-}" ]; then
        echo "  Configuring apt proxy (detected http_proxy in environment)..."
        echo "Acquire::http::Proxy \"$http_proxy\";" | sudo tee "$apt_proxy_conf" > /dev/null
        if [ -n "${https_proxy:-}" ]; then
            echo "Acquire::https::Proxy \"$https_proxy\";" | sudo tee -a "$apt_proxy_conf" > /dev/null
        fi
    fi
}

# Retry a command up to 4 times with exponential backoff (2s, 4s, 8s, 16s).
retry_cmd() {
    local desc="$1"; shift
    local max_retries=4
    for i in $(seq 1 $max_retries); do
        if "$@" 2>/dev/null; then
            return 0
        fi
        if [ "$i" -lt "$max_retries" ]; then
            local wait=$((2 ** i))
            echo "    Attempt $i/$max_retries failed ($desc), retrying in ${wait}s..."
            sleep "$wait"
        fi
    done
    echo "    All $max_retries attempts failed ($desc)"
    return 1
}

echo "=== SuperForge Toolchain Setup (asm-first) ==="
echo ""

# --- Shared apt helpers ---
# Run apt-get update once per session, tolerating failures on broken PPAs
# (e.g. deadsnakes/ondrej returning 403) so long as the main archive is
# reachable — apt-get install will still succeed against the package cache
# or retry each archive individually.
APT_UPDATED=0
apt_update_best_effort() {
    if [ "$APT_UPDATED" -eq 1 ]; then
        return 0
    fi
    configure_apt_proxy
    sudo apt-get update -qq 2>&1 | grep -Ev "^(E:|W:).*(PPA|ppa|Release|Forbidden|no longer signed)" || true
    APT_UPDATED=1
}

# --- 1. ca65 / ld65 (cc65 assembler + linker) + libSDL2 (runtime for Mesen) ---
# Install both in a single apt call: same archive, halves the network round trips.
echo "1. Checking ca65/ld65 + libSDL2..."
APT_NEEDED=""
if ! (ca65 --version >/dev/null 2>&1 && ld65 --version >/dev/null 2>&1); then
    APT_NEEDED="cc65"
fi
if ! ldconfig -p 2>/dev/null | grep -q "libSDL2-2.0.so.0"; then
    APT_NEEDED="$APT_NEEDED libsdl2-dev libasound2-dev"
fi
if [ -z "$APT_NEEDED" ]; then
    pass "ca65 $(ca65 --version 2>&1 | head -1) + ld65 + libSDL2 already installed"
else
    echo "  Installing:$APT_NEEDED ..."
    apt_update_best_effort
    if retry_cmd "apt-get install$APT_NEEDED" sudo apt-get install -y -qq $APT_NEEDED; then
        if ca65 --version >/dev/null 2>&1 && ld65 --version >/dev/null 2>&1; then
            pass "cc65 + libSDL2 installed"
        else
            fail "apt-get install returned 0 but ca65/ld65 still missing"
        fi
    else
        fail "cc65/libSDL2 install failed — check network and main-archive reachability"
    fi
fi

# --- 2. Python dependencies (Pillow + pytest) ---
echo "2. Checking Python dependencies..."
PYTHON_PKGS_NEEDED=""
python3 -c "from PIL import Image" >/dev/null 2>&1 || PYTHON_PKGS_NEEDED="Pillow"
python3 -c "import pytest" >/dev/null 2>&1 || PYTHON_PKGS_NEEDED="$PYTHON_PKGS_NEEDED pytest"
if [ -z "$PYTHON_PKGS_NEEDED" ]; then
    pass "Pillow + pytest already installed"
else
    echo "  Installing: $PYTHON_PKGS_NEEDED..."
    if retry_cmd "pip install" pip install --quiet $PYTHON_PKGS_NEEDED; then
        pass "Python dependencies installed ($PYTHON_PKGS_NEEDED)"
    else
        fail "Python dependency installation failed"
    fi
fi

# --- 3. MesenCore.so (SNES emulator core) ---
echo "3. Checking MesenCore.so..."
if [ -f "$MESEN_SO_PATH" ]; then
    pass "MesenCore.so found at $MESEN_SO_PATH"
elif [ -f "$MESEN_CACHED" ]; then
    echo "  Deploying cached MesenCore.so to $MESEN_SO_PATH..."
    mkdir -p "$(dirname "$MESEN_SO_PATH")"
    cp "$MESEN_CACHED" "$MESEN_SO_PATH"
    chmod +x "$MESEN_SO_PATH"
    pass "MesenCore.so deployed from cached copy"
else
    echo "  No cached or built MesenCore.so found. Building from source (~10 min)..."

    # Ensure SDL2 headers are present (required for build)
    if ! dpkg -s libsdl2-dev >/dev/null 2>&1; then
        echo "  Installing SDL2 build dependencies..."
        apt_update_best_effort
        retry_cmd "install SDL2" sudo apt-get install -y -qq libsdl2-dev libasound2-dev
    fi

    # Clone Mesen2 (shallow)
    if [ ! -d "$MESEN_BUILD_DIR" ]; then
        echo "  Cloning Mesen2 (shallow)..."
        if ! retry_cmd "git clone" git clone --depth 1 https://github.com/SourMesen/Mesen2.git "$MESEN_BUILD_DIR"; then
            fail "Could not clone Mesen2 — network issue"
        fi
    fi

    # Build core only
    if [ -d "$MESEN_BUILD_DIR" ]; then
        echo "  Building MesenCore.so (this takes ~10 minutes)..."
        if (cd "$MESEN_BUILD_DIR" && make -j"$(nproc)" core); then
            pass "MesenCore.so built from source"
            # Cache it for future sessions
            mkdir -p "$(dirname "$MESEN_CACHED")"
            cp "$MESEN_SO_PATH" "$MESEN_CACHED"
            echo "  Cached build artifact to $MESEN_CACHED"
        else
            fail "MesenCore.so build failed"
        fi
    fi
fi

# --- 3b. fullsnes hardware reference (best-effort, NEVER committed) ---
# The Nocash SNES specs are the most complete hardware reference. Fetched on
# demand (like the Mesen core), never committed — it is a reference, not a
# build input, so a failed fetch is non-fatal.
echo "3b. Checking fullsnes reference..."
FULLSNES_HTM="$PROJECT_ROOT/docs/reference/fullsnes.htm"
FULLSNES_URL="https://problemkaputt.de/fullsnes.htm"   # canonical host (Martin Korth)
# Fallback: the Internet Archive's latest snapshot of the SAME canonical URL.
# The `id_` flag serves the ORIGINAL bytes (no Wayback toolbar injected —
# consumers parse this file, so archive chrome would be silent corruption).
# Fallback only: the canonical live serve is always preferred; the snapshot
# exists so a host outage doesn't strand new users of an irreplaceable
# reference. Same licensing posture either way: fetched per-user for local
# reference, never committed (see NOTICE + .gitignore).
FULLSNES_ARCHIVE_URL="https://web.archive.org/web/2id_/https://problemkaputt.de/fullsnes.htm"
if [ -f "$FULLSNES_HTM" ] || [ -f "$PROJECT_ROOT/docs/reference/fullsnes.txt" ]; then
    pass "fullsnes reference already present (skipping fetch)"
elif command -v curl >/dev/null 2>&1; then
    mkdir -p "$(dirname "$FULLSNES_HTM")"
    # Raw download, NO HTML->text conversion (any transform = unverifiable mangling).
    if retry_cmd "fetch fullsnes" curl -fsSL --max-time 60 -o "$FULLSNES_HTM" "$FULLSNES_URL"; then
        pass "fullsnes fetched to docs/reference/fullsnes.htm (git-ignored)"
    elif echo "  [--] canonical host unreachable; trying the Internet Archive snapshot..." && \
         retry_cmd "fetch fullsnes (archive)" curl -fsSL --compressed --max-time 120 -o "$FULLSNES_HTM" "$FULLSNES_ARCHIVE_URL" && \
         grep -qi "SNES" "$FULLSNES_HTM"; then
         # --compressed is REQUIRED here: the Wayback id_ endpoint serves the
         # stored gzip stream; without it curl writes raw gzip bytes to disk
         # (verified 2026-07-18 — the grep guard above catches exactly that).
        pass "fullsnes fetched from the Internet Archive snapshot (git-ignored; canonical host was unreachable)"
    else
        rm -f "$FULLSNES_HTM"
        echo "  [WARN] Could not fetch fullsnes — reference, not a build input; continuing."
        echo "         Get it manually: $FULLSNES_URL  ->  docs/reference/fullsnes.htm"
        echo "         (or the archived copy: $FULLSNES_ARCHIVE_URL)"
    fi
else
    echo "  [WARN] curl not found; get fullsnes manually: $FULLSNES_URL -> docs/reference/fullsnes.htm"
fi

# --- 4. Verify MesenRunner can import ---
echo "4. Verifying MesenRunner integration..."
if (cd "$PROJECT_ROOT" && python3 -c "
from infrastructure.test_harness.mesen_runner import MesenRunner
print('OK')
" 2>/dev/null); then
    pass "MesenRunner imports successfully"
else
    fail "MesenRunner import failed"
fi

# --- 5. Smoke ROM: assemble -> link -> RUN -> read back the debug magic ---
# This is the end-to-end pipeline gate. A clean assemble proves the syntax is
# valid; it does NOT prove the ROM boots. We assemble + link the hand-written
# smoke ROM, run it on the cycle-accurate emulator, and confirm it wrote
# "SFDB" to $7E:E000 and the completion flag $0001 to $7E:E008. If the magic
# does not read back, the pipeline is broken and setup fails.
echo "5. Building + running the smoke ROM (end-to-end pipeline gate)..."
SMOKE_OK=0
if [ ! -f "$SMOKE_ASM" ]; then
    fail "smoke ROM source not found at $SMOKE_ASM"
elif ! ca65 -I "$ROM_TEMPLATE_DIR" "$SMOKE_ASM" -o "$SMOKE_O" 2>/dev/null; then
    fail "smoke ROM failed to assemble (ca65)"
elif ! ld65 -C "$SMOKE_CFG" "$SMOKE_O" -o "$SMOKE_SFC" 2>/dev/null; then
    fail "smoke ROM failed to link (ld65)"
else
    # Run the ROM on the emulator and read back the debug magic + completion flag.
    if (cd "$PROJECT_ROOT" && SMOKE_SFC="$SMOKE_SFC" python3 -c "
import os, sys
from infrastructure.test_harness.mesen_runner import MesenRunner, MemoryType
r = MesenRunner()
r.load_rom(os.environ['SMOKE_SFC'], run_seconds=2.0)
magic = bytes(r.read_bytes(MemoryType.SnesWorkRam, 0xE000, 4))
flag = r.read_u16(MemoryType.SnesWorkRam, 0xE008)
r.stop()
ok = magic == b'SFDB' and flag == 1
print('    smoke magic=%r completion=%d' % (magic, flag))
sys.exit(0 if ok else 1)
" 2>/dev/null); then
        pass "smoke ROM booted and read back SFDB magic + completion flag"
        SMOKE_OK=1
    else
        fail "smoke ROM ran but did NOT read back SFDB magic / completion flag"
    fi
fi
# Clean up the temp build artifacts (the .sfc is never committed).
rm -rf "$(dirname "$SMOKE_O")"

# --- Summary ---
echo ""
echo "=== Setup Complete: $PASS passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "Some checks failed. Review the output above."
    echo "If network issues persist, ensure DNS is reachable and retry."
    exit 1
fi

echo "Toolchain is ready and the build->run->verify pipeline is proven."
echo "You can now build and test ROMs."
exit 0
