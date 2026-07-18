"""Session-wide pytest fixtures for the kit test suite.

Build dependency for rail / sibling-test ROMs
---------------------------------------------
Most kit tests assert that a built ROM exists, e.g.::

    rom = BUILD / "mode7_test.sfc"
    assert rom.exists(), f"{rom} not built — run `make testroms` first"

If a user ran only ``make <template>`` (not ``make testroms``), that assert
fires with a message that reads like a regression rather than "you skipped a
build step". This hook closes the gap: before each test runs, it scans the
test's own source for ``"<name>.sfc"`` references and, for any whose
``build/<name>.sfc`` is MISSING, builds just that ROM via ``make`` — but only
when ``<name>`` is a single, known make target.

Why this shape (lowest-risk):
  * Lazy + targeted — builds only the specific ROM a test needs, the first
    time it's needed, never a blanket ``make testroms``. A run that touches
    one rail test pays for one ROM, not the whole testrom set.
  * Memoized per session — each ROM is attempted at most once; a second test
    that needs the same ROM is a dict hit, no subprocess.
  * Conservative — ``-D`` variant ROMs (e.g. ``m7_dungeon_far.sfc``,
    ``meteor_event_nocap.sfc``) have NO single make target; ``make -n`` reports
    "No rule to make target" for them, so the hook skips them and leaves the
    test's own module-scoped build fixture to handle them. Existing passing
    tests are unaffected: if the ROM already exists, the hook is a no-op.

If a build fails, the hook stays silent and lets the test's own
``assert rom.exists()`` produce the (now-accurate) failure — it never masks a
real build break.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"

# "<name>.sfc" string literals in test source.
_SFC_RE = re.compile(r'["\']([A-Za-z0-9_]+)\.sfc["\']')

# Per-session memo: rom stem -> already attempted (regardless of outcome).
_attempted: set[str] = set()
# Per-module memo: module path -> set of rom stems referenced in its source.
_module_roms: dict[Path, set[str]] = {}


def _roms_referenced_by(module_path: Path) -> set[str]:
    """Extract the set of `<stem>.sfc` rom stems named in a test module's
    source. Cached per module path."""
    cached = _module_roms.get(module_path)
    if cached is not None:
        return cached
    try:
        text = module_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    stems = set(_SFC_RE.findall(text))
    _module_roms[module_path] = stems
    return stems


def _is_known_target(stem: str) -> bool:
    """True if `make build/<stem>.sfc` is a target make knows how to build.
    A `-D` variant ROM (built by a test's own fixture) has no such rule and
    returns nonzero here, so we skip it."""
    try:
        res = subprocess.run(
            ["make", "-n", f"build/{stem}.sfc"],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, FileNotFoundError):
        return False
    return res.returncode == 0


def _ensure_rom(stem: str) -> None:
    """Build `build/<stem>.sfc` if missing and a known single make target.
    Attempted at most once per session; never raises (a failed build is left
    for the test's own existence assertion to report accurately)."""
    if stem in _attempted:
        return
    _attempted.add(stem)
    if (BUILD / f"{stem}.sfc").exists():
        return
    if not _is_known_target(stem):
        return
    try:
        subprocess.run(
            ["make", f"build/{stem}.sfc"],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=600,
        )
    except (OSError, FileNotFoundError, subprocess.TimeoutExpired):
        # Leave the missing ROM for the test's own assert to surface.
        pass


def pytest_runtest_setup(item) -> None:
    """Before each test, build any missing ROM the test's module references
    (when it maps to a single known make target)."""
    module_path = Path(str(item.fspath))
    for stem in _roms_referenced_by(module_path):
        _ensure_rom(stem)
