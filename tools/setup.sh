#!/usr/bin/env bash
# SuperForge toolchain bootstrap.
#
# Verifies and installs everything needed to build and test this repo:
#   ca65/ld65 (cc65)  — assembler + linker
#   libSDL2/ALSA      — runtime libraries the Mesen2 core links against
#   Pillow, pytest    — the Python side of the harness
#   pytest-xdist      — optional parallel suite (`pytest tests/ -n 3`)
#   MesenCore.so      — the cycle-accurate SNES core the tests drive
#
# Usage: bash tools/setup.sh
#
# Exit codes: 0 = all tools ready, 1 = a required tool could not be installed.
#
# Scope note: this installs exactly what THIS repo builds and tests with —
# nothing more — and ends on its own gates: `make toy`, `make microzero`,
# `make toy-bad`.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

MESEN_BUILD_DIR="/tmp/Mesen2"
MESEN_SO_PATH="$MESEN_BUILD_DIR/InteropDLL/obj.linux-x64/MesenCore.so"
# Repo-local cache, so a rebuilt core survives a wiped /tmp. This path is the
# second candidate in vendor/mesen_runner.py::_detect_core_path().
MESEN_CACHED="$REPO_ROOT/tools/Mesen/MesenCore.so"

PASS=0
FAIL=0

pass() { echo "  [OK] $1"; PASS=$((PASS + 1)); }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }

# --- Proxy detection for apt ---
# Cloud/container environments often route traffic through an egress proxy set
# in http_proxy/https_proxy. apt does not inherit these from sudo by default,
# so write an apt config snippet if a proxy is detected and apt lacks one.
configure_apt_proxy() {
    local apt_proxy_conf="/etc/apt/apt.conf.d/99proxy"
    if [ -f "$apt_proxy_conf" ]; then
        return 0
    fi
    if [ -n "${http_proxy:-}" ]; then
        echo "  Configuring apt proxy (detected http_proxy in environment)..."
        echo "Acquire::http::Proxy \"$http_proxy\";" | sudo tee "$apt_proxy_conf" > /dev/null
        if [ -n "${https_proxy:-}" ]; then
            echo "Acquire::https::Proxy \"$https_proxy\";" | sudo tee -a "$apt_proxy_conf" > /dev/null
        fi
    fi
}

# Network operations retry with exponential backoff (2s, 4s, 8s, 16s).
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

APT_UPDATED=0
apt_update_best_effort() {
    if [ "$APT_UPDATED" -eq 1 ]; then
        return 0
    fi
    configure_apt_proxy
    # Tolerate broken third-party PPAs so long as the main archive is reachable.
    sudo apt-get update -qq 2>&1 \
        | grep -Ev "^(E:|W:).*(PPA|ppa|Release|Forbidden|no longer signed)" || true
    APT_UPDATED=1
}

echo "=== SuperForge Toolchain Setup ==="
echo ""

# --- 1. ca65 / ld65 + libSDL2 -----------------------------------------------
# Installed in a single apt call: same archive, half the network round trips.
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

# --- 2. Python dependencies (Pillow + pytest + pytest-xdist) ----------------
# pytest-xdist is what makes `python3 -m pytest tests/ -n 3` and `make test
# XDIST=3` work. Two things make the suite safe to parallelise, both in
# tests/conftest.py: each worker process gets its own Mesen home via
# SF_MESEN_HOME (vendor/mesen_runner.py `_detect_home_dir`), so no two workers
# share a Screenshots/ or — load-bearing since the SRAM slice — a Saves/*.srm;
# and the two modules that plant into this repo's own working tree hold an
# exclusive lock, so their save/write/restore windows cannot overlap.
#
# No longer optional: CI runs the suite in parallel (`make test XDIST=N` in
# .github/workflows/ci.yml). A local `make test` is still single-threaded —
# XDIST unset is the default.
echo "2. Checking Python dependencies..."
PYTHON_PKGS_NEEDED=""
python3 -c "from PIL import Image" >/dev/null 2>&1 || PYTHON_PKGS_NEEDED="Pillow"
python3 -c "import pytest" >/dev/null 2>&1 || PYTHON_PKGS_NEEDED="$PYTHON_PKGS_NEEDED pytest"
python3 -c "import xdist" >/dev/null 2>&1 || PYTHON_PKGS_NEEDED="$PYTHON_PKGS_NEEDED pytest-xdist"
if [ -z "$PYTHON_PKGS_NEEDED" ]; then
    pass "Pillow + pytest + pytest-xdist already installed"
else
    echo "  Installing: $PYTHON_PKGS_NEEDED..."
    if retry_cmd "pip install" pip install --quiet $PYTHON_PKGS_NEEDED; then
        pass "Python dependencies installed ($PYTHON_PKGS_NEEDED)"
    else
        fail "Python dependency installation failed"
    fi
fi

# --- 2a. Pillow inside pytest's uv-tool Python ------------------------------
# When pytest comes from `uv tool install pytest` it runs in its own isolated
# env. Asset generators invoked from tests use sys.executable — which under
# pytest IS that env — so a missing Pillow there surfaces as a misleading
# generator error rather than a test failure. `--reinstall` is required: uv
# treats `--with` as a no-op when the tool is already installed.
if command -v uv >/dev/null 2>&1; then
    echo "2a. Ensuring Pillow in pytest's uv-tool Python..."
    if uv tool install --with Pillow pytest --reinstall >/dev/null 2>&1; then
        pass "Pillow installed in pytest's uv-tool Python"
    else
        echo "  [WARN] uv tool install --with Pillow pytest --reinstall failed."
        echo "         If pytest is uv-tool-managed, tests that shell out to the"
        echo "         asset generators may fail with misleading PIL errors."
    fi
fi

# --- 3. MesenCore.so (the cycle-accurate SNES core) -------------------------
echo "3. Checking MesenCore.so..."
if [ -f "$MESEN_SO_PATH" ]; then
    pass "MesenCore.so found at $MESEN_SO_PATH"
elif [ -f "$MESEN_CACHED" ]; then
    echo "  Deploying cached MesenCore.so to $MESEN_SO_PATH..."
    mkdir -p "$(dirname "$MESEN_SO_PATH")"
    cp "$MESEN_CACHED" "$MESEN_SO_PATH"
    chmod +x "$MESEN_SO_PATH"
    pass "MesenCore.so deployed from repo-local cache"
else
    echo "  No cached or built MesenCore.so found. Building from source (~10 min)..."

    if ! dpkg -s libsdl2-dev >/dev/null 2>&1; then
        echo "  Installing SDL2 build dependencies..."
        apt_update_best_effort
        retry_cmd "install SDL2" sudo apt-get install -y -qq libsdl2-dev libasound2-dev
    fi

    if [ ! -d "$MESEN_BUILD_DIR" ]; then
        echo "  Cloning Mesen2 (shallow)..."
        if ! retry_cmd "git clone" git clone --depth 1 \
                https://github.com/SourMesen/Mesen2.git "$MESEN_BUILD_DIR"; then
            fail "Could not clone Mesen2 — network issue"
        fi
    fi

    if [ -d "$MESEN_BUILD_DIR" ]; then
        echo "  Building MesenCore.so (this takes ~10 minutes)..."
        if (cd "$MESEN_BUILD_DIR" && make -j"$(nproc)" core); then
            pass "MesenCore.so built from source"
            mkdir -p "$(dirname "$MESEN_CACHED")"
            cp "$MESEN_SO_PATH" "$MESEN_CACHED"
            echo "  Cached build artifact to $MESEN_CACHED"
        else
            fail "MesenCore.so build failed"
        fi
    fi
fi

# --- 3a. Lockstep MesenCore (docs/53 D-DH2; vendor/mesen_patches/) ----------
# The deterministic-harness core: the shared /tmp/Mesen2 tree copied to a
# private /tmp/Mesen2-lockstep, patched, and built there — the shared tree is
# used by other sessions on this box and is never modified. Verify-not-rebuild:
# an existing core with the lockstep exports passes immediately (bare-check's
# clone takes this path); a missing one deploys from the repo-local cache or
# builds via apply.sh.
echo "3a. Checking lockstep MesenCore (vendor/mesen_patches)..."
LOCKSTEP_SO="/tmp/Mesen2-lockstep/InteropDLL/obj.linux-x64/MesenCore.so"
LOCKSTEP_CACHED="$REPO_ROOT/tools/Mesen/MesenCore-lockstep.so"
# No pipe here on purpose: under this script's `set -euo pipefail`, an
# `nm | grep -q` dies of SIGPIPE (grep -q exits at the first match, nm gets
# rc 141) and the verify reads FALSE with the symbol present — the exact
# masked-pipe class the "never pipe a gate without PIPESTATUS" rule is
# about, and it shipped a red into test_bare_check's clones once.
lockstep_ok() { case "$(nm -D "$1" 2>/dev/null)" in *" RunFramesSync"*) return 0;; *) return 1;; esac; }
if [ -f "$LOCKSTEP_SO" ] && lockstep_ok "$LOCKSTEP_SO"; then
    pass "lockstep MesenCore.so found at $LOCKSTEP_SO"
elif [ -f "$LOCKSTEP_CACHED" ] && lockstep_ok "$LOCKSTEP_CACHED"; then
    echo "  Deploying cached lockstep core to $LOCKSTEP_SO..."
    mkdir -p "$(dirname "$LOCKSTEP_SO")"
    cp "$LOCKSTEP_CACHED" "$LOCKSTEP_SO"
    chmod +x "$LOCKSTEP_SO"
    pass "lockstep MesenCore.so deployed from repo-local cache"
elif [ -d "$MESEN_BUILD_DIR" ]; then
    echo "  Building lockstep core via vendor/mesen_patches/apply.sh..."
    if bash "$REPO_ROOT/vendor/mesen_patches/apply.sh" "$MESEN_BUILD_DIR" \
            "/tmp/Mesen2-lockstep" >/dev/null 2>&1 && lockstep_ok "$LOCKSTEP_SO"; then
        pass "lockstep MesenCore.so built (patches applied to a private tree)"
    else
        fail "lockstep core build failed — run vendor/mesen_patches/apply.sh unredirected"
    fi
else
    fail "no Mesen2 source tree to patch — resolve step 3 first"
fi

# --- 4. Harness import ------------------------------------------------------
echo "4. Verifying the MesenRunner harness imports..."
if (cd "$REPO_ROOT" && python3 -c "
import sys; sys.path.insert(0, 'vendor')
from mesen_runner import MesenRunner
print('OK')
" >/dev/null 2>&1); then
    pass "vendor/mesen_runner.py imports successfully"
else
    fail "MesenRunner import failed — check Pillow and libSDL2"
fi

# --- 5. Sanity build: the toy ROM and its collision gate --------------------
# `toy` proves the allocator emits a map and the ROM links; `toy-bad` proves
# the collision gate still REFUSES an infeasible declaration, with the
# collision diagnostic rather than some other error.
#
# This check used to be inverted (`if make toy-bad; then fail; fi`) because the
# target failed on every path — which made it blind: a toothless allocator
# still produced a non-zero exit and this still printed "refused as designed"
# `make toy-bad` now exits 0 when the refusal was correct, so
# run it plainly.
echo "5. Running sanity build (toy + collision gate)..."
if (cd "$REPO_ROOT" && make toy >/dev/null 2>&1); then
    pass "make toy builds"
else
    fail "make toy failed — check ca65/ld65"
fi

if (cd "$REPO_ROOT" && make toy-bad >/dev/null 2>&1); then
    pass "make toy-bad: allocator refused as designed (collision gate intact)"
else
    fail "make toy-bad FAILED — the allocator collision gate did not refuse the
       collision toy for the right reason. Re-run 'make toy-bad' unredirected."
fi

# toy-bad's presence-side twin, same polarity: exit 0 means the gate
# refused the unbacked arm and accepted the backed one. Added because
# bring-up proved the collision gate and left the backing gate unproven on
# a fresh clone.
if (cd "$REPO_ROOT" && make rom-unbacked >/dev/null 2>&1); then
    pass "make rom-unbacked: backing gate refused the unbacked arm (intact)"
else
    fail "make rom-unbacked FAILED — the rom-claim backing gate did not refuse
       a claim with no .incbin. Re-run 'make rom-unbacked' unredirected."
fi

# --- 6. Sanity test: full pipeline assemble -> emulate -> verify ------------
echo "6. Running sanity test (allocator + ROM header)..."
if (cd "$REPO_ROOT" && python3 -m pytest tests/test_allocator.py tests/test_rom_header.py -q \
        >/dev/null 2>&1); then
    pass "sanity tests pass"
else
    fail "sanity tests failed — check MesenRunner + libSDL2"
fi

# --- 7. Git hooks: the pre-push gate ----------------------------------------
# Hooks do NOT clone with the repo, so this wires the versioned hook directory
# in via core.hooksPath. The value is RELATIVE on purpose: worktrees share
# repo config, and git resolves a relative hooksPath against the working tree
# a push runs from — so every worktree runs its own checked-out
# tools/git-hooks/pre-push against its own tree. Idempotent: setting the same
# value twice is a no-op, and an existing DIFFERENT value is reported as a
# failure rather than silently overwritten (someone chose it; look first).
# Bypass for a deliberately-red push: `git push --no-verify`.
echo "7. Installing the pre-push gate (core.hooksPath)..."
HOOKS_PATH_WANT="tools/git-hooks"
HOOKS_PATH_NOW="$(git -C "$REPO_ROOT" config --get core.hooksPath || true)"
if [ "$HOOKS_PATH_NOW" = "$HOOKS_PATH_WANT" ]; then
    pass "core.hooksPath already $HOOKS_PATH_WANT (pre-push gate active)"
elif [ -n "$HOOKS_PATH_NOW" ]; then
    fail "core.hooksPath is '$HOOKS_PATH_NOW', not $HOOKS_PATH_WANT — not overwriting; resolve by hand"
elif git -C "$REPO_ROOT" config core.hooksPath "$HOOKS_PATH_WANT"; then
    pass "core.hooksPath set to $HOOKS_PATH_WANT (pre-push gate active)"
else
    fail "could not set core.hooksPath — pre-push gate NOT installed"
fi

# --- Summary ---------------------------------------------------------------
echo ""
echo "=== Setup Complete: $PASS passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "Some checks failed. Read the output above."
    echo "If network issues persist, ensure DNS is reachable and retry."
    exit 1
fi

echo "Toolchain is ready. Next: make microzero && python3 -m pytest tests/ -q"
exit 0
