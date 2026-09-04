"""mill_direct — the same hall, drawn without a palette.

THE VARIANT IS THE SAME ROM WITH ONE DECLARATION DIFFERENT, so it is the same
CLIP with one ROM different: this module is `mill`'s drive, verbatim, pointed
at `build/mill_direct.sfc`. Every wait in it reads the ROM's own state, and
the variant's state is the shipped rail's — same scenes, same geometry, same
lift, same phase table — so a scenario of its own would be a second copy of a
choreography that cannot diverge without the variant having stopped being one.

WHAT THE PAIR SHOWS, and why it is worth a second clip rather than a note.
`mill.sfc` draws BG1 out of 96 CGRAM entries fitted to this exact picture by a
weighted k-means over the on-screen cloud. `mill_direct.sfc` draws the same
BG1 with `direct_color` declared — CGWSEL bit 0, `[[claims.video]]` — so the
8bpp pixel IS the colour: three bits of red, three of green, two of blue, each
extended one bit by the tilemap entry's palette field (Mesen2 SnesPpu.cpp
GetRgbColor, the `bpp == 8 && directColorMode` arm). No palette is consulted
and none is uploaded.

Measured between the two clips' own frames: 64-80% of the picture differs, by
a median of 9-16 units of 255 on its worst channel. The fit wins nearly
everywhere, which is the honest result — what direct colour buys is not
fidelity but that it needs no fit, and no CGRAM, at all.

IT IS ON THE SHOWCASE LIST AND IT IS NOT A RAIL. `record_pres_gif.RAILS` is
named for the rails it was built from, and this is the first entry that has no
`game/` directory of its own — `rail_registered` does not see it and should
not. It is on the list because a clip nothing refreshes goes stale in silence,
and the README cites this one.
"""
from tools.gif_scenarios.mill import CAPTURES, make_drive        # noqa: F401

ROM = "mill_direct"
