# racer — the Mode 7 kart-racing rail

## What it is

A kart-style racer on the Mode 7 perspective floor: a first-party closed
circuit with kerbs and a start line, accelerate/coast physics with a steerable
camera and off-road drag (the map is collision ground truth — grass slows the
kart to a crawl), a fixed-screen kart sprite with lean frames, a sprite speed
bar, race music, pause, and a day-night cycle (per-scanline horizon tint +
flashing kerb lights). Runs at a locked 60 fps, including while steering —
the expensive perspective rebuild is paced across two frames.

| Button | Action |
|---|---|
| B | Accelerate (release to coast to a stop) |
| D-pad LEFT / RIGHT | Steer (the kart leans into the turn) |
| START | Pause / unpause (freeze-frame; music keeps playing) |

## What it teaches

- **The Mode 7 racing camera** — `sf_mode7_on` / `sf_mode7_perspective` /
  `sf_mode7_cam` (`lib/macros/sf_mode7.inc`) with the racing trapezoid, plus
  the sincos + `smul16` position integration on the 1024 px torus. Guide:
  [`docs/guides/mode7_racer.md`](../../docs/guides/mode7_racer.md).
- **Frame-budget engineering** — a full perspective rebuild measures 245,779
  master clocks (69% of a frame), so the MAIN LOOP spreads it across two
  frames with the engine's `pv_rebuild_pass1`/`_pass2` split entry points
  while the cheap origin re-anchor keeps motion 60 Hz smooth.
- **OBJ over Mode 7** — moving the OBJ name base out of the map's VRAM
  (`OBSEL`), and why the HUD is sprites (BG3 does not exist in Mode 7).
- **HDMA composition on all 8 channels** — matrix (CH5/6), 3-channel COLDATA
  day-night gradient (`sf_gradient_rgb`, CH3/4/7), and a hand-armed TM split
  (CH2) that reveals a real sky above the horizon.
- **Palette effects** — `sf_pal` / `sf_pal_cycle` (`lib/macros/sf_fx.inc`)
  flashing ONLY the kerb pair while the road and start line hold dedicated
  static CGRAM indices (`assets/make_track.py` authors the indices).
- **TAD audio** — the `lorom_tad_m7.cfg` link shape (Mode 7 map bank + audio
  banks), `sf_audio_init` / `sf_audio_tick` / `sf_music`.

## Three things to tweak

- `SPEED_CAP` (`main.asm`, tuning block) — top speed, 8.8 fixed point.
  Raising it makes the floor stream past faster and lights the speed bar
  sooner (`ACCEL` / `DECEL` sit next to it).
- `PV_S0_RACING` (`main.asm`, perspective block) — the far-scale. Bigger =
  the horizon row spans more map = a longer forward view; the whole
  trapezoid (`PV_*_RACING`) is the camera's character.
- `tile_color()` (`assets/make_track.py`) — the track itself. Any closed
  circuit drawn on the 128x128-tile grid works; regenerate with
  `PYTHONPATH=. python3 templates/racer/assets/make_track.py`, rebuild, and
  the new track is in the ROM.

## How it's verified

`make racer` builds `build/racer.sfc` (the `LDCFG:` sentinel selects
`lorom_tad_m7.cfg`). `tests/test_racer.py` boots it headless and gates the
rendered floor, sky, kart, speed bar, both steer directions, the 60 fps
loop rate under sustained steering, and the recorded music (WAV peak);
`tests/test_racer_daynight.py` gates the horizon gradient, the day-night
progression, and the kerbs-only palette cycle. Run one:

    python3 -m pytest tests/test_racer.py -q
