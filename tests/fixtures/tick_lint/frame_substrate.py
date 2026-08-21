"""Deliberately violating: the NTSC frame as a literal, and by name."""
FRAME_MC = 357368
PCT = 100.0 * 1234 / 357368
def budget(d):
    return d["frame"]["ntsc"]["mc_per_frame"]
