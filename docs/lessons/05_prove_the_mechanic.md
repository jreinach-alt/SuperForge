# Lesson 5 — Prove the mechanic

*Matches Try-it prompt 5. The task: the first playable slice of your core
mechanic — input, motion, one collision-or-feedback response — **held at
60 fps and proven by measurement**. Read
[`.claude/skills/test-authoring.md`](../../.claude/skills/test-authoring.md)
before writing the first test; this lesson adds the performance recipes on
top of it.*

## The ground rule, restated once

Every assertion reads a rendered **output region** — VRAM, OAM, CGRAM bytes
or screenshot pixels — never a program variable that "should" reflect it. A
proxy-variable test passes while the feature is silently broken, which is
worse than no test. Addresses come from `build/<rail>/symbol_map.json`, never
a literal.

## The 60 fps witness: zero dropped ticks over the worst case

The library's cadence proof, shipped in
`tests/test_mode7_flight.py::test_the_join_fits_its_frame_under_the_worst_case_input`.
The mechanism: your main loop's tick runs once per frame *when the work
fits*; if a frame overruns, `sm_frame_sync` parks the loop on the next NMI,
so the tick runs one fewer time than the hardware frame counter advanced —
and any state word the tick moves exactly once per tick **repeats a value**.
Zero repeats over the window *is* the statement "every frame's work fit its
frame". Extracted:

```python
tick = _sym("US_TICKS")["start"]            # a word YOUR tick moves once per tick
worst = {"right": True, "b": True}          # the heaviest input your mechanic takes
with Machine(str(ROM)) as m:
    m.advance(BOOT)
    repeats, prev = 0, m.read_u16(W, tick)
    for _ in range(240):
        m.advance(1, pad1=worst)
        cur = m.read_u16(W, tick)
        repeats += (cur == prev)
        prev = cur
assert repeats == 0, f"{repeats} of 240 frames dropped a tick"
```

Three ingredients decide whether this is a proof or a ritual:

1. **The counter.** Any per-tick word works — a countdown, an animation
   clock; if nothing in your state moves every tick, declare `ticks = "u16"`
   in `state.toml` and increment it once per tick.
2. **The worst case.** The script must trigger your mechanic's heaviest
   per-frame work, held for the whole window — max speed *and* turning every
   frame *and* the feedback path firing. A witness over idle input proves
   idle.
3. **Non-vacuity.** Assert that the window really exercised the mechanic —
   some output region changed inside it. A witness that would also pass on a
   frozen ROM is vacuous.

## Measuring a routine's cost, the way the library does

Never estimate a cycle count; both house methods read the emulator's master
clock (frame = 357,368 mc; worst-case 60 fps frame = 305,348 mc — measured
pins in `allocator/substrate.toml`, re-checked by `make measure`).

**The write-breakpoint stopwatch** —
`tests/test_platformer.py::test_the_parallax_rebuild_costs_what_it_claims`
and its `_clock_at_write` helper. Set a write breakpoint on the first byte
your routine writes, note the master clock; same on its last byte; the delta
IS the routine, measured on the shipping binary. Care it takes, all three
learned the hard way in that file: take `min()` over several samples (a
sample that caught the NMI hook carries its cost too); treat the **write
counter as the oracle** — a reported break with the counter unmoved is a
thread pause wearing a breakpoint's clothes; and put the breakpoint in the
right memory space (`SnesWorkRam` offset — a long store to `$7E....` never
matches a bank-0 mirror address).

**The in-ROM latch stamp** — when you want the cost of *every* frame of a
long lockstep drive, breakpoints are the wrong tool; have the ROM stamp the
PPU's H/V latch before and after the routine into a claimed state block, and
read both pairs back per frame: cost = Δ(v·1,364 + h·4) mod 357,368.
`tests/test_mode7_flight.py` (`_join_mc`, the `ES_M7F_COST` claim) is the
worked example — that is how the flight rail's join carries a per-frame cost
ceiling *inside* the tick-witness loop.

Then write the assertion as a **regression band around the measured figure**
("measured ~X mc; ceiling guards against a regression of a different order")
— not as a hope. Print the number; it belongs in your report.

## Captures land on an absolute frame

When the picture is the assertion, the frame must be *named*, not "roughly
after N":

- **Lockstep `Machine`** (the default): every `advance(n)` is exact by
  construction, so any capture is an absolute frame. Budget the shot itself —
  **a screenshot costs one emulated frame** — or a picture pair meant to sit
  N frames apart drifts by one (the skill's "Capture facts" carries this plus
  the PNG overscan offset and the 5→8-bit palette expansion).
- **Legacy `MesenRunner` modules**: use `boot_to_frame(rom, N)` — it steps
  the last stretch so every host photographs frame N exactly;
  `boot_rom(frames=N)` lands on ≥ N and is not a capture primitive.

## Done looks like

Tests named for what they prove, each reading an output region; the state
cycle driven whole (both directions and the idle, per the skill); the tick
witness green over the true worst case with its non-vacuity guard; the
mechanic's cost on the record as a measured number with a band around it; and
fresh renders of the mechanic working, captured on named frames from the
verified binary.
