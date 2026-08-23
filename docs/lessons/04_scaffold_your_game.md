# Lesson 4 — Scaffold your game

*Matches Try-it prompt 4. The task: a new rail under `game/` that composes
declared features, boots, renders its world, and carries your game's own state
— with every gap named rather than papered over. This is the step with the
most moving parts; the checklist below is the whole of it, and the gates
enumerate whatever you miss.*

**The copyable exemplar is `game/microzero`** — the smallest complete game.
Fork its shapes rather than inventing your own; its files are commented as
templates.

## 1. The file set

| file | job |
|---|---|
| `game/<name>/game.toml` | the composition: `globals = [...]`, one `[[scene]]` per scene with its `features`, `[[edge]]`s between scenes |
| `game/<name>/state.toml` | **your** game state, declared through the allocator: `[global]` for run-lifetime, `[scene.<id>]` for scene-scoped, `u8`/`u16`/arrays, `@dp` for hot bytes |
| `game/<name>/main.asm` | the ROM skeleton — copy microzero's: header defines, generated include, `NMI` → `sm_nmi_core`, the feature `.include`s, `text_dp_init`, the blob `.incbin` block |
| `game/<name>/scenes/<id>.asm` | one file per scene: enter / tick / exit inside a `.scope` |
| `engine/features/<name>_*/feature.toml` | your rail's own features — a `*_bg`, a `*_obj`, a `*_rom` blob dir, a logic kernel — each declaring its claims **and a `role`** |
| `tools/gen_<name>_assets.py` | the asset generator, if you have art (it is also your tests' oracle) |
| a Makefile block + `tests/test_<name>.py` | copy microzero's block; the test boots the ROM and reads rendered output |

**Roles**, because the census is generated from the tree: `feature` · `blob` ·
`companion` · `consumer` · `game_logic` · `fixture`. Your game's kernel is
`role = "game_logic"` — game code that lives under `engine/features/` only
because that is where the allocator looks. `race_logic` is the model.

## 2. State goes through the allocator — never a hand-picked byte

Declare it in `state.toml`, rebuild, and use the emitted `US_*` symbols. Scene
state is reused between scenes by construction. Growing a claim later is an
edit to the toml plus a rebuild — nothing else to touch. If you cannot express
an address as an emitted symbol, you are about to write the bug class this
repo exists to refuse (and `no_literals` will refuse it).

## 3. Build, and read what comes back

```bash
make <name>
```

Two good outcomes. **Allocation OK** — read
`build/<name>/allocation_report.txt`: the packed VRAM/CGRAM/OAM/HDMA layout,
per-scene register ownership, your state's placement, per-edge reload sizes.
It is documentation of your own game; keep it open while writing ASM. Or **a
refusal that names the collision** — a design answer at build time. Fix the
design (drop, shrink, or rescope a claim to one scene), not the gate.

**The ROM pack-order gotcha.** The allocator packs `rom` claims largest-first,
and your `.incbin` sites carry `.assert ^label = ES_R_<NAME>_BANK` (microzero
shows the pattern, `.sprintf` templates for bank-tiled blobs). When the link
refuses naming a drifted blob, the fix is to **move the `.segment "BANKn"`
lines to match the allocation report's packed order** — the assert is the
messenger, not the problem.

## 4. Registration: run the gate and follow the list

A new rail must be named at ten sites — Makefile lists (`.PHONY`,
gates, md5s, `test:`/`determinism:` prerequisites), `tests/conftest.py`'s two
map dicts, the landing gate's derived expected-image set, the freshness-guard
dict, and AGENTS.md's build block. **Do not memorize them.**

```bash
make rail-registered
```

names every site still missing — its exact location and what skipping it
costs. Satisfy the list, re-run until green. The one to respect most is the
pair `conftest.MAPS` **and** `conftest._SUBDIR_MAP`: missing only the second
is silent and misdirecting (the freshness guard checks the wrong map).

## 5. The register duty

This duty is owed by `engine/features/` DIRS, not by your rail as such — a
game whose scaffold adds feature dirs (its `*_bg` / `*_obj` / `*_rom`) owes
one pair per dir; a game composing only existing features owes none. Each
new dir owes `docs/09` two entries: its row in the **generated** census
(`make register-write` regenerates §3 — machine-owned, never hand-edit) and
a **hand-written** `supplies / serves` line in §3.1. `make register` refuses
until both exist and agree — regenerate the one, write the other.

## 6. Stub honestly

A scene your idea needs but you cannot build yet should still *compose*: give
it `bg_text` + `backdrop` and render a card naming the gap ("GAP: <the
mechanic>"). The composition still allocates, the gap is visible on every
boot, and declared-but-unwired state in `state.toml` marks the seam for
lesson 5. Name every gap in your report — a named gap is scaffolding; an
unnamed one is a surprise.

## 7. Close the step

Build green, `make rail-registered` green, `make register` green,
`width-check` clean, the test reading rendered output (VRAM words against your
generator's blob, CGRAM against the palette, glyphs on screen), and a render
of the booted world attached.

Your composition either allocates or the refusal names the collision — both
are answers.

One pacing note: iterate on YOUR rail with `make <game> && python3 -m pytest
tests/test_<game>*.py -q` — seconds, not minutes. The whole-tree surfaces
(`make gates`, `make bare-check`, and the meta-test modules that launch
them) are landing tools; reaching for one as an iteration loop costs you the
suite's full runtime per edit.
