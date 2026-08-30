"""Fit mill's BG1 ramps to the art instead of to a curve through it.

WHY THIS EXISTS. `mil`'s four ramps were built by interpolating swatches read
off the concept sheet — `_stretch(_anchors(SW_*), n)` — and the kit art was
then quantised onto them by nearest-entry. That places the entries along a 1-D
CURVE, and the art is a 3-D CLOUD around it: measured on the shipped tree, only
76 of 96 claimed CGRAM entries were ever drawn, and the cold ramp used 19 of
its 36. An 8bpp layer indexes CGRAM directly with no palette field, which means
the palette can be chosen FROM the art rather than the art fitted onto it — and
that is the difference between 8bpp buying addressing and 8bpp buying depth.

WHAT IT DOES. Per family, k-means over the source pixels the family owns, then
sorted by luminance so the ramp stays MONOTONE and `Wm(k)` / `Ml(k)` / `Br(k)`
keep meaning "k steps from dark to light" — the procedural painting indexes
them by hand and those indices must not change meaning.

Measured against the even-stretched ramps it replaces, weighted per-pixel
error: cold -81%, warm -49%, molten -93%, brass -57%, overall -74%.

WHY THE OUTPUT IS COMMITTED rather than computed at build time: the same
argument KIT_BOX carries. A build must not depend on a clustering pass agreeing
with itself run to run, and reading three large sheets at import would cost
every build. Regenerate deliberately:

    python3 tools/fit_mill_palette.py            # prints the block to paste

SEEDED, so the same tree gives the same palette.
"""
import random
import sys
from pathlib import Path

sys.argv = [sys.argv[0], "/tmp/_fit_scratch"]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_mill_assets as G                                  # noqa: E402
import kit_import as K                                       # noqa: E402
from PIL import Image                                        # noqa: E402

SEED = 7
STRIDE = 2                       # every 2nd pixel each way — 4x fewer, same cloud
ITERS = 14
WEIGHT = (2, 4, 1)               # the eye's, and map_to_palette's own weighting
FRINGE = 2                       # px of silhouette edge dropped: the key's halo

FAMILIES = [("SW_STEEL_COLD", G.SW_STEEL_COLD, G.N_COLD),
            ("SW_STEEL_WARM", G.SW_STEEL_WARM, G.N_WARM),
            ("SW_MOLTEN", G.SW_MOLTEN, G.N_MOLTEN),
            ("SW_BRASS", G.SW_BRASS, G.N_BRASS)]


def _exp(c):
    return tuple((v << 3) | (v >> 2) for v in c)


def _d2(p, q):
    return sum(WEIGHT[i] * (p[i] - q[i]) ** 2 for i in range(3))


def _is_key_hue(r, g, b):
    """On the KEY'S HUE AXIS: red and blue both up, green well down.

    Erosion alone does not finish the job. A halo on continuous-tone art is
    wider than any fixed erosion, and what survives is dark magenta — whose
    nearest anchor is the DARKEST MOLTEN one, because a dark purple is closer
    to a dark red than to any steel. So it does not scatter, it piles into one
    family and takes entries there.

    This is safe here for a reason particular to this art and not general:
    the four families are steel (neutral to blue), molten (red to white
    through orange) and brass (brown to gold), and NONE of them puts red and
    blue up together with green down. A deep molten red has b LOW and is not
    matched. Measured on the sheets it rejects 3.19% of opaque pixels, present
    in all fifteen assets — the signature of a halo, not of a feature.
    """
    return r > 48 and b > 48 and g < 0.60 * min(r, b)


def gather():
    """Every kit pixel, bucketed by the family whose anchors it is nearest.

    THE KEY FRINGE IS NOT ART, AND IT WILL TAKE ENTRIES IF YOU LET IT. The
    sheets are keyed on magenta and `kit_import.is_key` matches it loosely
    (g < 110, r > 150, b > 150) — loose enough for the grain, not loose enough
    for the HALO, because the sheets are continuous-tone and every asset's
    edge blends the key toward the art through values like (107, 8, 115) that
    no key test can claim without eating real pixels too.

    Snapping onto hand-picked ramps hid that: a fringe pixel simply landed on
    whatever entry was nearest. Fitting the palette TO the pixels does not
    hide it — the fringe is a dense, tight cluster and k-means rewards it with
    entries of its own. The first cut of this file spent ELEVEN of ninety-six
    that way, most of the middle of the molten ramp, so the hall's channel and
    the lobby's deck drew key bleed as though it were hot metal.

    So the fringe is removed geometrically rather than by colour: a pixel
    within FRINGE of a transparent one is an edge pixel and is not sampled.
    That costs a thin outline of genuine art at every silhouette, which is the
    right trade — those pixels are the least representative in the sheet.
    """
    anchors = [(n, [_exp(c) for c in G._anchors(sw)]) for n, sw, _ in FAMILIES]
    out = {n: [] for n, _, _ in FAMILIES}
    for name, (sheet, box) in G.KIT_BOX.items():
        im = K.key_to_alpha(Image.open(G.KIT / f"{sheet}.png").crop(box))
        px = im.load()
        w, h = im.size
        solid = [[px[x, y][3] != 0 for x in range(w)] for y in range(h)]
        keep = [[solid[y][x]
                 and all(solid[j][i]
                         for j in range(max(0, y - FRINGE), min(h, y + FRINGE + 1))
                         for i in range(max(0, x - FRINGE), min(w, x + FRINGE + 1)))
                 for x in range(w)] for y in range(h)]
        for y in range(0, im.size[1], STRIDE):
            for x in range(0, im.size[0], STRIDE):
                r, g, b, a = px[x, y]
                if not keep[y][x] or _is_key_hue(r, g, b):
                    continue
                fam = min(anchors, key=lambda f: min(_d2((r, g, b), q) for q in f[1]))
                out[fam[0]].append((r, g, b))
    return out


def kmeans(pts, k):
    """k centroids, seeded evenly through the SORTED cloud so the run is
    reproducible without depending on dict or file order."""
    pts = sorted(pts)
    cent = [list(pts[i * len(pts) // k]) for i in range(k)]
    for _ in range(ITERS):
        acc = [[0, 0, 0, 0] for _ in range(k)]
        for p in pts:
            j = min(range(k), key=lambda j: _d2(p, cent[j]))
            for t in range(3):
                acc[j][t] += p[t]
            acc[j][3] += 1
        for j in range(k):
            if acc[j][3]:
                cent[j] = [acc[j][t] / acc[j][3] for t in range(3)]
    return cent


def main():
    random.seed(SEED)
    buckets = gather()
    print("# GENERATED by tools/fit_mill_palette.py — do not hand-edit.")
    print("# Per-family k-means over the kit's own pixels, sorted by luminance so")
    print("# the ramp stays monotone and Wm/Ml/Br keep their index meaning.")
    for name, sw, n in FAMILIES:
        pts = buckets[name]
        cent = kmeans(pts, n)
        # back to BGR555, keeping exactly n entries: the indices are addressed by
        # hand in the painter and must all stay valid, so duplicates after
        # rounding are kept rather than collapsed — a family that cannot fill
        # its ramp is saying so.
        ramp = [tuple(min(31, max(0, round(v / 8))) for v in c) for c in cent]
        ramp.sort(key=lambda c: 2 * c[0] + 4 * c[1] + c[2])
        err_old = sum(min(_d2(p, _exp(q)) for q in G._stretch(G._anchors(sw), n))
                      for p in pts) / len(pts)
        err_new = sum(min(_d2(p, _exp(q)) for q in ramp) for p in pts) / len(pts)
        print(f"# {name}: {len(pts)} px, {len(set(ramp))} distinct of {n}; "
              f"error {err_old:.0f} -> {err_new:.0f} ({100*(err_new-err_old)/err_old:+.0f}%)")
        body = ", ".join(f"({c[0]},{c[1]},{c[2]})" for c in ramp)
        print(f"FIT_{name.replace('SW_', '')} = [{body}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
