# `vendor/probe_ref` — reference sources for the CPU calibration probe

Everything `probe_cpu` needs in order to assemble, frozen. `probe_cpu` is the
CPU-budget probe: an instrumented build of a complete Mode 7 driving scene,
measured on the cycle-accurate emulator to produce this project's substrate
pins (`allocator/substrate.toml`, `allocator/pin_budgets.py`).

The scene is measured rather than estimated because the pins have to describe
a real frame's worth of work — a full tick with streaming, sprites, HDMA and
audio all live — not a synthetic loop. `src/probe_scene_ref.asm` is that scene,
unmodified apart from the SLHV latch rings the probe inserts in order to read
the cycle counters.

These files live here so the repository builds with nothing else on disk.

## Not all of this is ours — three files are CC BY 4.0

Most of this directory is first-party. **Three files are not**, and they carry
an attribution obligation:

| file | what it is |
|---|---|
| `inc/mode7_diz_ztable.inc` | the `pv_ztable` reciprocal LUT, **verbatim** from `dizworld.s` |
| `inc/mode7_diz_math.asm` | six math routines, **modified transliteration** |
| `src/probe_scene_ref.asm` | its `pv_*` perspective routines, same |

(c) Brad Smith (rainwarrior), https://rainwarrior.ca — **CC BY 4.0**,
https://creativecommons.org/licenses/by/4.0/. Each file carries its own
notice; do not strip them. `build/probe_cpu.sfc` and `build/probe_cpu_step.sfc`
embed this code and must credit Brad Smith. No `engine/` feature and no
`game/` rail links any of it. Consolidated attribution: `NOTICE`.

## Layout — it mirrors how ca65 resolves each kind of reference

| path | why it is shaped this way |
|---|---|
| `inc/` | the 20 `.include` targets, **flat**. ca65 finds these by basename on the `-I` path, so one directory serves all of them. |
| `assets/racing/` | the 13 `.incbin` targets, **path-preserved**. `.incbin` lines name `assets/racing/…` literally and resolve against `--bin-include-dir`, so that prefix has to survive. |
| `lorom_512k.cfg` | the linker config. |
| `src/probe_scene_ref.asm` | the un-instrumented scene, kept so `make_probe_cpu.py` can re-derive the probe from it. |

Total 33 assembler dependencies + the linker config + the derivation source.

## Two things that will bite you if you touch this

1. **`lorom_512k.cfg` here is NOT `vendor/rom/lorom_512k.cfg`.** They differ
   materially: segment names `BANK10..BANK15` vs `BANKA..BANKF`, an extra
   `SRAM`/`SRAMDATA` segment, and `define = yes` on the bank segments. The
   probe needs *this* one. Aliasing them produces a ROM that links cleanly and
   is wrong.

2. **`inc/sky_midday_gradient.inc` cannot be regenerated.** It is a committed
   artifact with no recipe anywhere — do not delete it expecting a rule to
   rebuild it.

## Updating this snapshot

Don't, in the normal case — this is frozen reference. If the scene ever does
change and the pins need re-deriving, re-run `make_probe_cpu.py` and
re-measure. The dependency list is derivable from the probe itself:

```bash
grep -o '\.incbin "[^"]*"\|\.include "[^"]*"' \
  vendor/probes/probe_cpu_ref.asm | sed 's/.*"\(.*\)"/\1/' | sort -u
```

The no-literals gate deliberately does **not** apply to anything in here: this
is measurement scaffolding, and no engine or game code links it.
