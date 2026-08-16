"""Per-rail GIF choreography — one drive per rail, each a narrated flight plan.

A scenario module is small and declarative:

    ROM        the build/<name>.sfc basename this drive belongs to
    CAPTURES   how many samples the take holds (x 50 ms = its real-time length)
    SETTLE     (optional) EMULATED frames of boot before recording starts
    WINDOW     (optional) keep only the densest N captures of the take
    PALETTE    (optional) `shared` (the format contract) or `perframe`
    make_drive()  returns the `drive(runner, i)` the recorder calls once per
               capture; it must advance record_gallery_clip.STEP frames

The recorder is `tools/record_gallery_clip.py`, and its
docstring is the format contract. Nothing here re-implements any of it; a
scenario only says WHAT TO DO WITH THE PAD, which is the half that is
genuinely per-rail. `tools/record_pres_gif.py` is the dispatcher.

TWO RULES THE DRIVES ARE WRITTEN AGAINST, both paid for already:

1. **Drive at full gameplay speed.** Playback is 1:1 real time, so a gentle
   "showcase" input reads as a frame-rate drop rather than as elegance — a
   gentle-rotation take of the split demo measured motion energy 109 against
   349 for a full-speed take and drew a "did the FPS crawl?" report
   (2026-07-19). Hold the throttle. Turn hard.

2. **Read the ROM's STATE; do not count frames to an event.** An atomic slide
   finishes after the button changes, and `take_screenshot` sits between
   steps, so a fixed plan drifts against the ROM's own tick: two earlier
   attempts produced a plausible GIF that never entered the town
   . Where a beat has an EVENT — a clamp, a scene
   id, a phase byte, a wipe — the drive waits on that byte. Where a beat is
   genuinely continuous (a heading sweeping at a constant rate) a count is
   honest, and the scenario says which it is using.

They live here rather than in the dispatcher for the reason `shot_<rail>.py`
is one file per rail: the interesting part of a capture is not the encoder,
it is WHY THESE BEATS, and that argument needs room next to the code.
"""
