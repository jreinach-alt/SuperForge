#!/usr/bin/env python3
"""png2snes.py — PNG -> SNES 4bpp CHR + palette, as ca65 .inc files.

The kit's asset front door. Two subcommands:

  sprite   PNG sheet or frame-folder -> OBJ CHR blob + one 15-color palette
           + per-frame tile constants + per-animation frame tables.
           CHR is emitted in OBJ VRAM-GRID order (16x16+ sprites read their
           second tile row at +16 tile numbers — the hardware layout is baked
           in here so no caller has to rediscover it).

  bg       tileset PNG -> deduped 8x8 CHR + <=8 grouped BG palettes + an
           mset-ready tilemap-word table (tile | palette<<10).

Validation-first: every rejection names the offending frames/tiles/colors and
suggests the fix. Nothing is ever silently quantized (--auto-fix quantizes
LOUDLY and writes a preview PNG). See docs/troubleshooting.md.

Examples:
  python3 tools/png2snes.py sprite art/knight_/idle_ --size 16 --name knight \\
      --out assets/knight.inc
  python3 tools/png2snes.py sprite art/arthur.png --frame 32x32 --size 32 \\
      --name arthur --out assets/arthur.inc
  python3 tools/png2snes.py bg art/tileset.png --region 0,0,64,64 \\
      --name terrain --out assets/terrain.inc
"""

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("png2snes.py needs Pillow: pip install Pillow (tools/setup.sh installs it)")


class ValidationError(Exception):
    """Input violates a hardware constraint. Message is the full user-facing report."""


# ----------------------------------------------------------------------------
# shared helpers
# ----------------------------------------------------------------------------

def rgb_to_bgr15(rgb):
    r, g, b = rgb
    return (r >> 3) | ((g >> 3) << 5) | ((b >> 3) << 10)


def natural_key(path):
    """Sort key treating digit runs numerically, so frame_10 follows frame_9
    (plain lexicographic order would shuffle >=10-frame animations)."""
    import re
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", path.name)]


def load_rgba(path):
    """Normalize any input mode to RGBA. P-mode transparency index and RGBA
    alpha both become alpha; '1'/'L'/'RGB' are fully opaque."""
    img = Image.open(path)
    return img.convert("RGBA")


def rgba_pixels(img):
    """RGBA image -> flat list of (r,g,b,a) tuples (avoids the deprecated
    getdata() so converter runs stay warning-free for the agent)."""
    raw = img.tobytes()
    return [tuple(raw[i:i + 4]) for i in range(0, len(raw), 4)]


def opaque_colors(img):
    """Distinct opaque (alpha>=128) RGB colors in an RGBA image."""
    return {p[:3] for p in rgba_pixels(img) if p[3] >= 128}


def detect_integer_scale(img):
    """Largest k such that the image is a clean k x k upscale (every k x k
    block uniform). 1 = native-resolution pixel art (or not pixel art)."""
    w, h = img.size
    data = rgba_pixels(img)
    for k in range(8, 1, -1):
        if w % k or h % k:
            continue
        ok = True
        for by in range(0, h, k):
            for bx in range(0, w, k):
                p0 = data[by * w + bx]
                for dy in range(k):
                    for dx in range(k):
                        if data[(by + dy) * w + bx + dx] != p0:
                            ok = False
                            break
                    if not ok:
                        break
                if not ok:
                    break
            if not ok:
                break
        if ok:
            return k
    return 1


def encode_tile_4bpp(pix):
    """8x8 list-of-rows of palette indices 0..15 -> 32 bytes SNES 4bpp planar.
    Asserts the index range — the encoder NEVER masks (the parent repo's
    silent `& 0x03` quantization incident is the canonical scar)."""
    out = bytearray(32)
    for y in range(8):
        b0 = b1 = b2 = b3 = 0
        for x in range(8):
            v = pix[y][x]
            assert 0 <= v <= 15, f"palette index {v} out of 4bpp range (encoder bug)"
            bit = 7 - x
            b0 |= ((v >> 0) & 1) << bit
            b1 |= ((v >> 1) & 1) << bit
            b2 |= ((v >> 2) & 1) << bit
            b3 |= ((v >> 3) & 1) << bit
        out[y * 2] = b0
        out[y * 2 + 1] = b1
        out[16 + y * 2] = b2
        out[16 + y * 2 + 1] = b3
    return bytes(out)


def index_frame(img, color_to_index):
    """RGBA image -> rows of palette indices (transparent -> 0)."""
    w, h = img.size
    data = rgba_pixels(img)
    rows = []
    for y in range(h):
        row = []
        for x in range(w):
            p = data[y * w + x]
            row.append(color_to_index[p[:3]] if p[3] >= 128 else 0)
        rows.append(row)
    return rows


def emit_bytes(label, blob, per_line=16):
    lines = [f"{label}:"]
    for i in range(0, len(blob), per_line):
        chunk = ", ".join(f"${b:02X}" for b in blob[i:i + per_line])
        lines.append(f"    .byte {chunk}")
    return "\n".join(lines)


def emit_words(label, words, per_line=8):
    lines = [f"{label}:"]
    for i in range(0, len(words), per_line):
        chunk = ", ".join(f"${w:04X}" for w in words[i:i + per_line])
        lines.append(f"    .word {chunk}")
    return "\n".join(lines)


def build_palette(colors):
    """Deterministic palette: index 0 transparent, 1..15 sorted by luminance
    then RGB (dark -> light, stable across runs)."""
    ordered = sorted(colors, key=lambda c: (c[0] * 299 + c[1] * 587 + c[2] * 114, c))
    pal = [(0, 0, 0)] + ordered  # entry 0 is transparent (value unused by HW)
    color_to_index = {c: i + 1 for i, c in enumerate(ordered)}
    words = [rgb_to_bgr15(c) for c in pal] + [0] * (16 - len(pal))
    return words, color_to_index


# ----------------------------------------------------------------------------
# sprite subcommand
# ----------------------------------------------------------------------------

def collect_frames(input_path, frame_spec):
    """-> list of (anim_name, frame_name, RGBA image).

    PNG file: cut into frame_spec (WxH) grid cells, row-major, skipping empty
    cells; one animation named 'all' (or whole image if no --frame).
    Directory: PNGs directly inside = one animation named after the dir;
    subdirectories containing PNGs = one animation each (sorted)."""
    p = Path(input_path)
    frames = []
    if p.is_file():
        img = load_rgba(p)
        if frame_spec is None:
            frames.append(("all", p.stem, img))
        else:
            fw, fh = frame_spec
            w, h = img.size
            if w % fw or h % fh:
                raise ValidationError(
                    f"{p.name}: image {w}x{h} is not divisible into --frame "
                    f"{fw}x{fh} cells. Check the grid size against the sheet."
                )
            n = 0
            for fy in range(h // fh):
                for fx in range(w // fw):
                    cell = img.crop((fx * fw, fy * fh, (fx + 1) * fw, (fy + 1) * fh))
                    if cell.getchannel("A").getbbox():
                        frames.append(("all", f"r{fy}c{fx}", cell))
                        n += 1
            if not n:
                raise ValidationError(f"{p.name}: no non-empty {fw}x{fh} cells found.")
    elif p.is_dir():
        subdirs = sorted((d for d in p.iterdir()
                          if d.is_dir() and list(d.glob("*.png"))), key=natural_key)
        pngs = sorted(p.glob("*.png"), key=natural_key)
        if pngs:
            for f in pngs:
                frames.append((p.name.strip("_") or "all", f.stem, load_rgba(f)))
        for d in subdirs:
            for f in sorted(d.glob("*.png"), key=natural_key):
                frames.append((d.name.strip("_"), f.stem, load_rgba(f)))
        if not frames:
            raise ValidationError(f"{p}: no .png files found (directly or one level down).")
    else:
        raise ValidationError(f"{input_path}: not a file or directory.")
    return frames


def recenter(img, size, anchor):
    """Fit a frame's opaque content into a size x size box, or explain why not."""
    a = img.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
    bbox = a.getbbox()
    if bbox is None:
        return Image.new("RGBA", (size, size), (0, 0, 0, 0)), None
    x0, y0, x1, y1 = bbox
    cw, ch = x1 - x0, y1 - y0
    if cw > size or ch > size:
        return None, (cw, ch)
    content = img.crop(bbox)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ox = (size - cw) // 2
    oy = (size - ch) if anchor == "bottom" else (size - ch) // 2
    out.paste(content, (ox, oy))
    return out, None


# OBJ VRAM grid: 16 tiles per row; an NxN sprite is N/8 x N/8 tiles whose rows
# sit +16 tile numbers apart (hardware-fixed). Frames pack left-to-right.
def content_bottom(boxed):
    """Max over frames of the drawn content's bottom edge (exclusive row
    index) inside the box. Sprites rarely fill their cell — anchoring an
    actor's FEET to a surface needs this, not the box height (the brawler's
    floating-feet lesson: a box-edge clamp leaves the art's empty bottom
    rows as a visible sky gap)."""
    bot = 0
    for _, _, img in boxed:
        a = img.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
        bb = a.getbbox()
        if bb:
            bot = max(bot, bb[3])
    return bot


def grid_layout(n_frames, size):
    t = size // 8                       # tiles per side (1, 2, or 4)
    per_row = 16 // t                   # frames per 16-tile grid row-group
    placements = []                     # frame -> top-left tile offset
    for f in range(n_frames):
        row_group = f // per_row
        col = f % per_row
        placements.append(row_group * t * 16 + col * t)
    rows_used = ((n_frames + per_row - 1) // per_row) * t
    return placements, rows_used


def parse_anims_spec(spec, n_collected):
    """--anims "idle:0-3,run:8-11+16-19" -> ordered dict anim -> list of
    collected-frame indices. Multi-ranges (+) concatenate."""
    anims = {}
    for part in spec.split(","):
        try:
            aname, ranges = part.split(":")
        except ValueError:
            raise ValidationError(f"--anims: each entry wants name:A-B[+C-D], got {part!r}")
        if not aname.isidentifier():
            raise ValidationError(f"--anims: {aname!r} is not a valid symbol name")
        idxs = []
        for rng in ranges.split("+"):
            try:
                a, b = (int(v) for v in rng.split("-"))
            except ValueError:
                raise ValidationError(f"--anims: bad range {rng!r} in {part!r}")
            if a > b:
                raise ValidationError(
                    f"--anims: reversed range {rng} (first index must not "
                    f"exceed the second — did you mean {b}-{a}?).")
            if b >= n_collected:
                raise ValidationError(
                    f"--anims: range {rng} out of bounds — input has "
                    f"{n_collected} collected frame(s) (0-{n_collected - 1}).")
            idxs.extend(range(a, b + 1))
        anims[aname] = idxs
    return anims


def cmd_sprite(args):
    size = args.size
    frames = collect_frames(args.input, args.frame)
    if args.frames:
        a, b = args.frames
        if b >= len(frames):
            raise ValidationError(f"--frames {a}-{b}: only {len(frames)} frame(s) "
                                  "collected from the input.")
        frames = frames[a:b + 1]
    anim_spec = None
    if args.anims:
        # keep ONLY the frames the animations reference (ordered dedup), and
        # remap each animation onto the kept-frame indices
        anim_spec = parse_anims_spec(args.anims, len(frames))
        keep = []
        for idxs in anim_spec.values():
            for i in idxs:
                if i not in keep:
                    keep.append(i)
        remap = {old: new for new, old in enumerate(keep)}
        frames = [frames[i] for i in keep]
        anim_spec = {aname: [remap[i] for i in idxs]
                     for aname, idxs in anim_spec.items()}

    # ---- validation: one <=15-color palette across the whole set ----
    all_colors = set()
    per_frame = []
    for anim, name, img in frames:
        c = opaque_colors(img)
        all_colors |= c
        per_frame.append((anim, name, len(c)))
    if len(all_colors) > 15:
        worst = sorted(per_frame, key=lambda t: -t[2])[:5]
        worst_s = ", ".join(f"{a}/{n} ({c} colors)" for a, n, c in worst)
        first = frames[0][2]
        scale = detect_integer_scale(first)
        scale_note = ""
        if scale == 1 and max(first.size) > 48:
            scale_note = (
                "\nThis does not look like hardware-scale pixel art (no clean "
                "integer upscale detected, large frame, smooth shading). "
                "Converting it faithfully is impossible — downscale+quantize "
                "produces mush."
            )
        msg = (
            f"REJECT: {len(all_colors)} distinct opaque colors across "
            f"{len(frames)} frame(s); an SNES OBJ palette holds 15 + transparent."
            f"\nBusiest frames: {worst_s}.{scale_note}"
            "\nOptions: (a) redraw/commission the art at SNES scale with <=15 "
            "colors, (b) split animations that use disjoint colors into "
            "separate conversions (one palette each), (c) re-run with "
            "--auto-fix to quantize to 15 colors (LOSSY — a preview PNG is "
            "written so you can judge the damage)."
        )
        if not args.auto_fix:
            raise ValidationError(msg)
        # loud, previewed quantization — against ONE palette shared by every
        # frame (per-frame quantization can still leave a >15-color union)
        print(f"[auto-fix] {len(all_colors)} colors -> 15 (LOSSY). Preview PNGs "
              f"written next to {args.out}.", file=sys.stderr)
        frames = quantize_frames_shared(frames, 15)
        all_colors = set()
        for _, _, img in frames:
            all_colors |= opaque_colors(img)
        assert len(all_colors) <= 15, "auto-fix shared palette overflow (tool bug)"
        prev = Path(args.out).with_suffix(".preview.png")
        frames[0][2].save(prev)
        print(f"[auto-fix] preview: {prev}", file=sys.stderr)

    pal_words, c2i = build_palette(all_colors)

    if args.meta:
        emit_meta(args, frames, all_colors, pal_words, c2i, anim_spec)
        return

    # ---- re-center each frame into the OBJ box ----
    boxed = []
    too_big = []
    for anim, name, img in frames:
        if img.size == (size, size):
            out, over = img, None  # already exact; keep author's framing
        else:
            out, over = recenter(img, size, args.anchor)
        if over:
            too_big.append((anim, name, over))
        else:
            boxed.append((anim, name, out))
    if too_big:
        listing = ", ".join(f"{a}/{n} (content {w}x{h})" for a, n, (w, h) in too_big[:8])
        more = f" (+{len(too_big) - 8} more)" if len(too_big) > 8 else ""
        bigger = {8: 16, 16: 32, 32: None}[size]
        sug = (f"re-run with --size {bigger}" if bigger
               else "this needs a metasprite (multiple OBJs) — not a single-sprite conversion")
        raise ValidationError(
            f"REJECT: {len(too_big)} frame(s) have opaque content larger than "
            f"the {size}x{size} OBJ box: {listing}{more}.\nOptions: {sug}, or "
            f"crop the source if the overflow is stray pixels."
        )

    # ---- encode CHR in VRAM-grid order ----
    placements, rows_used = grid_layout(len(boxed), size)
    t = size // 8
    blob = bytearray(rows_used * 16 * 32)   # 16 tiles per VRAM row, 32 B/tile
    for f, (anim, name, img) in enumerate(boxed):
        rows = index_frame(img, c2i)
        base = placements[f]
        for ty in range(t):
            for tx in range(t):
                tile_idx = base + ty * 16 + tx
                pix = [rows[ty * 8 + y][tx * 8:tx * 8 + 8] for y in range(8)]
                blob[tile_idx * 32:(tile_idx + 1) * 32] = encode_tile_4bpp(pix)

    # ---- emit ----
    name = args.name
    if anim_spec is not None:
        anims = anim_spec                    # --anims mapping (already remapped)
    else:
        anims = {}
        for f, (anim, _, _) in enumerate(boxed):
            anims.setdefault(anim, []).append(f)
    if anims and max(placements) > 255:
        raise ValidationError(
            f"REJECT: {len(boxed)} frames @ {size}x{size} put the last frame at "
            f"tile offset {max(placements)} — OAM tile numbers are 8-bit, so "
            f"animation tables can only span offsets 0-255. Trim the frame set "
            f"(--frames / --anims subsets) or split into two conversions at two "
            f"16-aligned bases.")
    lines = [
        f"; Generated by tools/png2snes.py — DO NOT EDIT BY HAND",
        f"; cmd: png2snes.py {' '.join(sys.argv[1:])}",
        f"; {len(boxed)} frame(s) @ {size}x{size}, {len(all_colors)} colors, "
        f"{rows_used} VRAM tile row(s) ({len(blob)} bytes)",
        f"; LOAD CONTRACT: upload {name}_chr at an OBJ tile index that is a",
        f"; MULTIPLE OF 16 (sf_load_obj_chr base, {name}_chr, {name}_chr_bytes).",
        f"; A frame's OAM tile = base + {name}_f<N>. 16x16+ sprites read their",
        f"; lower tile rows at +16 tile numbers — this blob is laid out for",
        f"; that, which is WHY base must be 16-aligned. Select an OBSEL size",
        f"; pair that includes {size}x{size}, and set the spr size flag (bit 7)",
        f"; to the pair half that is {size}x{size}.",
        f"",
        f"{name}_size      = {size}",
        f"{name}_frames    = {len(boxed)}",
        f"{name}_chr_bytes = {len(blob)}",
        f"{name}_pal_colors = {len(all_colors) + 1}",
        f"{name}_content_bottom = {content_bottom(boxed)}  "
        f"; lowest drawn row + 1 (max over frames) — anchor feet with "
        f"y = surface_top - this",
    ]
    for f, off in enumerate(placements):
        lines.append(f"{name}_f{f} = ${off:02X}")
    lines.append("")
    lines.append("; animation tables: BASE-RELATIVE TILE OFFSETS per frame step")
    lines.append("; (index with sf_anim_tile; add your load base; one byte per step)")
    for anim, fl in anims.items():
        lines.append(f"{name}_anim_{anim}_len = {len(fl)}")
        lines.append(f"{name}_anim_{anim}: .byte "
                     + ", ".join(f"${placements[f]:02X}" for f in fl))
    lines.append("")
    lines.append(emit_words(f"{name}_pal", pal_words))
    lines.append("")
    lines.append(emit_bytes(f"{name}_chr", blob))
    lines.append("")
    Path(args.out).write_text("\n".join(lines))
    print(f"sprite: {len(boxed)} frame(s) -> {args.out} "
          f"({len(blob)} CHR bytes, {len(all_colors)} colors, "
          f"{len(anims)} animation(s): {', '.join(anims)})")


def recenter_box(img, bw, bh, anchor):
    """Fit a frame's opaque content into a bw x bh box (the --meta variant)."""
    a = img.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
    bbox = a.getbbox()
    out = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    if bbox is None:
        return out
    content = img.crop(bbox)
    cw, ch = content.size
    ox = (bw - cw) // 2
    oy = (bh - ch) if anchor == "bottom" else (bh - ch) // 2
    out.paste(content, (ox, oy))
    return out


def meta_parts_layout(bw, bh):
    """Fixed tiling of a box into hardware parts under OBSEL pair 3:
    greedy 32x32 from the top-left, 16x16 for the remaining cells.
    -> list of (dx, dy, size_px)."""
    cw, ch = bw // 16, bh // 16
    used = [[False] * cw for _ in range(ch)]
    parts = []
    for cy in range(ch - 1):
        for cx in range(cw - 1):
            if not (used[cy][cx] or used[cy][cx + 1]
                    or used[cy + 1][cx] or used[cy + 1][cx + 1]):
                parts.append((cx * 16, cy * 16, 32))
                used[cy][cx] = used[cy][cx + 1] = True
                used[cy + 1][cx] = used[cy + 1][cx + 1] = True
    for cy in range(ch):
        for cx in range(cw):
            if not used[cy][cx]:
                parts.append((cx * 16, cy * 16, 16))
    return parts


def emit_meta(args, frames, all_colors, pal_words, c2i, anim_spec):
    """--meta: encode frames LARGER than one hardware sprite as multi-OBJ
    metasprites. Per frame: a parts table (count + entries of tile-offset
    word, dx, dy, large flag); plus a frame->table address index. Consumed
    by sf_meta_draw (lib/macros/sf_meta.inc), which REQUIRES OBSEL size
    pair 3 (16x16 small / 32x32 large)."""
    name = args.name
    # box = max content, rounded up to 16px (hardware part granularity)
    sizes = []
    for _, fname, img in frames:
        a = img.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
        bb = a.getbbox()
        if bb:
            sizes.append((bb[2] - bb[0], bb[3] - bb[1], fname))
    if not sizes:
        raise ValidationError("--meta: every frame is empty.")
    cw = max(s[0] for s in sizes)
    ch = max(s[1] for s in sizes)
    if cw > 64 or ch > 64:
        worst = max(sizes, key=lambda s: max(s[0], s[1]))
        raise ValidationError(
            f"REJECT: --meta content up to {cw}x{ch} (e.g. frame {worst[2]}) "
            "exceeds the 64x64 metasprite box this kit supports. Crop the "
            "source or split the actor.")
    bw, bh = ((cw + 15) // 16) * 16, ((ch + 15) // 16) * 16
    # frames already exactly box-sized keep the author's framing — per-frame
    # re-centering would make animations jitter when content shifts between
    # steps (same rule as the single-sprite path)
    boxed = [(anim, fname,
              img if img.size == (bw, bh) else recenter_box(img, bw, bh, args.anchor))
             for anim, fname, img in frames]
    layout = meta_parts_layout(bw, bh)

    # pass 1: collect non-empty parts per frame, assigned to the two pools
    frame_parts = []                  # per frame: list of (pool, idx, dx, dy, size)
    n_large = n_small = 0
    for anim, fname, img in boxed:
        plist = []
        for dx, dy, sz in layout:
            crop = img.crop((dx, dy, dx + sz, dy + sz))
            if not crop.getchannel("A").getbbox():
                continue                      # fully transparent part: no OBJ
            if sz == 32:
                plist.append(("L", n_large, dx, dy, sz, crop))
                n_large += 1
            else:
                plist.append(("S", n_small, dx, dy, sz, crop))
                n_small += 1
        frame_parts.append(plist)

    large_rows = ((n_large + 3) // 4) * 4 if n_large else 0
    small_rows = ((n_small + 7) // 8) * 2 if n_small else 0
    small_base = large_rows * 16

    def part_offset(pool, idx):
        if pool == "L":
            return (idx // 4) * 64 + (idx % 4) * 4
        return small_base + (idx // 8) * 32 + (idx % 8) * 2

    max_off = max((part_offset(p, i) for pl in frame_parts for p, i, *_ in pl),
                  default=0)
    if max_off > 511:
        raise ValidationError(
            f"REJECT: --meta needs tile offsets up to {max_off}; OAM tiles are "
            "9-bit (0-511). Trim the frame set (--frames / --anims) or split "
            "into two conversions.")

    # pass 2: encode CHR
    rows_used = large_rows + small_rows
    blob = bytearray(rows_used * 16 * 32)
    for plist in frame_parts:
        for pool, idx, dx, dy, sz, crop in plist:
            base = part_offset(pool, idx)
            t = sz // 8
            rows = index_frame(crop, c2i)
            for ty in range(t):
                for tx in range(t):
                    tile_idx = base + ty * 16 + tx
                    pix = [rows[ty * 8 + y][tx * 8:tx * 8 + 8] for y in range(8)]
                    blob[tile_idx * 32:(tile_idx + 1) * 32] = encode_tile_4bpp(pix)

    # ---- emit ----
    if anim_spec is not None:
        anims = anim_spec
    else:
        anims = {}
        for f, (anim, _, _) in enumerate(boxed):
            anims.setdefault(anim, []).append(f)
    lines = [
        f"; Generated by tools/png2snes.py — DO NOT EDIT BY HAND",
        f"; cmd: png2snes.py {' '.join(sys.argv[1:])}",
        f"; METASPRITE: {len(boxed)} frame(s), box {bw}x{bh}, "
        f"{n_large} large + {n_small} small parts, {rows_used} VRAM rows",
        f"; LOAD CONTRACT: sf_load_obj_chr at a 16-aligned base; draw with",
        f"; sf_meta_draw (sf_meta.inc) — REQUIRES OBSEL size pair 3",
        f"; ($2101 = $60: 16x16 small / 32x32 large). Animation tables hold",
        f"; FRAME INDICES into {name}_parts_index (unlike single-sprite",
        f"; conversions, whose anim tables hold tile offsets).",
        f"",
        f"{name}_meta      = 1",
        f"{name}_box_w     = {bw}",
        f"{name}_box_h     = {bh}",
        f"{name}_content_bottom = {content_bottom(boxed)}  "
        f"; lowest drawn row + 1 (max over frames)",
        f"{name}_frames    = {len(boxed)}",
        f"{name}_chr_bytes = {len(blob)}",
        f"{name}_pal_colors = {len(all_colors) + 1}",
        f"",
        f"; per-frame parts: .byte count, then per part:",
        f";   .word tile-offset (base-relative) ; .byte dx ; .byte dy ; .byte large",
    ]
    for f, plist in enumerate(frame_parts):
        lines.append(f"{name}_f{f}_parts:")
        lines.append(f"    .byte {len(plist)}")
        for pool, idx, dx, dy, sz, _ in plist:
            lines.append(f"    .word ${part_offset(pool, idx):03X}")
            lines.append(f"    .byte {dx}, {dy}, {1 if sz == 32 else 0}")
    lines.append("")
    lines.append(f"{name}_parts_index:")
    lines.append("    .word " + ", ".join(f"{name}_f{f}_parts"
                                          for f in range(len(boxed))))
    lines.append("")
    lines.append("; animation tables: FRAME INDICES (meta mode)")
    for anim, fl in anims.items():
        lines.append(f"{name}_anim_{anim}_len = {len(fl)}")
        lines.append(f"{name}_anim_{anim}: .byte " + ", ".join(str(f) for f in fl))
    lines.append("")
    lines.append(emit_words(f"{name}_pal", pal_words))
    lines.append("")
    lines.append(emit_bytes(f"{name}_chr", blob))
    lines.append("")
    Path(args.out).write_text("\n".join(lines))
    print(f"meta: {len(boxed)} frame(s), box {bw}x{bh} -> {args.out} "
          f"({n_large}L+{n_small}S parts, {len(blob)} CHR bytes, "
          f"{len(all_colors)} colors)")


def quantize_frames_shared(frames, n):
    """Lossy reduction of ALL frames to one shared n-color palette,
    preserving transparency (auto-fix path only). A per-frame quantize would
    give each frame its own n colors and the union could still bust the
    budget — so the palette is derived from a strip of every frame."""
    strip = Image.new("RGB", (sum(i.size[0] for _, _, i in frames),
                              max(i.size[1] for _, _, i in frames)))
    x = 0
    for _, _, img in frames:
        strip.paste(img.convert("RGB"), (x, 0))
        x += img.size[0]
    pal_img = strip.quantize(colors=n, dither=Image.Dither.NONE)
    out = []
    for anim, name, img in frames:
        alpha = img.getchannel("A").point(lambda v: 255 if v >= 128 else 0)
        q = (img.convert("RGB")
                .quantize(palette=pal_img, dither=Image.Dither.NONE)
                .convert("RGBA"))
        q.putalpha(alpha)
        out.append((anim, name, q))
    return out


# ----------------------------------------------------------------------------
# bg subcommand
# ----------------------------------------------------------------------------

def group_palettes(tile_sets):
    """Group per-tile color-sets into <=8 palettes of <=15 colors.

    Best-fit-decreasing on the UNIQUE color-sets: place each set into the
    existing palette that already shares the most colors with it (fewest new
    colors added) if the union stays <=15; then a pairwise merge pass.
    Returns (palettes: list[set], set_to_pal: dict[frozenset, int])."""
    uniq = {}
    for pos, s in tile_sets.items():
        uniq.setdefault(s, []).append(pos)
    sets = sorted(uniq, key=lambda s: (-len(s), sorted(s)))
    palettes = []          # list of (color_set, member_sets)
    for s in sets:
        best, best_added = None, None
        for i, (pcols, members) in enumerate(palettes):
            added = len(s - pcols)
            if len(pcols | s) <= 15 and (best_added is None or added < best_added):
                best, best_added = i, added
        if best is None:
            palettes.append((set(s), [s]))
        else:
            pcols, members = palettes[best]
            pcols |= s
            members.append(s)
    # pairwise merge pass (cheap set-cover improvement over plain greedy)
    merged = True
    while merged and len(palettes) > 1:
        merged = False
        for i in range(len(palettes)):
            for j in range(i + 1, len(palettes)):
                if len(palettes[i][0] | palettes[j][0]) <= 15:
                    palettes[i][0].update(palettes[j][0])
                    palettes[i][1].extend(palettes[j][1])
                    del palettes[j]
                    merged = True
                    break
            if merged:
                break
    set_to_pal = {}
    for i, (_, members) in enumerate(palettes):
        for s in members:
            set_to_pal[s] = i
    return [p for p, _ in palettes], set_to_pal, uniq


def cmd_bg(args):
    img = load_rgba(args.input)
    if args.region:
        x, y, w, h = args.region
        if x % 8 or y % 8 or w % 8 or h % 8:
            raise ValidationError("--region x,y,w,h must all be multiples of 8 "
                                  "(SNES BG tiles are 8x8).")
        iw, ih = img.size
        if x + w > iw or y + h > ih:
            raise ValidationError(
                f"--region {x},{y},{w},{h} runs past the image edge — "
                f"{args.input} is {iw}x{ih}. (Out-of-bounds area would convert "
                f"as blank tiles, silently.)")
        img = img.crop((x, y, x + w, y + h))
    W, H = img.size
    if W % 8 or H % 8:
        raise ValidationError(f"{args.input}: {W}x{H} is not a multiple of 8 — "
                              "crop or pad the tileset, or pass --region.")
    mw, mh = W // 8, H // 8

    # ---- per-tile color budget ----
    cells = {}
    over = []
    for ty in range(mh):
        for tx in range(mw):
            cell = img.crop((tx * 8, ty * 8, tx * 8 + 8, ty * 8 + 8))
            cols = frozenset(opaque_colors(cell))
            cells[(tx, ty)] = (cell, cols)
            if len(cols) > 15:
                over.append((tx, ty, len(cols)))
    if over:
        listing = ", ".join(f"tile ({tx},{ty}) px ({tx*8},{ty*8}): {n} colors"
                            for tx, ty, n in over[:8])
        raise ValidationError(
            f"REJECT: {len(over)} 8x8 tile(s) exceed 15 colors + transparent: "
            f"{listing}. Reduce colors in those tiles, or exclude them with "
            f"--region."
        )

    # ---- global palette grouping (<=8 hardware BG palettes) ----
    occupied = {pos: cols for pos, (_, cols) in cells.items() if cols}
    palettes, set_to_pal, uniq = group_palettes(occupied)
    if len(palettes) > 8:
        report = []
        for i, p in enumerate(palettes):
            forcing = next(pos for s, poss in uniq.items() if set_to_pal[s] == i
                           for pos in poss)
            report.append(f"  palette {i}: {len(p)} colors "
                          f"(e.g. tile {forcing} at px {forcing[0]*8},{forcing[1]*8})")
        raise ValidationError(
            f"REJECT: tiles need {len(palettes)} palettes; SNES BG hardware "
            f"has 8.\n" + "\n".join(report) +
            "\nOptions: (a) convert a sub-region (--region x,y,w,h) — e.g. one "
            "season/biome at a time, (b) merge near-duplicate colors in the "
            "source, (c) drop decoration tiles that force rare palettes."
        )

    pal_tables = []
    pal_c2i = []
    for p in palettes:
        words, c2i = build_palette(p)
        pal_tables.append(words)
        pal_c2i.append(c2i)

    # ---- dedupe + encode; blob index 0 is RESERVED as the blank tile ----
    chr_blobs = [bytes(32)]
    tile_cache = {bytes(32): 0}
    map_words = []
    base = args.base_tile
    for ty in range(mh):
        for tx in range(mw):
            cell, cols = cells[(tx, ty)]
            if not cols:
                map_words.append(base & 0x3FF)   # blank tile, palette 0
                continue
            pal = set_to_pal[cols]
            rows = index_frame(cell, pal_c2i[pal])
            enc = encode_tile_4bpp(rows)
            if enc not in tile_cache:
                tile_cache[enc] = len(chr_blobs)
                chr_blobs.append(enc)
            map_words.append(((base + tile_cache[enc]) & 0x3FF) | (pal << 10))

    n_tiles = len(chr_blobs)
    if base + n_tiles > 1024:
        raise ValidationError(f"REJECT: {n_tiles} unique tiles at base {base} "
                              "exceeds the 1024-tile BG CHR space.")
    blob = b"".join(chr_blobs)
    name = args.name
    pal_flat = [w for tbl in pal_tables for w in tbl]
    lines = [
        f"; Generated by tools/png2snes.py — DO NOT EDIT BY HAND",
        f"; cmd: png2snes.py {' '.join(sys.argv[1:])}",
        f"; {mw}x{mh} cells, {n_tiles} unique tiles (incl. reserved blank #0), "
        f"{len(palettes)} BG palette(s)",
        f"; LOAD CONTRACT: sf_load_bg_chr {base}, {name}_chr, {name}_chr_bytes",
        f"; then sf_load_bg_pals 0, {name}_pal, {name}_pal_count — map words",
        f"; already carry tile index (base {base} baked in) and palette bits;",
        f"; pass them straight to mset. If you also use sf_text, keep",
        f"; base + tiles <= 80 (the font owns BG1 tiles 80-127).",
        f"",
        f"{name}_chr_tiles = {n_tiles}",
        f"{name}_chr_bytes = {len(blob)}",
        f"{name}_pal_count = {len(palettes)}",
        f"{name}_map_w = {mw}",
        f"{name}_map_h = {mh}",
        f"",
        emit_words(f"{name}_pal", pal_flat),
        f"",
        emit_words(f"{name}_map", map_words),
        f"",
        emit_bytes(f"{name}_chr", blob),
        f"",
    ]
    Path(args.out).write_text("\n".join(lines))
    if base + n_tiles > 80:
        print(f"note: base {base} + {n_tiles} tiles = {base + n_tiles} > 80 — "
              "collides with the sf_text font (BG1 tiles 80-127) if you use text.",
              file=sys.stderr)
    print(f"bg: {mw}x{mh} cells -> {args.out} ({n_tiles} tiles, "
          f"{len(palettes)} palette(s), {len(blob)} CHR bytes)")


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def parse_frame(s):
    try:
        w, h = s.lower().split("x")
        return int(w), int(h)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--frame wants WxH (e.g. 32x32), got {s!r}")


def parse_range(s):
    try:
        a, b = s.split("-")
        return int(a), int(b)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--frames wants A-B (e.g. 0-7), got {s!r}")


def parse_region(s):
    try:
        x, y, w, h = (int(v) for v in s.split(","))
        return x, y, w, h
    except ValueError:
        raise argparse.ArgumentTypeError(f"--region wants x,y,w,h, got {s!r}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("sprite", help="PNG sheet/folder -> OBJ CHR + palette .inc")
    sp.add_argument("input", help="PNG sheet, or folder of frame PNGs "
                    "(subfolders = animations)")
    sp.add_argument("--name", required=True, help="symbol prefix in the .inc")
    sp.add_argument("--out", required=True, help="output .inc path")
    sp.add_argument("--size", type=int, choices=(8, 16, 32), default=16,
                    help="OBJ box size (default 16)")
    sp.add_argument("--frame", type=parse_frame, default=None,
                    help="grid cell WxH when input is a sheet PNG")
    sp.add_argument("--frames", type=parse_range, default=None,
                    help="keep only frames A-B (inclusive) of the collected set "
                    "(e.g. one animation row of a sheet)")
    sp.add_argument("--meta", action="store_true",
                    help="metasprite mode for content larger than one OBJ "
                    "(up to 64x64): emits per-frame multi-part tables for "
                    "sf_meta_draw instead of single-sprite frames")
    sp.add_argument("--anims", default=None,
                    help="named animations over collected-frame indices, e.g. "
                    "\"idle:0-3,run:8-11+16-19\" — only referenced frames are "
                    "kept, and per-animation tile-offset tables are emitted")
    sp.add_argument("--anchor", choices=("center", "bottom"), default="center",
                    help="content placement inside the OBJ box")
    sp.add_argument("--auto-fix", action="store_true",
                    help="quantize over-budget colors (LOSSY, writes a preview)")
    sp.set_defaults(fn=cmd_sprite)

    bp = sub.add_parser("bg", help="tileset PNG -> BG CHR + palettes + map .inc")
    bp.add_argument("input", help="tileset PNG")
    bp.add_argument("--name", required=True, help="symbol prefix in the .inc")
    bp.add_argument("--out", required=True, help="output .inc path")
    bp.add_argument("--region", type=parse_region, default=None,
                    help="x,y,w,h sub-region to convert (8px-aligned)")
    bp.add_argument("--base-tile", type=int, default=0,
                    help="BG CHR tile index the blob will be loaded at (baked "
                    "into the map words; default 0)")
    bp.set_defaults(fn=cmd_bg)

    args = ap.parse_args(argv)
    try:
        args.fn(args)
    except ValidationError as e:
        print(f"png2snes: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
