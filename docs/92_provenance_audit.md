# 92 — Provenance audit: what in this tree is not ours, and how that was established

> Status: RECORD — the audit `LICENSE` and `NOTICE` were written against, 2026-08-16

This repository vendors third-party assets, so `NOTICE` could not be a file
copy — it needed a real provenance audit. This is that audit. `LICENSE` and
`NOTICE` are its output; this file is its working.

The licence choice itself was not open here — zlib for first-party content,
per component. What was open is **which components are first-party at all**,
and the answer had to be established rather than transcribed.

---

## 1. The rule this audit had to obey

CLAUDE.md's second primary-source rule names the exact trap:

> *An asset's provenance taken from a licence its own author wrote* — one of
> three assertions in one session that were wrong this way.

So the discipline here is: **a `LICENSE`, `README` or header sitting beside an
artifact is a claim about that artifact, and a claim is not evidence.** Every
row in `NOTICE` had to reach one of these instead:

| evidence class | what it proves | used for |
|---|---|---|
| **regeneration** | the committed bytes are the deterministic output of a generator in this tree, from no third-party input | first-party verdicts |
| **byte-match to the upstream artifact** | the vendored copy is what it claims to be | verbatim-vendoring verdicts |
| **the upstream's own grant, fetched** | the licence is what the row says | licence verdicts |
| **structural reachability** | a file cannot enter a ROM, because nothing reads it | scoping an obligation |
| **numeric non-derivation** | our data is not a copy or resample of theirs | the dizworld trace |

A licence *grant written by the rights holder on their own work* is a
different thing from a *provenance claim*, and is primary: an SPDX header in
an upstream file, or the licence sentence on an author's own page, is the
grant itself. The trap is the third-party's-provenance-asserted-by-the-user
case, and this audit keeps the two apart.

---

## 2. Method

1. Swept every tracked file that is not obviously prose or first-party source:
   `git ls-files | grep -vE '\.(asm|py|md|toml|inc|cfg|json|yml|sh)$'` — 1,363
   tracked files at audit start, ~250 of them binary-ish.
2. Classified by directory, then traced each class to a primary source.
3. For generated artifacts: found the generator, re-ran it, diffed.
4. For vendored artifacts: hashed against the upstream file or pack zip.
5. For licences: fetched the upstream grant where the network allowed, and
   said so plainly where it did not.
6. For the dizworld question: located every dizworld-derived file, then tested
   numerically whether any Mode 7 data generated in this tree derives from it.

---

## 3. Artifact classes examined, and the verdict on each

| class | verdict | evidence |
|---|---|---|
| `allocator/`, `engine/`, `game/`, `tools/`, `tests/`, `Makefile` | **first-party** | authored here; the only external-origin markers are hardware-fact citations to Mesen2 source and `fullsnes`, which restate behaviour in our own words (`allocator/schemas.py:314,333`; `engine/features/shg_grad/shg_grad.asm:10`) |
| `docs/` prose | **first-party** | authored here |
| `docs/img/*.png`, `*.gif` | **first-party captures** | the stills are exactly 256×239 — Mesen2's SNES capture geometry — and the animated clips are built by `tools/record_gallery_clip.py` and its siblings from frames of that shape. Note the capture/subject split `LICENSE` states: the captures are ours, but any shot of a rail built on a vendored pack pictures that pack's pixels (§5.1) |
| `assets/audio/samples/*.wav` (4) | **first-party, PROVEN** | `python3 tools/gen_audio_samples.py <dir>` reproduces all four **byte-for-byte** (sha256 equal). No external sample material |
| `assets/audio/mml/`, `sound-effects.txt`, `slice_b.terrificaudio` (3) | **first-party** | authored here |
| `assets/audio/export/*` (3) | **third-party embedded** | the `.asm` wrapper carries `SPDX-License-Identifier: Unlicense`; the `.bin` embeds TAD's SPC700 loader (116 B) + driver (3,218 B), zlib — the offsets are declared by the wrapper's own `.export` lines |
| `vendor/tad/` (2) | **third-party, zlib** | both files sha256-**identical to upstream fetched live** at the pinned commit `822164b`; `audio-driver/LICENSE` at that commit fetched and read |
| `vendor/fonts/unscii-8.hex` (1) | **third-party, public domain** | §5.3 |
| `vendor/art/` original pack PNGs + text (21) | **third-party** | every one sha256-matched against the upstream pack zip; digests recorded in §5.1 |
| `vendor/art/*/ref_*` and `split_v/sv_*` conversions and oracles (34) | **mixed** | first-party where the conversion's source is procedural, third-party-derived where it traces to a pack; §5.2 |
| `vendor/probe_ref/` (36) | **first-party, EXCEPT three files** | the reference sources the CPU calibration probe measures. `inc/mode7_diz_ztable.inc`, `inc/mode7_diz_math.asm` and **`src/probe_scene_ref.asm`** (its `pv_*` routines) are CC BY 4.0 — §4.2 |
| `vendor/probes/` (19) | **first-party, EXCEPT `probe_cpu_ref.asm`** | the four small probes are authored here; `probe_cpu_ref.asm` is regenerated from the reference scene and carries its CC BY content — §4 |
| `vendor/rom/` (6) | **first-party** | authored here — LoROM/HiROM headers and linker fragments |
| `vendor/machine.py`, `vendor/mesen_runner.py` (2) | **first-party** | both are ctypes FFI **clients** of Mesen2 — no Mesen2 code is present in either. Their `MemoryType` enum is a transcription of an upstream enum's numeric values, a fact table |
| `vendor/mesen_patches/` (5) | **first-party source, GPLv3 combination** | §5.4 |
| `tools/mesen_state_offsets.cpp` (1) | **first-party** | a `printf` program; includes Mesen2 headers at build time, is not built by the Makefile, is not linked, contains no Mesen2 code |
| `tests/fixtures/` | **first-party** | our own lint/gate fixtures. `ref_dusk_grad.bin` is 675 B of COLDATA read off a running reference ROM — data computed by that ROM's own engine from six of its own constants |
| `.claude/` | **first-party** | authored here |

---

## 4. The dizworld trace, in full

This was the flagged highest risk, and it resolves in two halves that point
opposite ways. This tree vendors Brad Smith's `dizworld` material under **CC BY
4.0**, where attribution is *required*. The question was what, if anything,
carries that obligation.

### 4.1 The upstream grant, fetched

Fetched from `github.com/bbbradsmith/SNES_stuff/tree/main/dizworld`:

> *"This program was written by Brad Smith. Its source code is made freely
> available under the the terms of the Creative Commons Attribution license:
> CC BY 4.0"*

The readme also credits dizworld's **visual assets** to OpenGameArt
contributors under CC BY 4.0 / CC BY 3.0. None of those assets are in this
repository — checked by inspecting every binary under `vendor/`.

### 4.2 Half one — the tree DOES carry CC BY 4.0 dizworld code

Four files, found by grepping the tree for the routine names the upstream
source defines:

| file | content | how established |
|---|---|---|
| `vendor/probe_ref/inc/mode7_diz_ztable.inc` | the `pv_ztable` data block, **verbatim** | its 4,096 `.byte` values parse to exactly `min(255, round(32768 / i))` at all 4,095 non-zero indices — the closed form `dizworld.s` documents |
| `vendor/probe_ref/inc/mode7_diz_math.asm` | `umul16`, `smul16`, `smul16_u8`, `udiv32`, `sign`, `sincos` | the file's own header: *"Ported from: …/dizworld/dizworld.s — Author: Brad Smith (rainwarrior)"*, and each of the six routines matches its upstream counterpart |
| `vendor/probe_ref/src/probe_scene_ref.asm` | `pv_rebuild`, `pv_set_origin`, `pv_abcd_lines_{full,sa1,angle0}`, `pv_interpolate_{2x,4x}`, `pv_buffer_x` | present by label, with the in-file comments *"Ported from dizworld.s pv_rebuild"* and *"Formulas (matching Dizworld mode_y)"*. `pv_rebuild` alone spans ~740 lines |
| `vendor/probes/probe_cpu_ref.asm` | the same, plus instrumentation | generated by `vendor/probes/make_probe_cpu.py` from the file above; re-running it produced a **byte-identical** file (7 anchored patches), so the derivation is mechanical and the CC BY content passes straight through |

**None of these files carried a licence header.** The two
`vendor/probe_ref/inc/` files named only the author and the source repository;
the licence was nowhere in this tree. That is finding **F1** and is fixed.

**Reachability.** `build/probe_cpu.sfc` and `build/probe_cpu_step.sfc` link
this material and therefore embed CC BY 4.0 code. They are cycle-measurement
probes. Nothing under `engine/` or `game/` includes any of the four files —
`git grep` for `mode7_diz` outside `vendor/probe_ref/inc/` returns only the two
probe consumers and prose.

### 4.3 Half two — this project's OWN Mode 7 data is not derived from it

The reason to look hard: a design note for `mode7_flight` cited the reference
`pv_ztable` clamp as the source of a defect, which proves a dizworld-derived
curve was at least **consulted** while that rail was designed. Consultation is
not derivation, but the difference had to be shown, not asserted.

**Criterion used.** An artifact in this tree requires CC BY attribution if it
reproduces dizworld *expression* — its table values, its code, or a
transformation of either — as opposed to the *mathematics of perspective*
(scale ∝ 1/depth), which is an idea, is in every SNES Mode 7 reference, and is
not anyone's to license. Where the criterion left genuine doubt, the rule was
to attribute anyway and flag it; in the event it did not, and here is why.

**Structural argument (the strong one).** No asset generator in this repo reads
any dizworld file. Checked exhaustively: every `open` / `read_bytes` /
`Image.open` / `zipfile` call across `tools/` resolves to (a) nothing at all —
most generators are pure `math` + integer code — (b) an itch-pack PNG or zip,
or (c) a `vendor/art/*/ref_*` refusal oracle. `git grep` for `vendor/probe_ref`
under `tools/`, `engine/`, `game/`, `tests/` returns nothing outside the probe
recipes in the Makefile. **A dizworld byte therefore cannot enter a game ROM
built here**, by construction rather than by inspection.

**Numeric argument (the specific one).** `tools/gen_m7f_factors.py` is the
generator the design note points at. Ran it and tested its output against
`pv_ztable`:

* no altitude profile appears verbatim anywhere in `pv_ztable` — 0 of 81;
* no profile is expressible as an arithmetic resample `z[start + step·k]` for
  any start in 1..4095 and any step in 1..63 — searched exhaustively, no hits.

The profiles are `S(k) = K/(k + k₀)` solved through endpoints
`s0 = 220 + (alt·853 >> 8)`, `s1 = 40 + (alt·240 >> 8)` and quantised
`min(255, round(S/4))`. Those endpoint constants are measured from the
**vendored reference scene's** own linear ramp
(`vendor/probe_ref/src/probe_scene_ref.asm`) — first-party numbers — not from
Brad's table. And that generator explicitly *reverses* an earlier attempt to
reproduce the `pv_ztable` clamp, capping `S0_SPAN` at 853 so the clamp is
designed out rather than mirrored.

**Provenance of the shared shape.** Every per-scanline Mode 7 table this repo
emits — `gen_pose_tables.py`, `gen_split_h_persp_assets.py`,
`gen_split_h_2p_assets.py`, `gen_m7f_factors.py` — uses the same hyperbola
`S(k) = K/(k + k₀)`. That is the elementary closed form of perspective scale
against depth, it appears in every Mode 7 reference, and each of those four
generators derives it in pure `math` from its own endpoints, reading no
third-party file. It is re-derived here, not imported.

**Adjacent check.** `vendor/probe_ref/inc/mode7_sin_lut.inc` is a plain trig
table: all 512 entries equal `round(sin(i·π/256)·256)`. It is a different table
from Brad's 256-entry one and is generated by the closed form. First-party.

### 4.4 Verdict

> **This tree carries CC BY 4.0 dizworld material in four vendored
> measurement-scaffolding files, which now say so in their own headers and in
> `NOTICE`; `build/probe_cpu.sfc` embeds it and must credit Brad Smith. No
> engine feature, game rail or asset generator in this repo derives from
> dizworld: no generator reads a dizworld file, and the one generator whose
> design consulted a dizworld curve emits profiles that are provably neither a
> copy nor a resample of `pv_ztable` — and whose governing decision reverses
> the mirroring outright.**

---

## 5. The other traces, one hop at a time

### 5.1 The itch.io art packs

`vendor/art/` holds original pack files plus blobs derived from them. The
originals were verified by **hashing every one against the upstream pack zip**:
all 21 matched byte-for-byte.

**Ten of the 21 are stored under a changed name**, so a reader cannot pair
them up by filename — hence the member column in the table below. Two are
plain renames (camelot's `- READ ME -.txt` → `READ ME.txt`, dropping a leading
dash that is an option flag to half the tools that would touch it; the
spaceship pack's `Space Ships Explosion.png` → `explosion_sheet.png`), and
eight are **path flattenings** of the dungeonSprites tree
(`dungeonSprites_v1.0/fHero_/idle_/rIdle_0.png` → `fHero_idle_rIdle_0.png`,
and its seven siblings).

Two of the eight flattened files share bytes with another of the eight
(`fHero_idle_rIdle_1` = `_3`, `ghost_…_1` = `_3`). That is **upstream's own
duplication** — the four-frame idle cycle reuses a frame — reproduced
faithfully, not a vendoring mistake. It also means a bare hash lookup is
ambiguous for those files, so the member column names the path that flattens
to our filename, and each pairing was asserted individually rather than
inferred from the hash.

#### The digests, recorded

The match is written down rather than asserted, because a claim nobody can
recompute is not evidence. **The left column is reproducible on any checkout**
(`sha256sum` on the vendored file); the right column is reproducible against a
fresh download from the pack's upstream page, linked per pack in `NOTICE`.
Together those two are the chain: this file is that member of that archive.

**Pack zip digests** (the four upstream archives the per-file digests below
were taken against):

| sha256 | zip |
|---|---|
| `658fb27043898039fc1bccff9b38669f6705a2c75b388713f384dd171d02ea9b` | `camelot_ [version 1.0].zip` |
| `9b351e2992381004e8f2ccc23dae53ef2660843f337772d157177db6fdbed533` | `dungeonSprites_v1.0.zip` |
| `a1d7efd47e2c6a0347010aeae2f2ca7625dd31482e7d4f00e8163cf4eb01dd68` | `Four Seasons Platformer Tileset [16x16][FREE] - RottingPixels.zip` |
| `ddebd3e4e073e2132f5c3b47b9a8f592f2e59d4d40ed1dd787696487b9ce4203` | `Spaceship Pack.zip` |

**Per-file digests.** Every vendored file, its sha256, and the zip member
it is byte-identical to.

| vendored file (under `vendor/art/`) | sha256 | zip member |
|---|---|---|
| `camelot/READ ME.txt` | `118da1130a6675ca260d5d9f6533466e29326708b3abe0d26d41e7a9233761be` | `camelot_ [version 1.0]/- READ ME -.txt` |
| `camelot/arthurPendragon_.png` | `f1c160ab44df45cdbc482d4de365c8dc231672b8a11e18a604ebbd95d5dd4664` | `camelot_ [version 1.0]/arthurPendragon_.png` |
| `camelot/mordred_.png` | `346ae55ff10a11e9e1aed4cf2b05d507790c6d11e7e1a7c61b32e2586ddacd3e` | `camelot_ [version 1.0]/mordred_.png` |
| `camelot/excalibur_.png` | `36bb50b7bcc15ff29006b416d309b5cc2dc123fe1c42438396a5d203694f3435` | `camelot_ [version 1.0]/excalibur_.png` |
| `camelot/dust_.png` | `5c47c9dc710cb96fc3cb91958f504ccd7ba400f6a9af9ac258031c7ba412efa5` | `camelot_ [version 1.0]/dust_.png` |
| `dungeon_sprites/fHero_idle_rIdle_0.png` | `aa0de91aaf7efea3b7ffcd833631d7ef2be03d2a97913a98318dcfed3223f453` | `dungeonSprites_v1.0/fHero_/idle_/rIdle_0.png` |
| `dungeon_sprites/fHero_idle_rIdle_1.png` | `f8166e70aef4873f88bef767400f1abf467ed605ac02d2e51afffacbba5b9103` | `dungeonSprites_v1.0/fHero_/idle_/rIdle_1.png` |
| `dungeon_sprites/fHero_idle_rIdle_2.png` | `ce4e9ec20fd8ccc93436e2472f41e1556433b9373eb28c19a35e79e3f98b8d70` | `dungeonSprites_v1.0/fHero_/idle_/rIdle_2.png` |
| `dungeon_sprites/fHero_idle_rIdle_3.png` | `f8166e70aef4873f88bef767400f1abf467ed605ac02d2e51afffacbba5b9103` | `dungeonSprites_v1.0/fHero_/idle_/rIdle_3.png` |
| `dungeon_sprites/ghost_idleWalkRun_rIdleWalkRun_0.png` | `fa567a43678ca3df635182fc621f3209f348d1a855fe1687797408c36e12836f` | `dungeonSprites_v1.0/ghost_/idleWalkRun_/rIdleWalkRun_0.png` |
| `dungeon_sprites/ghost_idleWalkRun_rIdleWalkRun_1.png` | `8a6e9fcdc1fa9565058923e2eb495c3651d1d524c4e9247ed7fbdefb06d0a125` | `dungeonSprites_v1.0/ghost_/idleWalkRun_/rIdleWalkRun_1.png` |
| `dungeon_sprites/ghost_idleWalkRun_rIdleWalkRun_2.png` | `971695d0c27db0e6665e46280936fb899e2df3eb4389ab8f0b3159d6bf13e0f8` | `dungeonSprites_v1.0/ghost_/idleWalkRun_/rIdleWalkRun_2.png` |
| `dungeon_sprites/ghost_idleWalkRun_rIdleWalkRun_3.png` | `8a6e9fcdc1fa9565058923e2eb495c3651d1d524c4e9247ed7fbdefb06d0a125` | `dungeonSprites_v1.0/ghost_/idleWalkRun_/rIdleWalkRun_3.png` |
| `four_seasons_tileset/RottingPixels.txt` | `a3c837543b56c7cb6f575c37dc40e6e6f3156ba55f00b23bbd2b03d18a525f07` | `Four Seasons Platformer Tileset [16x16][FREE] - RottingPixels/RottingPixels.txt` |
| `four_seasons_tileset/four-seasons-tileset.png` | `27b078335ac220c14d77c06287b96f4cd0011ed93810b0c965340a4e40ff2d22` | `Four Seasons Platformer Tileset [16x16][FREE] - RottingPixels/four-seasons-tileset.png` |
| `spaceship_pack/explosion_sheet.png` | `bbd2962f948e0c3c73332c641aa6917e4572ee72114fcb09b0d2f364facd2384` | `Space Ships Explosion.png` |
| `spaceship_pack/planet_1.png` | `5e51c733d7278d3b174ae956f7646cee4a078f03f6f2eb526a66c74c66334683` | `planet_1.png` |
| `spaceship_pack/planet_2.png` | `8dbd0103a207047382989caa87dbc0baadaf423177f7789baa6dced70215656e` | `planet_2.png` |
| `spaceship_pack/planet_4.png` | `b689d6ac0f35a0379889bf511cb35fe845866ad3642fb644e4c344f46741d45d` | `planet_4.png` |
| `spaceship_pack/planet_6.png` | `10fe5dc1dd57d6d76d0439748327c92440d7a2daa60367d476d98600fda20786` | `planet_6.png` |
| `spaceship_pack/ship_2.png` | `b60791306e20646a7ef88f7610ef80024033df67dd3fedd61cb5e730b06381d5` | `ship_2.png` |
| `spaceship_pack/ship_5.png` | `77c052cfb31e64b28367515df6214e04f8e6418b70780ac154f54a4d42bbcfef` | `ship_5.png` |
| `spaceship_pack/turbo_blue.png` | `ae3ab07905648e8754cb5961124de3e0afa78cc5f4c404676af5eabba9aa09ed` | `turbo_blue.png` |

The grant text for each pack was read from its itch.io page and recorded
verbatim, with verification dates in July 2026. **Those pages were not
re-fetched here** (§7 L2), so the licence half of these four rows rests on that
record rather than on this audit's own retrieval. The pack **identity** half
does not — that is hashed, above.

**The four packs are under four different states, and only two of them are
CC0**, per `NOTICE`:

| pack | state |
|---|---|
| camelot | **CC0** — the itch.io page links the CC-0 deed |
| dungeonSprites | **CC0** — same |
| Four Seasons **tileset** (Rotting Pixels) | **custom permissive grant, NOT CC0** — free + commercial, modification allowed, credit optional, but no public-domain dedication. Verified against the raw page 2026-08-16: a section headed "LICENSE:" carrying those terms, no licence name, no `creativecommons.org` link, and no License field in the page's metadata table. **Not to be confused with a different pack of nearly the same name** — analogStudios_'s "Four Seasons Platformer *Sprites*", which does state "[ CC-0 ]" and is not vendored here (and whose own CC-0 text links a CC BY 4.0 deed, flagged unanswered in its comments) |
| Spaceship Pack | **page-stated permissive grant, NOT a CC0 dedication** — the page grants "Free for commercial use" and nothing more (owner-verified on the live page, 2026-08-16) |

The Four Seasons grant covers everything this repo does with the art but is
not a dedication, and the Spaceship Pack's grant is the page's own wording — permissive, not a dedication; vendored with source attribution and link-back, the same treatment as the CC0 packs (resolved 2026-08-16),
not a settled one.

**Do not count these four into two buckets.** An earlier draft of this
paragraph read *"Three of the four are CC0"*, allocating the Spaceship Pack to
CC0 by arithmetic and contradicting F5 two sections below; `LICENSE` carried the
same miscount. The error direction is the one that matters: CC0 is strictly
broader than "free for commercial use", so the miscount **over**-granted to a
downstream reader. It is the third instance in this file of one sentence
flattening N artifacts into one clause, and the first to survive a dedicated
sweep — because that sweep keyed on the previous two's *wording*, and this one
contained none of it. Hence the standing rule: **grep the claim, not the
string.**

### 5.2 The reference conversions

`vendor/art/*/ref_*.{bin,inc,png}` are conversions of source art into SNES
formats, vendored as committed bytes and kept as the asset pipeline's refusal
oracles — first-party **unless** the conversion's own input traces to a pack.
Traced per directory:

| directory | traces to | verdict |
|---|---|---|
| `m7_dungeon` | stdlib-only procedural generators building pixels from `math.hypot` bands and a `MAZE` string literal, with no file read and no image import | **first-party** |
| `mode7_chamber` | a procedural generator giving every tile a solid colour from a three-line rule over the tile grid | **first-party** |
| `split_h_2p`, `split_h_matrix`, `split_h_persp` | checker algebra and the closed-form perspective ramp, no image input | **first-party** |
| `camelot`, `dungeon_sprites`, `four_seasons_tileset` | the packs above | **third-party-derived** |
| `split_v` | `sv_knight_chr.bin` ← camelot (CC0); `sv_stage_pal.bin` ← Four Seasons (permissive grant) | **third-party-derived** |
| `platformer_stream` | `ref_level_chr.bin` + `ref_level_pal.bin` ← a BG level pipeline reading the Four Seasons tileset | **third-party-derived** |

### 5.3 The font

`vendor/fonts/unscii-8.hex` is the repo's only vendored face, and its recorded
provenance had been a single unsourced cell — "CC0 fonts", with no author, no
upstream URL and no filename (finding **F3**).

Grounded here instead. Upstream `viznut/unscii`'s README states: *"You can
consider it Public Domain (or CC-0) except for the files derived from or
containing parts of Roman Czyborra's Unifont project (unifont.hex,
hex2bdf.pl, unscii-16-full.\*) which fall under GPL."* `unscii-8` is outside
that carve-out. Then the file itself was checked: the released `unscii-8.hex`
was fetched (3,191 glyphs) and compared glyph-by-glyph against our 96. Every
one of our codepoints U+0020..U+007F exists upstream and **95 of 96 bitmaps
are byte-identical**; U+007F (DEL) is blanked to all-zero in our copy, which
is the sole modification.

`unscii-8.hex` is not committed in the upstream git repo — it is a build
product distributed from `viznut.fi`, which returned 503 throughout this
session, so the comparison copy came from the Internet Archive's snapshot of
that exact URL. Recorded as a limit (§7 L1).

### 5.4 Mesen2

This repository commits a patch and two new C++ sources that are compiled
*into* Mesen2, so it cannot put Mesen2 wholly under "fetched on demand, never
committed" and does not try to.

* `lockstep_core_edits.patch` is a unified diff whose **context lines are
  Mesen2's GPLv3 source** (`Debugger.cpp`'s break-sleep loop, `EmuSettings.h`,
  `VideoDecoder.h`).
* `LockstepSync.h` and `LockstepApiWrapper.cpp` are first-party code, but
  they exist to be linked into Mesen2. The resulting `MesenCore-lockstep.so`
  is a **GPLv3 derivative work**. It is a build artifact, never committed
  (`tools/Mesen/` is git-ignored), and never linked into a ROM.
* `tools/mesen_state_offsets.cpp` includes Mesen2 headers at build time and
  contains no Mesen2 code.

Separately, Mesen2's source is read across the tree as a **hardware
reference** (CLAUDE.md rule 7's second source). Those passages restate
behaviour in this project's own words with file:line citations; no code is
reproduced.

---

## 6. Findings

| # | finding | severity | action taken |
|---|---|---|---|
| **F1** | CC BY 4.0 dizworld material shipped in four files with **no licence notice** — the two `vendor/probe_ref/inc/` files named the author and source repo but not the licence, and the two consumers named neither | **HIGH** — CC BY requires attribution, and the tree gave a reader no way to know one was owed | per-file notices added to `mode7_diz_ztable.inc` and `mode7_diz_math.asm`; the notice added to `make_probe_cpu.py`'s generated header so `probe_cpu_ref.asm` carries it through regeneration; a pointer added to `vendor/probe_ref/README.md`; rows added to `LICENSE` and `NOTICE` |
| **F2** | `vendor/art/split_v/README.md` stated *"Both packs are CC0"* — but one is the Four Seasons tileset, whose grant is **not** CC0. This directly contradicted `vendor/art/four_seasons_tileset/README.md`, which says so explicitly (*"This is NOT CC0 and must not be flattened to it"*) | **MEDIUM** — an internal contradiction that would have propagated into a NOTICE written from the READMEs | corrected in place; `NOTICE` carries the accurate grant |
| **F3** | The font's licence was sourced to a doc that says only *"CC0 fonts"* — no author, no URL, no filename. The repo's only vendored face had no traceable provenance | **MEDIUM** | verified upstream and against the released file; `NOTICE` carries author, upstream, grant and the one-glyph modification; `docs/11`'s row now points at `NOTICE` |
| **F4** | The BG level pipeline that produced two vendored blobs labels its input *"the Four Seasons CC0 16x16 tileset"* in a header comment inherited by every file it generates — wrong by the pack's own recorded grant, which is permissive but not a public-domain dedication | **LOW** (the correct grant covers the use) | recorded; `NOTICE` states the actual grant for the derived blobs |
| **F5** | The Spaceship Pack is **not CC0** — the page grants "Free for commercial use" and nothing more (owner-verified live, 2026-08-16, closing the question open since 2026-07-19). Resolved 2026-08-16: the pack is listed free and unrestricted, and is vendored with source attribution and link-back, the same treatment as the CC0 packs | — (closed) | `NOTICE` and §5.1 state the grant as the page states it |

---

## 7. Limits — what this audit could NOT establish

* **L1 — `viznut.fi` was unreachable.** Every request to `viznut.fi/unscii/`
  returned 503. The upstream **grant** was read from the project's GitHub
  README (authoritative, same author); the released `unscii-8.hex` used for
  the glyph comparison came from the Internet Archive's snapshot of the
  canonical URL rather than from the canonical host.
* **L2 — the four itch.io pack pages were not re-fetched during this audit.**
  Their licences rest on a record of live verification on 2026-07-18/19 with
  the grant text quoted verbatim, reproduced in `NOTICE`. The pack **identity**
  is hashed here (§5.1) and does not depend on that record; the **licence**
  half does. Re-verifying the four pages at the next release would close this.

  *Partly closed 2026-08-16.* Two of the four pages were fetched again:
  **camelot** states CC-0 and links the deed — confirmed, unchanged; **Four
  Seasons** states no licence name at all, only free and commercial use with
  modification allowed and credit optional, which is exactly what this
  document and `NOTICE` already record, so that row now rests on its own
  retrieval. The check earned its keep: the acquisition-time record these
  rows were originally taken from labels the Four Seasons pack **CC0**, and
  the page does not support that label. Nothing this tree does with the art
  depends on the difference — the grant covers all of it — but a permissive
  grant is not a dedication, and a derivative of it cannot be re-dedicated to
  the public domain on the strength of that label. The **dungeonSprites** and
  **Spaceship Pack** pages remain un-refetched here (the latter was
  owner-verified live 2026-08-16, F5).
* **L3 — the Spaceship Pack's CC0 deed is an open question (F5).** The
  reachable page grants *"Free for commercial use"* and carries no CC0 label,
  while the July 2026 record carries a CC0 attestation alongside it. `NOTICE`
  records the live grant verbatim rather than the attestation, which is the
  conservative reading, and that grant covers everything `game/shmup` does with
  the art. **The deed itself is not established.** Closing it means contacting
  the author and recording the answer.
* **L4 — GitHub's API was proxy-restricted in this environment.** Upstream
  files were reachable through `raw.githubusercontent.com` (which is how the
  TAD byte-identity check ran), but repository metadata — commit dates,
  tags, the file list at a revision — was not. The TAD pin `822164b` is
  therefore confirmed as *"the two files at this ref are byte-identical to
  ours"*, not as *"this ref is `v0.3.0-48-g822164b`"*.
* **L5 — this is a provenance audit, not a legal opinion.** It establishes
  what each artifact is, where it came from, and what its author granted. It
  does not opine on the boundary between idea and expression in any
  borderline case; §4's criterion is stated so a reader can disagree with it
  on the evidence rather than on the conclusion.
* **L6 — one adjacent, non-licence observation.** `tools/gen_m7f_factors.py`'s
  `quantise()` docstring still describes its clamp as mirroring the reference
  `pv_ztable` clamp, which the `S0_SPAN` cap recorded in §4.3 reverses.
  Running the generator prints *"1 levels clamped at the horizon"*, so the
  clamp does still fire once at the top altitude — `round(1019/4) = 255` —
  where the decision's text says it never saturates. A rounding-boundary nit in
  a comment, recorded because it was measured while tracing §4.3. Not a
  licensing matter and not fixed here.

---

## 8. What a downstream consumer actually has to do

* **Ship a game ROM built from this repo** (`microzero`, `platformer`,
  `brawler`, `shmup`, `rpg`, any rail): **no obligations.** zlib's conditions
  bind source distributions, the art packs' grants make credit optional, and
  no CC BY material is linked into any rail.
* **Redistribute the source**: keep `LICENSE`, `NOTICE` and the per-file
  notices intact; mark altered sources as altered.
* **Ship `build/probe_cpu.sfc` or anything built from the four files in §4.2**:
  **credit Brad Smith (rainwarrior)** — one line is enough, and `NOTICE`
  carries the wording.
* **Redistribute a built `MesenCore-lockstep.so`**: GPLv3 terms apply. The
  repo never commits one.
