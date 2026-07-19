# seam_irq_trial — the seam-scanline IRQ trial

## What it is

A trial rail that proves, in isolation, a Mode-7 split where band 2's camera
origin is stamped by a **seam-scanline IRQ firing a pre-armed GP-DMA pair**,
rather than by the classic origin HDMA channel pair. It exists to de-risk two
hardware unknowns before the composed `split_h_irq_grad_demo` template relies on
them:

- **H1 — `wai` wakes on the IRQ too.** With a mid-frame IRQ armed, the classic
  wait-for-VBlank loop also returns at the seam; the loop here gates on the NMI
  counter, and a raw wake counter shows the hazard is real and the gate closes it.
- **H2 — the seam write window.** The DMA must land after band 1's last content
  line is flushed and before band 2's first — a timing model verified against the
  emulator core source and corrected by on-emulator measurement.

| Input | Action |
|---|---|
| — | none; autonomous. The scene is frozen; the seam IRQ fires once per frame. |

The frozen scene puts camera 1 over a cool (green) stripe and camera 2 over a warm
(red) stripe, so band 2's red is the "independent origin" signal. The variant
builds are the test controls: `-DHDMA_ORIGIN` renders the same scene through the
classic origin pair (must be byte-identical to the default), `-DMISTIME` mis-times
the fire to corrupt the band (non-vacuity), and `-DHV` proves an H+V trigger
renders identically through the same HBlank spin gate.

## What it teaches

- **A seam IRQ + pre-armed GP-DMA** as an alternative to origin HDMA — arming
  CH0/CH1 as `DMAP $03` (write-twice) GP-DMA at boot, then firing both with one
  `MDMAEN` write from the IRQ handler, re-arming `A1T`/`DAS` each VBlank (a GP-DMA
  fire consumes them).
- **The Mode-7 write-twice ValueLatch discipline** — all `$211B-$2120` registers
  share one latch, so each register's lo/hi bytes must be written back-to-back;
  `DMAP $03` delivers exactly that order.
- **HBlank-flag spin-gating an IRQ fire** so it always lands after the line's HDMA
  transfer, independent of the trigger's exact dot.
- The engine's IRQ opt-in (`SF_IRQ_VECTOR` + `sf_irq.inc`), the HDMA channel
  allocator, and INDIRECT-mode matrix streaming shared with the 2-player rail.
  Deep dive on the split family: [`docs/guides/split_h.md`](../../docs/guides/split_h.md).

## Three things to tweak

All three live in [`main.asm`](main.asm):

1. **`SEAM`** (default 112) — the seam scanline. Band 1 is lines `0..SEAM-1`, band
   2 the rest; the V-IRQ `VTIME` is derived from it, so moving it moves where the
   camera switches.
2. **`P2_X0`** (default 768) — camera 2's world X, centred on the warm stripe. Move
   it toward 512 and band 2 drifts onto the cool stripe, so its red fades.
3. **`COLOR_WARM_LIGHT`** (default `$03FF`) — the bright warm checker colour
   (15-bit BGR). Change it to recolour band 2's stripe.

## How it's verified

```bash
make seam_irq_trial
bash templates/seam_irq_trial/build_seam_irq_trial_variants.sh   # the control ROMs
python -m pytest tests/test_seam_irq_trial.py -q
```

[`tests/test_seam_irq_trial.py`](../../tests/test_seam_irq_trial.py) reads the
rendered framebuffer and the WRAM debug mirrors: the IRQ build is byte-identical to
the `-DHDMA_ORIGIN` control, the `-DMISTIME` build corrupts the expected band
(non-vacuity), `-DHV` matches the default, and the loop-cadence gate holds at
+1/+1 while the raw wake counter shows ~2 wakes per frame. To watch it, boot
`build/seam_irq_trial.sfc` in any SNES emulator (or drive it from `MesenRunner`,
as the tests do).
