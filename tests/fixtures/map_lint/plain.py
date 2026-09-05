"""Planted violations for tools/map_lint.py. A FIXTURE, not a test.

Each case is padded apart because the override window is +-3 lines and will
otherwise reach over a neighbour and silence a case its reason was never
written for — which it did on this file's first draft, suppressing three of
the four plants and making the lint look broken.
"""


def probe(m, V, MAP):
    m.read_bytes(V, 0x3C00, 2048)          # PLANT 1: a literal base




    m.read_bytes(V, 0, 512)                # a region ORIGIN: must not fire




    m.read_bytes(V, MAP["aur_map2"], 2048)  # derived: must not fire




    m.read_bytes(V, 0x1000 * 2, 64)        # PLANT 2: folded from literals




    m.read_u16(V, 0x0200)                  # PLANT 3: a different accessor




    m.read_bytes(V, 0x0200, 4)
    # MAP: ok — a real override, with a reason: must not fire




    m.read_bytes(V, 0x4000, 4)
    # MAP: ok
    # ...PLANT 4 is the BARE override above; the address it sits on is
    #    reported too, because a bare stamp does not silence what it sits on
