"""col_map's six required binding symbols, as falsify plants.

Carried over from the hand-rolled tools/falsify_col_map_binding.py, which
proves the same six gates and is kept beside this one. What this form buys
is the artifact check the hand-rolled script did not have: these plants
expect the BUILD to refuse, so `expect="build-fails"` and the harness
requires ca65 to name the missing symbol — a build that breaks on something
else is a PLANT failure, not a fired gate.

col_map takes includer-supplied symbols with NO DEFAULTS rather than a
parameterised `depends`, on the argument that "the undefined-symbol error is
the design review". That argument is worth nothing unless the errors arrive,
and arrive NAMING the symbol. This is the evidence.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
SCENE = SUPERFORGE / "game" / "microzero" / "scenes" / "race.asm"
ROM = SUPERFORGE / "build" / "microzero.sfc"

# (symbol, the exact binding line in race.asm, the words the .error must carry)
BINDINGS = [
    ("CM_WORLD_W_LOG2", "CM_WORLD_W_LOG2      = 9",
     "must define CM_WORLD_W_LOG2"),
    ("CM_WORLD_H_LOG2", "CM_WORLD_H_LOG2      = 9",
     "must define CM_WORLD_H_LOG2"),
    ("CM_WORLD_BLOB", "CM_WORLD_BLOB        = ::ES_R_WORLD_MAP_T0_ADDR",
     "must define CM_WORLD_BLOB "),
    ("CM_WORLD_BLOB_BANK", "CM_WORLD_BLOB_BANK   = ::ES_R_WORLD_MAP_T0_BANK",
     "must define CM_WORLD_BLOB_BANK"),
    ("CM_WORLD_BLOB_CHUNKS", "CM_WORLD_BLOB_CHUNKS = ::ES_R_WORLD_MAP_CHUNKS",
     "must define CM_WORLD_BLOB_CHUNKS"),
    ("CM_FLAGS", "CM_FLAGS             = ::col_flags_bin",
     "must define CM_FLAGS"),
]

PLANTS = [
    Plant(id=f"binding-{sym}",
          file=SCENE,
          old=line,
          new="; PLANT: binding omitted  " + line,
          artifact=ROM,
          build=["microzero"],
          tests=[],
          expect="build-fails",
          build_names=needle,
          why=f"a scene that forgets {sym} is the exact mistake the "
              f"no-defaults design bets on catching at assembly time; the "
              f"bet is only good if ca65 names the symbol rather than "
              f"failing three includes later with a range error")
    for sym, line, needle in BINDINGS
]
