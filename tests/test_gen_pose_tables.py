"""gen_pose_tables.py — the pose-table generator tooling (all granularities).

Pure-Python tests (no emulator): the generator's OUTPUT BYTES are the unit
under test — determinism, fixed-point structure, rotation identities, the
LoROM bank budget for every supported granularity, and the committed demo
assets' reproducibility (the provenance-manifest contract).
"""
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "gen_pose_tables.py"
DEMO_ASSETS = ROOT / "templates" / "split_h_2p_demo" / "assets"

LINES = 112
POSE_BYTES = LINES * 4
BANK = 32 * 1024
SLICE_POSES = 64                    # poses per LoROM bank slice (28,672 B)
SLICE_BYTES = SLICE_POSES * POSE_BYTES


def _run(tmp, angles, extra=()):
    subprocess.run([sys.executable, str(TOOL), "--angles", str(angles),
                    "--out-dir", str(tmp), *extra], check=True,
                   capture_output=True, text=True)
    ab = (tmp / f"poses{angles}_ab.bin").read_bytes()
    cd = (tmp / f"poses{angles}_cd.bin").read_bytes()
    return ab, cd


def _words(blob, pose, line):
    off = pose * POSE_BYTES + line * 4
    return struct.unpack_from("<hh", blob, off)


@pytest.mark.parametrize("angles", (64, 256))
def test_deterministic(tmp_path, angles):
    a1 = _run(tmp_path / "r1", angles)
    a2 = _run(tmp_path / "r2", angles)
    assert a1 == a2, "generator output is not byte-deterministic"


def test_angle0_structure(tmp_path):
    """Angle 0 = the pure hyperbolic ramp: B = C = 0, D = A, A monotonically
    non-increasing (adjacent lines may round to the SAME 8.8 value near the
    band bottom where the per-line delta drops under 1/256) with a real
    overall far->near decrease, endpoints at the geometry defaults."""
    ab, cd = _run(tmp_path, 1)
    assert len(ab) == len(cd) == POSE_BYTES
    a_prev = None
    for k in range(LINES):
        a, b = _words(ab, 0, k)
        c, d = _words(cd, 0, k)
        assert b == 0 and c == 0, f"line {k}: fixed angle must have B=C=0"
        assert d == a, f"line {k}: D != A"
        if a_prev is not None:
            assert a <= a_prev, f"line {k}: ramp increased"
        a_prev = a
    assert _words(ab, 0, 0)[0] > _words(ab, 0, LINES - 1)[0], "ramp is flat"
    assert _words(ab, 0, 0)[0] == round(1.5 * 256)
    assert _words(ab, 0, LINES - 1)[0] == round(0.625 * 256)


@pytest.mark.parametrize("angles", (32, 64, 128, 256, 512))
def test_rotation_identities_and_bank_budget(tmp_path, angles):
    """Every pose is a rotation of the shared ramp: C = -B, D = A, and the
    (A,B) magnitude equals the ramp scale within rounding. Blob sizes are the
    exact granularity budget under the SLICE model: 64 poses per 28,672-B bank
    slice (each slice fits a 32KB LoROM bank, every slice boundary lands ON a
    pose boundary) — 32/64 fit one bank, 128 = 2 slices, 256 = 4, 512 = 8.
    Pose sampling deliberately crosses slice boundaries (poses 64/128/... are
    in the sample set for 256/512) so the identities hold ACROSS banks."""
    ab, cd = _run(tmp_path / str(angles), angles)
    assert len(ab) == len(cd) == angles * POSE_BYTES
    slices = (len(ab) + SLICE_BYTES - 1) // SLICE_BYTES
    assert slices == max(1, angles // SLICE_POSES)
    assert SLICE_BYTES <= BANK, "a 64-pose slice must fit one LoROM bank"
    assert SLICE_BYTES % POSE_BYTES == 0, "slice boundary not a pose boundary"
    if angles > SLICE_POSES:
        # bank-slice addressability: pose (64k + j) at slice k offset j*448
        assert len(ab) == slices * SLICE_BYTES, "blob not whole slices"

    ramp = [_words(ab, 0, k)[0] for k in range(LINES)]      # angle-0 scales
    for pose in range(0, angles, max(1, angles // 16)):     # sample poses
        for k in (0, LINES // 2, LINES - 1):
            a, b = _words(ab, pose, k)
            c, d = _words(cd, pose, k)
            assert c == -b, f"pose {pose} line {k}: C != -B"
            assert d == a, f"pose {pose} line {k}: D != A"
            mag2 = a * a + b * b
            want = ramp[k] * ramp[k]
            assert abs(mag2 - want) <= 2 * ramp[k] + 2, \
                f"pose {pose} line {k}: rotation does not preserve scale"


def test_256_set_adjacent_pose_distinct(tmp_path):
    """The 8.8 precision floor: at 256 poses adjacent tables must still be
    byte-DISTINCT (the format wall where neighbours round identical sits at
    ~512-1024 poses — 256 is safely inside it). A granularity whose adjacent
    poses collide would silently halve the effective step rate."""
    ab, cd = _run(tmp_path, 256)
    for pose in range(0, 256, 16):
        nxt = (pose + 1) % 256
        assert ab[pose * POSE_BYTES:(pose + 1) * POSE_BYTES] != \
            ab[nxt * POSE_BYTES:(nxt + 1) * POSE_BYTES], \
            f"AB poses {pose} and {nxt} rounded byte-identical"


def test_move_lut_convention():
    """The committed move LUTs follow the velocity convention the rail's 8.8
    fractional accumulators consume: entry h = round(2*256*(-sin, -cos)
    (2*pi*h/N)) — magnitude 2.0 px/frame at every heading, entry 0 = (0,-512)
    (due 'up' in world -Y), the quarter-turn entry = (-512, 0), and entry
    h + N/2 is the exact negation of entry h."""
    import math
    for n in ("64", "256"):
        blob = (DEMO_ASSETS / f"move{n}.bin").read_bytes()
        n = int(n)
        assert len(blob) == n * 4
        assert struct.unpack_from("<hh", blob, 0) == (0, -512)
        assert struct.unpack_from("<hh", blob, (n // 4) * 4) == (-512, 0)
        for h in range(0, n, max(1, n // 16)):
            dx, dy = struct.unpack_from("<hh", blob, h * 4)
            a = 2.0 * math.pi * h / n
            assert dx == round(-512.0 * math.sin(a)), f"move{n}[{h}].dx"
            assert dy == round(-512.0 * math.cos(a)), f"move{n}[{h}].dy"
            ox, oy = struct.unpack_from("<hh", blob, ((h + n // 2) % n) * 4)
            assert (ox, oy) == (-dx, -dy), f"move{n}[{h}] opposite not negated"


def test_demo_assets_reproducible(tmp_path):
    """The committed demo assets regenerate byte-identically from the committed
    generators (the provenance-manifest contract; the un-reproducible-blob
    lesson from the perspective-series review)."""
    import shutil
    work = tmp_path / "assets"
    work.mkdir()
    for f in ("gen_assets.py",):
        shutil.copy(DEMO_ASSETS / f, work / f)
    # gen_assets.py locates the tool relative to its own path; run it from a
    # tree-shaped copy so that resolution works.
    tree_tool = tmp_path / "tools"
    tree_tool.mkdir()
    shutil.copy(TOOL, tree_tool / "gen_pose_tables.py")
    staged = tmp_path / "templates" / "split_h_2p_demo" / "assets"
    staged.mkdir(parents=True)
    shutil.copy(DEMO_ASSETS / "gen_assets.py", staged / "gen_assets.py")
    subprocess.run([sys.executable, str(staged / "gen_assets.py")],
                   check=True, capture_output=True, text=True)
    for name in ("checker_map.bin", "poses1_ab.bin", "poses1_cd.bin",
                 "pose_rot45_ab.bin", "pose_rot45_cd.bin",
                 "poses64_ab.bin", "poses64_cd.bin", "move64.bin",
                 "poses256_ab.bin", "poses256_cd.bin", "move256.bin"):
        got = (staged / name).read_bytes()
        want = (DEMO_ASSETS / name).read_bytes()
        assert got == want, f"{name}: committed asset != regenerated bytes"
