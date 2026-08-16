"""The replay triple must reach a PLAIN assert failure.

docs/53 D-DH3 settles that a lockstep trajectory is a pure function of
`(rom md5, seed, input script)` and that every failure prints that triple.
`Machine._raise` covers every MachineError — but the failure kind a
test actually produces is a plain `assert`, and the spec's headline
scenario ("leave the test red WITH THE TRIPLE IN THE FAILURE TEXT" if the
11 == 12 desync reproduces) is exactly that shape. It printed without the
triple until `tests/conftest.py`'s `pytest_runtest_makereport` hook landed.

WHAT THIS READS. The output region here is the pytest REPORT — the bytes a
human is handed when a lockstep test goes red — so these tests run a real
pytest against a real red and read its real stdout. Asserting on
`machine_replay_section()` alone would test the payload while leaving the
WIRING (does the hook fire? does the section survive to the terminal?)
unproven, which is the indirect-evidence shape CLAUDE.md rule 2 refuses:
the hook could be unregistered and a payload-only test would stay green.

Both directions are driven, because a hook that fires on EVERYTHING is as
useless as one that fires on nothing: a red that drove a Machine must carry
the triple, and a red that drove no Machine must not grow a section.
"""
import subprocess
import sys
from pathlib import Path

import pytest

SUPERFORGE = Path(__file__).resolve().parent.parent
ROM = SUPERFORGE / "build" / "microzero.sfc"

_SECTION = "replay triple (lockstep Machine)"

# A module that drives a Machine and then fails a PLAIN assert — no
# MachineError anywhere on the path, which is the whole point.
_RED_WITH_MACHINE = '''
import sys
sys.path.insert(0, {vendor!r})
from machine import Machine, MemoryType

def test_red():
    m = Machine({rom!r})
    m.advance(12, pad1={{"right": True, "b": True}})
    m.advance(7)
    try:
        assert m.read_bytes(MemoryType.SnesWorkRam, 0, 1)[0] == 0xAB
    finally:
        m.close()
'''

# The negative control: a red with no Machine in the process at all.
_RED_WITHOUT_MACHINE = '''
def test_red():
    assert 1 == 2
'''


def _run_red(tmp_path, body):
    """Run a one-test module under THIS repo's conftest; return its output."""
    # The hook lives in tests/conftest.py, so the generated module must be
    # collected beside a copy of it — pytest loads conftest from the test
    # file's own directory chain, not from rootdir.
    (tmp_path / "conftest.py").write_text(
        (SUPERFORGE / "tests" / "conftest.py").read_text())
    (tmp_path / "test_generated_red.py").write_text(body)
    r = subprocess.run(
        [sys.executable, "-m", "pytest", str(tmp_path / "test_generated_red.py"),
         "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=SUPERFORGE, capture_output=True, text=True)
    assert r.returncode != 0, (
        f"the generated module was supposed to go RED and did not — this "
        f"test proves nothing unless it does:\n{r.stdout}\n{r.stderr}")
    return r.stdout


@pytest.fixture(scope="module", autouse=True)
def rom_built():
    r = subprocess.run(["make", "microzero"], cwd=SUPERFORGE,
                       capture_output=True, text=True)
    assert r.returncode == 0, f"make microzero failed:\n{r.stdout}\n{r.stderr}"


def test_a_plain_assert_red_carries_the_replay_triple(tmp_path):
    """The headline shape, end to end through a real pytest run."""
    out = _run_red(tmp_path, _RED_WITH_MACHINE.format(
        vendor=str(SUPERFORGE / "vendor"), rom=str(ROM)))

    assert _SECTION in out, (
        f"a plain-assert red in a module that drove a Machine printed NO "
        f"replay-triple section — D-DH3 says every failure prints the "
        f"triple:\n{out}")

    # The triple itself, not merely a section header: all three components,
    # each read from the machine the generated module actually drove.
    rom_md5 = __import__("hashlib").md5(ROM.read_bytes()).hexdigest()
    assert rom_md5 in out, f"the ROM md5 {rom_md5} is missing:\n{out}"

    sys.path.insert(0, str(SUPERFORGE / "vendor"))
    from machine import DEFAULT_POWERON_SEED
    assert f"{DEFAULT_POWERON_SEED:#x}" in out, (
        f"the seed {DEFAULT_POWERON_SEED:#x} is missing:\n{out}")

    # The input script, exactly as the module drove it: 12 frames on
    # right+b, then 7 frames with both pads released.
    assert "(12, ('b', 'right'), ())" in out and "(7, (), ())" in out, (
        f"the input script is missing or wrong — without it the triple "
        f"does not replay:\n{out}")


def test_a_red_that_drove_no_machine_gets_no_section(tmp_path):
    """The control: the hook must not rubber-stamp every failure."""
    out = _run_red(tmp_path, _RED_WITHOUT_MACHINE)
    assert _SECTION not in out, (
        f"a red with no Machine in the process grew a replay-triple "
        f"section — the hook fires on everything, so its presence on a "
        f"lockstep red proves nothing:\n{out}")
