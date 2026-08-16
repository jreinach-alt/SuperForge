# vendor/art/platformer_stream

Read-only artifacts for the `platformer_stream` rail: bytes that are COPIED
rather than generated, because nothing in this tree can produce them. Nothing
here is a build input in the sense of being compiled — the generators read them
as an oracle and the tests read them again.

## What is here, and why each one is *copied* rather than generated

| file | bytes | what it is | why vendored |
|---|---|---|---|
| `ref_level_chr.bin` | 800 | 25 unique 4bpp BG tiles — the level's CHR | The conversion that produced them read a **Four Seasons tileset image that is not in this tree** (a path on the author's machine). There is nothing here to regenerate from. |
| `ref_level_pal.bin` | 32 | the 16 CGRAM words the CHR above is indexed against, little-endian | Same reason: quantized from the same absent image. |

**Everything else the rail needs is generated**, and that split is deliberate.
`tools/gen_platformer_stream_assets.py` emits the column-major tilemap, the
row-major tilemap and the world-space collision table from
`author_level_seasons` — pure integer code with no image input — and
`tests/test_platformer_stream_assets.py` asserts all three are **byte-identical
to the committed `level_flat.bin` / `level_flat_row.bin` /
`level_collision.bin` reference blobs**. Those blobs are what a published
render of this level was built from, so agreement with them is ground truth
this repo did not produce — which is what the asset-import rule asks
for, and what a converter checked against its own output cannot give.

The two files above cannot be checked that way — they *are* the source — so
they are copied verbatim rather than round-tripped through a generator that
would only be agreeing with itself.

## The hero sprite is NOT here

It is already in the tree at `vendor/art/dungeon_sprites/ref_hero.inc`,
vendored for the `platformer` rail, and it is **byte-identical** to the frames
this rail wants — the two rails share one 16×16 four-frame idle.
`tools/gen_platformer_assets.py` already converts it; this rail reuses that
path rather than vendoring a second copy. See that directory's README for its
own provenance.

## Provenance of the tileset — settled 2026-08-16; see `NOTICE`

**The operative record for these two files is the Rotting Pixels row in this
repo's [`NOTICE`](../../../NOTICE), and the trace behind it is
[`docs/92_provenance_audit.md`](../../../docs/92_provenance_audit.md) §5.1–§5.2.**
`ref_level_chr.bin` and `ref_level_pal.bin` are conversions of the **Four
Seasons Platformer Tileset [16x16][FREE]** by Rotting Pixels,
<https://rottingpixels.itch.io/four-seasons-platformer-tileset-16x16free>,
under that pack's **custom permissive grant — free and commercial use,
modification allowed, credit optional. It is NOT CC0**, and this project
cannot re-dedicate it.

*What this section used to say, and why the caution was right.* Until the
provenance audit it recorded the source as *"the Four Seasons CC0 tileset"* —
a label inherited from the conversion tool's own header — with the standing
caveat that this was *"a statement repeated here, not a licence this repo has
verified"*, per `AGENTS.md`'s trap about provenance taken from a licence its
own author wrote. **That caution was correct and the statement it declined to
accept was in fact wrong**: the pack ships a *custom permissive grant (not
CC0)*, so the header — and every generated file inheriting it — mislabelled
its own input. The grant covers everything done with the art here, so nothing
is blocked; the label was simply wrong, and declining to repeat it as a
cleared right was the right call. It is superseded here only because the
question is now answered rather than open.


## The published gallery frame, vendored as an oracle

| file | bytes | what it is | why vendored |
|---|---|---|---|
| `ref_at_rest_frame.png` | 3,112 | frame **30** of a published hardware capture of this level, cropped to the active picture `(0, 7, 256, 231)` | A hardware render by a program sharing no code with this repo, at the moment this rail's own tests settle on: the player at rest on the bedrock floor with the follow camera clamped at the world bottom. |

**Why frame 30 and not any other.** The capture is 155 frames of 256×239. Its
frames 1–28 are the no-input spawn fall, **29–32 are AT REST**, and 33 onward
is a recorded walk that depends on input this repo does not replay. Within the
at-rest run only the hero moves: frames 29 and 31 differ in **314 pixels, every
one of them inside `x 126..137, y 115..153`** — the four-step idle cycle. So a
whole-frame comparison would be hostage to animation phase, and the oracle is
split: the LEVEL pixels are compared to this frame, the hero is compared
through OAM against the recorded at-rest pin (slot 0 at screen 124, 145).

**What this frame can and cannot ground-truth, measured rather than assumed.**
It holds **50 distinct colours**. Twelve of them are the level palette's exact
CGRAM words — `$329B`, `$14A6` and the rest round-trip byte-for-byte — so the
level half of a comparison against it is **pixel-exact with no tolerance**. The
dusk sky cannot be: it is 224 scanlines of independently varying R/G/B fixed
colour, which the capture's 256-entry palette necessarily quantizes, and our
render differs from it there by up to one 5-bit step.
`tests/test_platformer_stream.py` therefore compares only the level pixels to
this file and asserts the sky EXACTLY against the ROM's own declared sources
(`pfs_grad.bin` plus CGRAM word 0) — a stronger oracle for that region than a
quantized picture could be, and the reason no tolerance appears anywhere in
either case.

`test_the_vendored_oracle_frame_is_the_published_gif_frame` re-extracts frame
30 from the published capture and byte-compares it to this PNG. It is gated on
`SF_REFERENCE_TREE`, so it runs only where that capture is on disk and skips
everywhere else — which is the half that makes the vendoring honest: the
comparison case itself runs anywhere, against the PNG in this tree, and this
case proves that PNG is the frame it claims to be rather than something this
repo drew.
