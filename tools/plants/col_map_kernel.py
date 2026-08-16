"""Two col_map kernel defects, carried over from tools/falsify_col_map.py.

These are `expect="test-red"` plants — the build succeeds and a named
assertion must go red — which is the shape where the harness's ARTIFACT-MD5
check earns its keep: without it, a plant that failed to reach
build/probe_colmap.sfc would present as a green test, i.e. as "the gate is
fine".

Deliberately a SMALL port. tools/falsify_col_map.py carries thirteen plants
and their accumulated commentary (P12 and P13 in particular record two
assertions that were measured GREEN against real defects and then
strengthened); that script stays the record. These two are here to prove the
harness fits the shape, not to replace it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from falsify import Plant                                   # noqa: E402

SUPERFORGE = Path(__file__).resolve().parent.parent.parent
KERNEL = SUPERFORGE / "engine" / "features" / "col_map" / "col_map.asm"
PROBE = SUPERFORGE / "build" / "probe_colmap.sfc"
T1 = ("tests/test_col_map.py::"
      "test_t1_col_map_matches_the_world_blob_across_every_chunk_bank")

PLANTS = [
    Plant(id="kernel-bank-term-dropped",
          file=KERNEL,
          old="""    lda z:CM_T0
    .repeat CM_CHUNK_SHIFT
        lsr                     ; ty >> log2(rows per chunk) = the chunk index
    .endrepeat
    clc
    adc #CM_WORLD_BLOB_BANK""",
          new="""    lda z:CM_T0
    .repeat CM_CHUNK_SHIFT
        lsr                     ; ty >> log2(rows per chunk) = the chunk index
    .endrepeat
    and #0                      ; PLANT: always chunk 0
    clc
    adc #CM_WORLD_BLOB_BANK""",
          artifact=PROBE,
          build=["probe-colmap"],
          tests=[T1],
          why="every query with ty >= 64 reads the wrong world row. A "
              "realistic defect: dropping a chunk term is what a 'simplify "
              "the index maths' change looks like"),

    Plant(id="kernel-axes-transposed",
          file=KERNEL,
          old="""    lda z:CM_PY
    lsr
    lsr
    lsr
    and #(CM_H - 1)             ; ty = (py >> 3) mod H — the world is a torus""",
          new="""    lda z:CM_PX                 ; PLANT: transpose the world
    lsr
    lsr
    lsr
    and #(CM_H - 1)             ; ty = (py >> 3) mod H — the world is a torus""",
          artifact=PROBE,
          build=["probe-colmap"],
          tests=[T1],
          why="x/y swapped at the entry — the classic copy-paste in a two-"
              "axis index. The octagon is not symmetric under transpose on "
              "the start spoke, so T1 can see it"),
]
