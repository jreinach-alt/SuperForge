"""write_on — "The End", as a pen path and the coverage it lays down.

=============================================================================
WHY THE LETTERFORMS ARE TRACED AND NOT AUTHORED
=============================================================================
Four hand-cut passes at these letters produced four different misreadings.
The reason was one shape: a cursive capital T is a near-horizontal BAR with a
steep riser CROSSING it, and every curve guessed from memory drew a stem with
a peak instead — which is an N. So the shapes come from a traced centreline
of the reference (`vendor/art/the_end/`), and this module's job is only to
give that trace a HAND and a NIB.

=============================================================================
THE TRACE IS A GRAPH, NOT A SEQUENCE
=============================================================================
It arrives as 23 polyline fragments in no order. Its junction degrees say
what the writing hand actually did: twelve nodes of odd degree, so no single
unbroken trail covers it and six is the fewest that can — and six of those
nodes have degree ONE, which are exactly the free terminals visible in the
reference (the entry tip, the T's oval tail, the T's stem foot, the E's tail,
the n's head, the exit tip). That is a property of the script, not a defect
in the trace.

So each trail is begun at a free terminal, and at every junction the walk
CARRIES ON — taking the continuation that bends least, because that is what
a hand does where a script crosses itself. Greedy nearest-endpoint chaining
does not do this: it takes whichever stub is closest and strands the rest,
which on the first attempt wrote the exit swash before the h.
"""
import math
import re
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "vendor" / "art" / "the_end" \
    / "the_end_traced_strokes.svg"

JOIN_TOL = 26.0          # px, in the trace's own 1672x941 space
BASELINE = 522.0         # ...measured off the image it traces, by column scan
XHEIGHT = 52.0
ORIGIN_X = 624.0         # the T's crossing, which is where x = 0 is put

XH = 8.2                 # x-height on screen, in pixels
PENW = 1.45              # MONOLINE: round, ONE weight throughout. The
                         #   reference runs 9 px of stroke against a 52 px
                         #   x-height and this is that same 0.17 ratio.
BASE = (93.0, 216.5)     # where the baseline sits on the 256x224 screen
FRAMES = 70              # how long the pen takes

# The word is 25 x-heights wide and 3.8 tall — the reference's proportions,
# not a choice — which at this size lands it inside the black band under the
# cliff with a couple of pixels to spare on every side.


def _load():
    out = []
    for d in re.findall(r'<path[^>]*\bd="([^"]+)"', SRC.read_text()):
        pts = [(float(a), float(b)) for a, b in
               re.findall(r"[ML]\s*(-?[\d.]+)[ ,]+(-?[\d.]+)", d)]
        if len(pts) >= 2:
            out.append(pts)
    return out


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _dir(poly, at_end):
    """Unit direction the pen travels as it LEAVES this end of poly."""
    p = poly[::-1] if at_end else poly
    a = p[0]
    for b in p[1:]:
        d = _dist(a, b)
        if d > 4.0:
            return ((b[0] - a[0]) / d, (b[1] - a[1]) / d)
    b = p[-1]
    d = _dist(a, b) or 1.0
    return ((b[0] - a[0]) / d, (b[1] - a[1]) / d)


def _nodes(frags, tol=JOIN_TOL):
    pts, ends = [], []
    for f in frags:
        e = []
        for p in (f[0], f[-1]):
            for i, q in enumerate(pts):
                if _dist(p, q) <= tol:
                    e.append(i)
                    break
            else:
                pts.append(p)
                e.append(len(pts) - 1)
        ends.append(tuple(e))
    return pts, ends


def order(frags):
    """Walk the fragments as a hand would; return runs, left to right."""
    pts, ends = _nodes(frags)
    used = [False] * len(frags)

    def at(node):
        return [i for i, (a, b) in enumerate(ends)
                if not used[i] and (a == node or b == node)]

    runs = []
    while not all(used):
        cand = [n for n in range(len(pts)) if at(n)]
        odd = [n for n in cand if len(at(n)) % 2] or cand
        node = min(odd, key=lambda n: pts[n][0])
        run, hd = [], None
        while True:
            here = at(node)
            if not here:
                break
            best = bi = brev = None
            for i in here:
                rev = ends[i][1] == node and ends[i][0] != node
                f = frags[i][::-1] if rev else frags[i]
                o = _dir(f, at_end=False)
                bend = 1.0 if hd is None else hd[0] * o[0] + hd[1] * o[1]
                key = (-round(bend, 3), len(f))
                if best is None or key < best:
                    best, bi, brev = key, i, rev
            f = frags[bi][::-1] if brev else frags[bi]
            used[bi] = True
            run.extend(f if not run else f[1:])
            hd = _dir(f, at_end=True)
            node = ends[bi][0] if brev else ends[bi][1]
        if run:
            runs.append(run)
    runs.sort(key=lambda r: r[0][0])
    return runs


def resample(poly, step):
    """Even spacing, so the write-on advances at a constant speed."""
    out = [poly[0]]
    carry = 0.0
    for a, b in zip(poly, poly[1:]):
        seg = _dist(a, b)
        if seg <= 1e-9:
            continue
        t = step - carry
        while t <= seg:
            out.append((a[0] + (b[0] - a[0]) * t / seg,
                        a[1] + (b[1] - a[1]) * t / seg))
            t += step
        carry = (carry + seg) % step
    out.append(poly[-1])
    return out


def runs():
    """The pen path in SCREEN pixels, in the order the hand draws it."""
    s = XH / XHEIGHT
    step = 0.34 / s
    return [[(BASE[0] + (x - ORIGIN_X) * s, BASE[1] - (BASELINE - y) * s)
             for x, y in resample(r, step)] for r in order(_load())]


def ink(w=256, h=224):
    """-> cov[y][x] (0..1), tim[y][x] (pen parameter 0..1).

    A ROUND pen of constant width, stamped as a disc at every sample, with
    coverage accumulated as a MAXIMUM rather than a sum — so the places where
    the script crosses itself (the T, the d's loop, the E's waist) do not
    build a bright knot where they overlap.
    """
    cov = [[0.0] * w for _ in range(h)]
    tim = [[None] * w for _ in range(h)]
    rs = runs()
    n_all = sum(len(r) for r in rs)
    R = PENW / 2.0
    seen = 0
    for run in rs:
        for (x, y) in run:
            seen += 1
            t = seen / n_all
            for yy in range(int(y - R - 1), int(y + R + 2)):
                for xx in range(int(x - R - 1), int(x + R + 2)):
                    if not (0 <= xx < w and 0 <= yy < h):
                        continue
                    d = math.hypot(xx + 0.5 - x, yy + 0.5 - y)
                    a = max(0.0, min(1.0, (R + 0.55 - d) / 1.10))
                    if a <= 0.0:
                        continue
                    if a > cov[yy][xx]:
                        cov[yy][xx] = a
                    if tim[yy][xx] is None or t < tim[yy][xx]:
                        tim[yy][xx] = t
    return cov, tim
