"""The frame geometry Mesen hands back — a fact about the MACHINE, not a rail.

Promoted here 2026-08-07 (earlier DX change) from the two per-rail
predictors that each stated it. It was booked as a promotion and called
"a ten-line change"; and re-booked after `tests/shp_predict.py`
became the THIRD file to state the same constants — at which point a follow-up
that keeps being re-booked is cheaper to do than to carry. The record notes
the scope.

WHAT IS HERE: only what is true of Mesen's SNES output, whatever ROM is
running. Nothing about a world size, a seam, a palette layout or a band list —
those are rail facts and belong to the rail's own predictor. The test for
whether a constant belongs here is "would it change if I pointed the harness
at a different ROM"; if yes, it does not.

WHERE THESE NUMBERS COME FROM, because a shared constant with no provenance is
worse than a duplicated one with it:

  * Mesen hands back a **256x239** PNG. The active picture is **224 lines**
    starting at PNG row **7**.
  * `realY` IS MESEN'S `_scanline`, WHICH IS NOT THE PICTURE ROW. Rendering is
    guarded by `_scanline > 0`, so the first rendered line is `_scanline == 1`
    and lands on PNG row `PICTURE_TOP`. `REAL_Y_BIAS` is that offset.
  * MEASURED, not argued: predicting every row of `split_h_matrix_demo`'s boot
    frame at seven candidate offsets mismatched 69/52/35/18/**0**/18/36 rows.
    `realY = picture_row + 1` is the only offset that describes the machine,
    and it agrees with the `_scanline > 0` guard.

**The modules that use these still RE-ASSERT them from the picture** — e.g.
`test_split_h_persp_demo.py::test_the_frame_geometry_is_the_one_this_predictor
_assumes` re-solves the offset by predicting the boot frame at six candidates
and requiring exactly one to mismatch zero rows. That is deliberate and must
not be dropped as "already shared": sharing a constant makes it consistent, it
does not make it true, and the whole point of the measurement above is that
this number was once fitted rather than known.
"""

# Mesen hands back 256x239. The active 224 lines start at PNG row 7.
PICTURE_TOP = 7
PICTURE_LINES = 224
FRAME_W = 256
FRAME_H = 239
REAL_Y_BIAS = 1                 # realY = picture row + 1 (measured; see above)


def png_row(picture_row: int) -> int:
    """PNG row of a picture scanline (0 = the first rendered line)."""
    return PICTURE_TOP + picture_row
