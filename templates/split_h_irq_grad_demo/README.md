# split_h_irq_grad_demo — seam-IRQ origin frees a channel for a gradient

## What it is

A two-band Mode-7 split that stamps band 2's camera origin from a **seam-scanline
IRQ** (firing a pre-armed GP-DMA pair) instead of a dedicated origin HDMA channel
pair — and then spends one of the two channels that frees on a real per-scanline
COLDATA gradient over the floor. It is the composed rail that the `seam_irq_trial`
cold-start rail was built to de-risk: the IRQ origin mechanism is proven there
byte-identical to an HDMA-origin control, and here it earns its keep.

| Input | Action |
|---|---|
| — | none; autonomous. Both cameras pan on their own at different speeds. |

The default build moves camera 1 at +1 px/frame and camera 2 at +2 (different
speeds are the "independent driver" signal). The variant builds are the test
controls: `-DFREEZE` holds both still, `-DNO_GRAD` drops the gradient,
`-DHDMA_ORIGIN` renders through the classic origin pair (byte-identical to the
frozen no-gradient IRQ build), and `-DIRQ_INTERLEAVE` deliberately violates the
write-twice latch discipline to make the corruption visible.

## What it teaches

- **Spending a freed channel** — the 2-player split family burns a channel pair on
  the per-band origin splice, so the 256-pose rail has all six allocator channels
  busy. Moving band 2's origin to the seam IRQ frees both; this demo uses 3
  channels (2 matrix + 1 gradient) and leaves 3 free.
- **A one-byte-per-line COLDATA gradient** — the plane-select trick (`$E0 | v`)
  sets R=G=B in a single `$2132` write, so a 224-line ramp is a ~227-byte
  repeat-mode HDMA table, built at boot in WRAM (no committed binary). Fixed-color
  ADD on BG1 via `CGWSEL`/`CGADSUB`; every world colour keeps BLUE=0, so the
  rendered blue channel is exactly the gradient — a checker-immune test signal.
- **The seam-IRQ origin mechanism and its `wai` hazard** — gating the loop's `wai`
  on the NMI counter so a seam-IRQ wake doesn't write tables mid-frame; the
  write-twice `ValueLatch` discipline (`DMAP $03` byte order). Deep dive:
  [`docs/guides/split_h.md`](../../docs/guides/split_h.md); the isolated proof is
  [`templates/seam_irq_trial`](../seam_irq_trial/README.md).

## Three things to tweak

All three live in [`main.asm`](main.asm):

1. **`SEAM`** (default 112) — the seam scanline (and the IRQ's `VTIME`). Band 1 is
   content lines `0..SEAM-1`, band 2 the rest; move it to resize the bands.
2. **The Y-pan speeds** (`game_loop`, the `POS1Y`/`POS2Y` `inc a` block) — camera
   1 advances once, camera 2 twice per frame. Change the increments to alter each
   band's scroll rate.
3. **`P2_X0`** (default 768) — camera 2's world X, on the warm stripe. Move it
   toward 512 and band 2 drifts onto the cool stripe.

## How it's verified

```bash
make split_h_irq_grad_demo
bash templates/split_h_irq_grad_demo/build_split_h_irq_grad_variants.sh   # the controls
python -m pytest tests/test_split_h_irq_grad_demo.py -q
```

[`tests/test_split_h_irq_grad_demo.py`](../../tests/test_split_h_irq_grad_demo.py)
reads the rendered framebuffer and the WRAM debug mirrors: the frozen no-gradient
IRQ build is byte-identical to the `-DHDMA_ORIGIN` control, the blue channel ramps
monotonically down the floor (and is flat on `-DNO_GRAD`), the `-DIRQ_INTERLEAVE`
build tears the band, and the loop cadence holds at +1/+1 while the raw wake
counter shows ~2 wakes per frame. To watch it, boot
`build/split_h_irq_grad_demo.sfc` in any SNES emulator (or drive it from
`MesenRunner`, as the tests do).
