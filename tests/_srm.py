"""Battery-SRAM (.srm) hygiene helpers — shared by every SRAM-using game's tests.

Mesen2's battery model (sf_save.inc SETUP CONTRACT, battery caveat):
the .srm file is flushed at ROM UNLOAD, never on write, and a fresh
load_rom seeds live SRAM from the file (or power-on GARBAGE if absent —
virgin SRAM is garbage, not zeros). These helpers encode the two
patterns every persistence test needs and the ordering trap behind them.

Dependency: the neutral ROM must already be built (`make testroms` —
text_test.sfc is the conventional choice: it never touches SRAM and its
own test reads only VRAM, so its .srm garbage-flush is harmless).
"""
from pathlib import Path

from infrastructure.test_harness import mesen_runner

SAVES_DIR = Path(mesen_runner._DEFAULT_HOME_DIR) / "Saves"


def srm_path(rom_name: str) -> Path:
    """Where Mesen2 battery-persists <rom_name>'s SRAM (raw slot bytes)."""
    return SAVES_DIR / (Path(rom_name).stem + ".srm")


def flush_srm(runner, neutral_rom):
    """Force the LIVE SRAM of the currently-loaded ROM out to its .srm.

    Mesen2 flushes battery SRAM only at ROM unload — the only way to
    materialize the .srm mid-process is to unload the game ROM by
    loading something else (the neutral ROM).
    """
    runner.load_rom(str(neutral_rom), run_seconds=0.2)


def virgin_srm(runner, rom_name, neutral_rom):
    """Guarantee the NEXT boot of <rom_name> starts from VIRGIN battery SRAM.

    A bare unlink of the .srm is NOT enough: the emulator is
    process-global, so if a previous test module left the game ROM
    loaded (with a save banked in live SRAM), the unload triggered by
    the NEXT load_rom would flush that SRAM and resurrect the file
    AFTER the delete. Order matters: load a neutral ROM FIRST (that
    unload flushes the .srm now, if the game ROM was live), THEN delete
    the file. The following load_rom of the game only unloads the
    neutral ROM and seeds SRAM from the missing file = power-on
    garbage, exactly like a real cart's first boot.
    """
    flush_srm(runner, neutral_rom)
    p = srm_path(rom_name)
    if p.exists():
        p.unlink()
