# 11 — Font assets: what we have, what was rejected, and what is still owed

> Status: LIVE — the one vendored face, what was examined and REJECTED, and the still-open proportional/VWF source question

**Status:** record, written 2026-07-28, **corrected the same day** after the
provenance of the font it had just recommended was challenged. The challenge
was right and the recommendation is withdrawn. Read §3 before §2 if you are
short on time: **the VWF font question is OPEN, not settled** — §5 names a
licence-verified shortlist but nothing is adopted until §5.1's gate runs.

This file exists because a search for good-quality CC0 fonts covering a range
of game genres (arcade, racing, RPG…) had been commissioned and never written
down anywhere. It is not recorded, and §4 explains what that absence caused.

---

## 1. What is actually in the tree

| file | shape | provenance | status |
|---|---|---|---|
| `vendor/fonts/unscii-8.hex` | monospace 8×8, 96 glyphs | **unscii-8** by viznut (Ville-Matias Heikkilä), <https://github.com/viznut/unscii> — public domain / CC0. Our copy is U+0020..U+007F of the released `unscii-8.hex`: 95 of 96 bitmaps byte-identical upstream, U+007F blanked. Traced and verified in [`92`](92_provenance_audit.md) §5.3; see `NOTICE` | **in use** — `font_rom`'s source via `tools/gen_font.py` |

> **Provenance corrected 2026-08-16**
> ([`docs/92_provenance_audit.md`](92_provenance_audit.md) finding F3). This row
> previously sourced the grant to a document that said only *"CC0 fonts"* —
> with no author, no upstream and no filename, so the repo's one vendored face
> had no traceable provenance. The grant is now read from upstream and the
> bytes compared against the released file. The `.hex` **format** is Unifont's;
> the glyphs are unscii's own and are outside unscii's GPL carve-out.

That is the whole inventory. **There is no proportional font in this repo, and
no VWF-suitable source.**

## 2. Rejected: a candidate `clean.png` / `dialog.png` pair

A candidate font pair was examined for vendoring — a monospace `clean.png`, a
proportional `dialog.png`, a `LICENSE` declaring both CC0, and a 33 KB
`generate_fonts.py`. I vendored `dialog.png` and named it the VWF source.
**Both were withdrawn within the hour.** Kept here as the record of what was
examined, so nobody re-adopts it.

### 2.1 The provenance is a self-assertion, not a provenance

`generate_fonts.py` is not procedural — it is literal `#`/`.` bitmaps typed into
two Python dicts, one row per string. So it is *hand-authored art expressed as
code*. But the hand was a model's: the glyphs, the generator, and the `LICENSE`
declaring them original pixel art made for the project were all produced by the
same authoring session. **A CC0 file written by the same session that made the
asset attests to nothing about quality and adds nothing to provenance** — it
establishes only that no third-party font was copied, which is a licensing
fact, not a design fact.

### 2.2 The measured defects — this is a broken font, not a tight one

All verified by reading `dialog.png`'s pixels, not by inspection of the source.

| defect | measurement |
|---|---|
| **`l` and `\|` are byte-identical** after left-alignment | both are `#` × 7 rows then blank |
| `i` and `!` are also 1 px columns | `i` = `#/-/#/#/#/#/#`, `!` = `#/#/#/#/#/-/#` — distinguished only by which row is blank |
| **the period is one pixel** | 1 ink pixel total, at row 5 |
| colon / semicolon are 2 and 3 pixels | vs `clean.png`'s 2×2 blocks — the two faces disagree |
| **lowercase `w` is wider than `m`** | `w` = 7 px, `m` = 5 px. Typographically backwards; `v` = 5 px, so the v/w pair is inconsistent with the m/n pair |
| same-class capitals have arbitrary widths | `V` 5 · `H` 5 · `N` 6 · `M` 7 · `W` 7 — not a designed progression |
| the stated style is not the delivered style | the generator's docstring says "semi-serif"; the glyphs have no serifs — they are `clean.png`'s blocky sans, narrowed |

**These are exactly the failure modes the brief named** — inconsistent style,
alignment and spacing — and they are structural, not cosmetic: a VWF renderer
that strips bearings will render `l` and `|` as the same glyph, and a 1 px
period will vanish against a busy background.

## 3. So the VWF font source is OPEN

`unscii-8` remains the only vendored face and it is monospace. **Deriving VWF
widths from it produces a font that renders close to monospace** (55 of 96
glyphs are the same 6 px of ink, narrowest real glyph 2 px, and its bearings
vary so a stripping pass is required) — technically proportional, visually not.

Two honest routes, neither yet taken:

1. **Source a real proportional bitmap font with third-party provenance.** This
   is what was asked for originally. **§5 now names a licence-verified
   shortlist** — [m5x7](https://managore.itch.io/m5x7) (CC0, Daniel Linssen) is
   the VWF pick — but no glyph has been inspected yet, so §5.1's gate stands
   between the shortlist and adoption.
2. **Commission the face deliberately** as a design task with a style spec and a
   review pass — not as a side-effect of renderer work. §2 is what happens
   when glyphs get typed to unblock something else.

**Do not let the VWF work pick a font by default.** The renderer can be built
and tested against `unscii-8`-derived widths — the proportional-advance
invariant is provable there, it just looks near-monospace — and the face can be
swapped later without touching the renderer. That decoupling is the safe path.

## 4. What the missing record cost — the actual lesson

The search for good CC0 fonts covering arcade / racing / RPG use cases **was
never written down anywhere.** Searching for it returns nothing: no candidate
list, no licence notes, no genre mapping, no per-font provenance. Zero hits for
font + OFL + candidates + provenance.

The consequence was not that the work was lost. It was that **the next session
re-derived from what *was* recorded and reached a confident wrong answer.** I
inventoried, found `unscii-8` and the candidate pair, measured them, and
produced a well-evidenced recommendation — measured distributions, an honest
caveat, a comparison table — for the wrong font. Worse, I read the *defects as
the feature*: I cited `dialog.png`'s "7:1 width ratio, `i`/`l`/`.` at 1 px" as
proof it was purpose-designed, when 1 px glyphs that collide with `|` are the
symptom of a font typed rather than drawn.

Three transferable rules:

1. **A licence file authored alongside an asset is not provenance.** It answers
   "was anything copied", never "is this any good" or "who designed it". Ask who
   the *author* was and whether anyone reviewed the output.
2. **When a measurement flatters a candidate, check whether the extreme is a
   feature or a defect.** A 7:1 width ratio in a bitmap font could be excellent
   design or a collapsed glyph. Rendering the extremes side by side answers it
   in one minute; the distribution table does not.
3. **Record candidate *sets*, not just the choice.** The choice is the least
   durable part — a decision with no recorded alternatives cannot be revisited,
   only re-derived, and re-derivation reaches for whatever is nearest.

Also worth knowing: `.gitignore` line 20 is `*.png` with `!docs/**/*.png`, so my
"vendored" PNGs were **silently never committed** — `git add -A` reported success
and the binaries never landed. Had the decision been right, the vendoring would
have failed quietly. Any future font asset needs a `!vendor/fonts/*.png`
exception, and a `git ls-files` check that it actually tracked.

## 5. The three itch.io picks — licence-verified, glyphs NOT yet inspected

Searched itch.io filtered to **CC0** (`itch.io/game-assets/assets-cc0/tag-fonts`)
on 2026-07-28, for three slots. Licence, author and format confirmed by reading
each asset page. **Read §5.1 before adopting any of them.**

| slot | pick | author | licence | shape | formats |
|---|---|---|---|---|---|
| **basic console** | [monogram](https://datagoblin.itch.io/monogram) | datagoblin | CC0 | monospace, 5 px wide | **TTF + bitmap PNG (1.3 kB)** |
| **racing HUD (fixed-width)** | [Public Pixel Font](https://ggbot.itch.io/public-pixel-font) | GGBotNet | CC0 | monospace on an **8×8 grid** | TTF |
| **RPG dialog (VWF)** | [m5x7](https://managore.itch.io/m5x7) | Daniel Linssen | CC0 | **proportional**, 5×7 | TTF |

Why each:

- **monogram** is the only pick that **already ships a bitmap**, so it needs no
  rasterisation step at all — the one conversion in this whole area with a known
  failure mode is skipped entirely. Its author states the design intent as "your
  IDE, terminal or fantasy console", which is the console slot exactly.
- **Public Pixel Font** is monospaced on an **8×8 grid — our tile size**. Glyphs
  map 1:1 to SNES tiles with no scaling and no fitting judgement, which is what a
  HUD needs: digits identical in width and crisp at native size. TTF-only, but
  rasterising at exactly its 8 px design size is lossless.
- **m5x7** is the canonical CC0 proportional pixel font, by a designer with a
  body of published work. Proportional by design rather than by accident, which
  is the property `dialog.png` faked. 7 px tall leaves a descender row inside an
  8 px cell. Companion `m6x11` exists if 7 px reads cramped.

Runners-up, all CC0, if a pick fails §5.1: [Not Jam Font
Pack](https://not-jam.itch.io/not-jam-font-pack) — 29 fonts, Not Jam has "waived
all copyright and related or neighboring rights", with monospace variants
explicitly marked (`Mono Clean 8`, `Mono Prophet 8`, `Mono Crooked 8` are all
8 px, so all HUD-slot candidates) and proportional ones for the dialog slot;
[at01](https://grafxkid.itch.io/at01-pixel-font) by GrafxKid for the console
slot; [Pixuf](https://erytau.itch.io/pixuf) for a tighter proportional face.

### 5.1 The gate — none of these is adopted until it passes

**I verified licence, author and format. I inspected no glyphs.** itch.io serves
downloads through a flow I could not complete headlessly, and two of the three
picks are TTF-only, so they must be rasterised before they can even be examined.
Treat the table above as a **shortlist**, not a decision — that distinction is
the whole lesson of §2 and §4.

Before any face enters `vendor/fonts/`, run the test that would have caught
`dialog.png` in one minute, on the actual rasterised bitmap:

1. **Render `l | i ! 1` at native size.** All five must be visually distinct
   *after left-alignment* (bearing stripped), which is how a VWF renderer will
   see them. `dialog.png` failed here: `l` and `|` were byte-identical.
2. **Render `mill will Wm` and `nvmw`.** Check `m ≥ n` and `w ≥ v`, and that `w`
   does not exceed `m`. `dialog.png` had `w` 40% wider than `m`.
3. **Render `End. Next: go; wait, ok`.** Punctuation must have body — a period of
   ≥2×2 pixels. `dialog.png`'s period was one pixel.
4. **Tabulate same-class capital widths** (`V H N M W`). Expect a coherent
   narrow/wide split, not an arbitrary spread. `dialog.png` gave V5 H5 N6 M7 W7.
5. **Confirm the delivered style matches the described style.** `dialog.png`'s
   generator claimed "semi-serif" and shipped a blocky sans.
6. **For the VWF pick only:** confirm the ink extents give a usable advance
   spread — and that the *narrow* glyphs are narrow by design, not collapsed.

`vendor/fonts/unscii-8.hex` passes all of 1–4 and is the reference for what
passing looks like: `i` 5 px and `l` 5 px with distinct serif shapes, `!` and `|`
both 2 px but differing in body, caps V6 H6 N7 M7 W7, `m` = `w` = 7 with
`n` = `v` = 6, and a 2×2 period. It is a genuinely designed font — its only
limitation is that it is monospace, which is why the VWF slot needs m5x7.

7. **Also required, mechanically:** add `!vendor/fonts/*.png` to `.gitignore`
   before committing any bitmap, and verify with `git ls-files` that it tracked.
   Line 20 is a blanket `*.png` and it silently swallowed the last attempt (§4).

The genre framing from the original ask stays the acceptance shape: **arcade/HUD**
(blocky, high-contrast numerals), **racing/technical** (condensed, fixed-width),
**RPG/dialog** (proportional, comfortable at length), **title/display**. The three
picks above cover the first three slots; nothing here covers title/display, and
that gap is deliberate — it is not needed yet.

## 6. Superseded — the earlier non-itch.io leads

Found by web search 2026-07-28, **none inspected, none measured, none adopted.**
Recorded so the search starts from here rather than from nothing. Every one of
these needs the §2.2 treatment before it is trusted: render the extremes,
check `l`/`|`/`i`/`!` are distinguishable, check the m/w and v/w relationships,
check punctuation has body, confirm the licence and the human author.

| lead | note |
|---|---|
| [Bitmap Font (OpenGameArt)](https://opengameart.org/content/bitmap-font) | CC0, max 8×12, and **ships a definition file giving each glyph's pixel width** — the only lead with metrics already authored by its designer |
| [Grafx2 font collection](https://opengameart.org/content/new-original-grafx2-font-collection) | eight 8 px **proportional** faces — sans (NeoSans), serif (Kronos, Paris), script (BitScript), compact (Ruthenia), blackletter (Berlin), plus faux-Cyrillic/kana. The widest *genre* range on offer, which is the original ask |
| [Pixuf](https://erytau.itch.io/pixuf) | CC0, deliberately minimal proportional face, designed for 8/16/24/32 px |
| [OpenZoo Fonts](https://asie.itch.io/openzoo-fonts) | CC0/PD but **fixed-width** — a CGA/EGA replacement family. No use for VWF; possible `clean`-slot alternative |

The genre framing from the original ask is worth preserving as the acceptance
shape: an **arcade/HUD** face (blocky, high-contrast, numerals that read at a
glance), a **racing/technical** face (condensed, italic-capable), an
**RPG/dialog** face (proportional, comfortable at length), and a **title/display**
face. Grafx2 is the only lead that plausibly covers more than one of those.
