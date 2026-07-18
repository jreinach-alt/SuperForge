"""
Phase 8E: Mode 7 Asset Pipeline

Converts Mode 7 tilesets, tilemaps, and palettes into SNES-compatible binary
formats. Handles the interleaved VRAM layout unique to Mode 7.

Mode 7 VRAM Format (lower 32 KB):
  Each VRAM word address contains:
    low byte  = tilemap entry (tile index 0-255)
    high byte = tile data byte (8bpp pixel data)
  Tilemap:  128x128 entries = 16,384 bytes (single-byte tile indices)
  Tiledata: 256 tiles x 64 bytes = 16,384 bytes (8x8 pixels, 8bpp)
  Total:    32,768 bytes interleaved (16K words)

  Interleaving: VRAM word 0 = [map[0], tile[0]],
                VRAM word 1 = [map[1], tile[1]], etc.

Color format: SNES BGR555 (little-endian 16-bit)
  Byte 0: gggrrrrr  (low 5 bits of green + 5 bits of red)
  Byte 1: 0bbbbbgg  (5 bits of blue + high 2 bits of green)

References:
  - docs/sprints/phase_8_mode7.md
  - toolchain/graphics.py (existing pipeline patterns)
  - docs/superforge_vram_partitions_v0.1.md
"""

from __future__ import annotations

import logging
import struct
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODE7_TILEMAP_WIDTH = 128
MODE7_TILEMAP_HEIGHT = 128
MODE7_TILEMAP_SIZE = MODE7_TILEMAP_WIDTH * MODE7_TILEMAP_HEIGHT  # 16,384
MODE7_MAX_TILES = 256
MODE7_TILE_SIZE = 8  # 8x8 pixels
MODE7_TILE_BYTES = MODE7_TILE_SIZE * MODE7_TILE_SIZE  # 64 bytes per tile (8bpp)
MODE7_TILEDATA_SIZE = MODE7_MAX_TILES * MODE7_TILE_BYTES  # 16,384
MODE7_INTERLEAVED_SIZE = MODE7_TILEMAP_SIZE + MODE7_TILEDATA_SIZE  # 32,768
MODE7_PALETTE_COLORS = 256
MODE7_PALETTE_SIZE = MODE7_PALETTE_COLORS * 2  # 512 bytes (BGR555)


# ---------------------------------------------------------------------------
# SNES Color Conversion
# ---------------------------------------------------------------------------

def rgb_to_bgr555(r: int, g: int, b: int) -> int:
    """Convert 8-bit RGB to 16-bit SNES BGR555.

    Uses truncation (>> 3) to convert 8-bit channels to 5-bit.

    Args:
        r: Red channel (0-255).
        g: Green channel (0-255).
        b: Blue channel (0-255).

    Returns:
        16-bit BGR555 value: 0bbbbbgggggrrrrr.
    """
    r5 = (r >> 3) & 0x1F
    g5 = (g >> 3) & 0x1F
    b5 = (b >> 3) & 0x1F
    return (b5 << 10) | (g5 << 5) | r5


def bgr555_to_rgb(bgr: int) -> tuple[int, int, int]:
    """Convert 16-bit SNES BGR555 to 8-bit RGB.

    Reconstructs 8-bit values by replicating the top bits into the low bits
    for better color accuracy (e.g., 5-bit 31 -> 8-bit 255).

    Args:
        bgr: 16-bit BGR555 value.

    Returns:
        Tuple of (r, g, b) in range 0-255.
    """
    r5 = bgr & 0x1F
    g5 = (bgr >> 5) & 0x1F
    b5 = (bgr >> 10) & 0x1F
    return (
        (r5 << 3) | (r5 >> 2),
        (g5 << 3) | (g5 >> 2),
        (b5 << 3) | (b5 >> 2),
    )


# ---------------------------------------------------------------------------
# Mode 7 Tileset Converter
# ---------------------------------------------------------------------------

def convert_mode7_tileset(image_path: str) -> bytes:
    """Convert a PNG image to Mode 7 8bpp tile data.

    Input: PNG image where tiles are arranged in a grid (16 tiles wide).
    Each tile is 8x8 pixels. Maximum 256 tiles.
    Pixel values are palette indices (0-255) in an indexed-color PNG,
    OR for RGB PNGs, build the palette from unique colors.

    Output: Raw 8bpp tile data, 64 bytes per tile, tiles in sequence.
    Each tile's 64 bytes are the pixel values row by row (8 bytes per row).
    Padded to exactly 16,384 bytes (256 tiles).

    Args:
        image_path: Path to the source PNG image.

    Returns:
        16,384 bytes of 8bpp tile data.

    Raises:
        ValueError: If image dimensions are not tile-aligned or too many tiles.
    """
    try:
        from PIL import Image
    except ImportError:
        raise ImportError(
            "PIL/Pillow is required for PNG image conversion. "
            "Install with: pip install Pillow"
        )

    path = Path(image_path)
    img = Image.open(path)

    # Validate dimensions are tile-aligned
    if img.width % MODE7_TILE_SIZE != 0 or img.height % MODE7_TILE_SIZE != 0:
        raise ValueError(
            f"{path.name}: dimensions {img.width}x{img.height} "
            f"not divisible by tile size {MODE7_TILE_SIZE}"
        )

    tiles_w = img.width // MODE7_TILE_SIZE
    tiles_h = img.height // MODE7_TILE_SIZE
    tile_count = tiles_w * tiles_h

    if tile_count > MODE7_MAX_TILES:
        raise ValueError(
            f"{path.name}: {tile_count} tiles exceed Mode 7 maximum of "
            f"{MODE7_MAX_TILES} (image has {tiles_w}x{tiles_h} tiles)"
        )

    # Get pixel data as palette indices
    if img.mode == 'P':
        # Indexed image: pixel values are already palette indices
        pixel_data = list(img.tobytes())
    elif img.mode in ('RGB', 'RGBA'):
        # RGB image: build palette from unique colors
        pixel_data, _ = _rgb_to_indexed(img)
    else:
        raise ValueError(
            f"{path.name}: unsupported color mode '{img.mode}'. "
            f"Expected indexed (P), RGB, or RGBA."
        )

    # Validate all pixel values are in range
    max_idx = max(pixel_data) if pixel_data else 0
    if max_idx > 255:
        raise ValueError(
            f"{path.name}: pixel index {max_idx} exceeds Mode 7 maximum of 255"
        )

    # Extract tiles: each tile is 8x8 pixels = 64 bytes, row-major
    output = bytearray()
    for ty in range(tiles_h):
        for tx in range(tiles_w):
            for row in range(MODE7_TILE_SIZE):
                offset = (ty * MODE7_TILE_SIZE + row) * img.width + (tx * MODE7_TILE_SIZE)
                for col in range(MODE7_TILE_SIZE):
                    output.append(pixel_data[offset + col])

    # Pad to full 256 tiles (fill unused tiles with zeros)
    while len(output) < MODE7_TILEDATA_SIZE:
        output.append(0x00)

    logger.info(
        f"[MODE7] {path.name}: converted {tile_count} tiles "
        f"({tiles_w}x{tiles_h} grid, {len(output)} bytes)"
    )

    return bytes(output)


def _rgb_to_indexed(img) -> tuple[list[int], list[tuple[int, int, int]]]:
    """Convert an RGB/RGBA image to indexed pixel data + palette.

    Builds a palette from unique colors encountered in the image.
    Supports up to 256 unique colors.

    Args:
        img: PIL Image in RGB or RGBA mode.

    Returns:
        (pixel_indices, palette_rgb) where:
          pixel_indices: list of int, one per pixel
          palette_rgb: list of (r, g, b) tuples, up to 256 entries

    Raises:
        ValueError: If more than 256 unique colors are found.
    """
    has_alpha = img.mode == 'RGBA'
    raw = img.tobytes()
    bpp = 4 if has_alpha else 3

    # Collect unique colors and build palette
    color_to_index: dict[tuple[int, int, int], int] = {}
    palette: list[tuple[int, int, int]] = []
    pixel_indices: list[int] = []

    num_pixels = img.width * img.height
    for i in range(num_pixels):
        offset = i * bpp
        r, g, b = raw[offset], raw[offset + 1], raw[offset + 2]

        # Treat fully transparent pixels as color index 0
        if has_alpha and raw[offset + 3] < 128:
            color = (0, 0, 0)
        else:
            color = (r, g, b)

        if color not in color_to_index:
            if len(palette) >= MODE7_PALETTE_COLORS:
                raise ValueError(
                    f"Image has more than {MODE7_PALETTE_COLORS} unique colors. "
                    f"Mode 7 supports a single 256-color palette."
                )
            color_to_index[color] = len(palette)
            palette.append(color)

        pixel_indices.append(color_to_index[color])

    return pixel_indices, palette


# ---------------------------------------------------------------------------
# Mode 7 Tilemap Converter
# ---------------------------------------------------------------------------

def convert_mode7_tilemap(map_data, width: int = 128, height: int = 128) -> bytes:
    """Convert a 128x128 tilemap to Mode 7 format.

    Input: 2D array (list of lists) or flat list of tile indices (0-255).
    Must be exactly width*height entries.

    Output: 16,384 bytes of tile indices in row-major order.

    Args:
        map_data: Tile indices as a 2D list[list[int]] or flat list[int].
        width: Tilemap width (must be 128 for Mode 7).
        height: Tilemap height (must be 128 for Mode 7).

    Returns:
        16,384 bytes of tilemap data.

    Raises:
        ValueError: If dimensions are wrong or indices are out of range.
    """
    # Flatten 2D array if needed
    if map_data and isinstance(map_data[0], (list, tuple)):
        flat = []
        for row in map_data:
            flat.extend(row)
    else:
        flat = list(map_data)

    expected_size = width * height
    if len(flat) != expected_size:
        raise ValueError(
            f"Tilemap has {len(flat)} entries, expected {expected_size} "
            f"({width}x{height})"
        )

    # Validate all indices are in range
    for i, idx in enumerate(flat):
        if idx < 0 or idx > 255:
            row = i // width
            col = i % width
            raise ValueError(
                f"Tilemap index {idx} at ({col}, {row}) is out of range [0, 255]"
            )

    # Pack as raw bytes (each index is a single byte)
    return bytes(flat)


# ---------------------------------------------------------------------------
# Interleaver
# ---------------------------------------------------------------------------

def interleave_mode7_data(tilemap: bytes, tiledata: bytes) -> bytes:
    """Interleave tilemap and tile data for Mode 7 VRAM upload.

    Takes 16,384 bytes of tilemap and 16,384 bytes of tile data.
    Produces 32,768 bytes where each word has [tilemap_byte, tiledata_byte].

    Output format: [map[0], tile[0], map[1], tile[1], ...]

    The SNES PPU reads Mode 7 VRAM as 16-bit words where the low byte
    is the tilemap and the high byte is the tile data.

    Args:
        tilemap: 16,384 bytes of tilemap entries.
        tiledata: 16,384 bytes of tile pixel data.

    Returns:
        32,768 bytes of interleaved data.

    Raises:
        ValueError: If input sizes are not exactly 16,384 bytes each.
    """
    if len(tilemap) != MODE7_TILEMAP_SIZE:
        raise ValueError(
            f"Tilemap size is {len(tilemap)} bytes, expected {MODE7_TILEMAP_SIZE}"
        )
    if len(tiledata) != MODE7_TILEDATA_SIZE:
        raise ValueError(
            f"Tile data size is {len(tiledata)} bytes, expected {MODE7_TILEDATA_SIZE}"
        )

    output = bytearray(MODE7_INTERLEAVED_SIZE)
    for i in range(MODE7_TILEMAP_SIZE):
        output[i * 2] = tilemap[i]
        output[i * 2 + 1] = tiledata[i]

    return bytes(output)


def deinterleave_mode7_data(interleaved: bytes) -> tuple[bytes, bytes]:
    """De-interleave Mode 7 VRAM data back into tilemap and tile data.

    Inverse of interleave_mode7_data(). Useful for verification and testing.

    Args:
        interleaved: 32,768 bytes of interleaved Mode 7 VRAM data.

    Returns:
        (tilemap, tiledata) each 16,384 bytes.

    Raises:
        ValueError: If input size is not exactly 32,768 bytes.
    """
    if len(interleaved) != MODE7_INTERLEAVED_SIZE:
        raise ValueError(
            f"Interleaved data size is {len(interleaved)} bytes, "
            f"expected {MODE7_INTERLEAVED_SIZE}"
        )

    tilemap = bytearray(MODE7_TILEMAP_SIZE)
    tiledata = bytearray(MODE7_TILEDATA_SIZE)

    for i in range(MODE7_TILEMAP_SIZE):
        tilemap[i] = interleaved[i * 2]
        tiledata[i] = interleaved[i * 2 + 1]

    return bytes(tilemap), bytes(tiledata)


# ---------------------------------------------------------------------------
# Palette Extractor
# ---------------------------------------------------------------------------

def extract_mode7_palette(image_path: str) -> bytes:
    """Extract the 256-color palette from a Mode 7 tileset PNG.

    For indexed PNGs: reads the embedded palette directly.
    For RGB PNGs: builds a palette from unique colors in the image.

    Output: 512 bytes (256 colors x 2 bytes SNES BGR555 format, little-endian).

    Args:
        image_path: Path to the source PNG image.

    Returns:
        512 bytes of SNES BGR555 palette data.

    Raises:
        ValueError: If the image has more than 256 colors.
    """
    try:
        from PIL import Image
    except ImportError:
        raise ImportError(
            "PIL/Pillow is required for PNG palette extraction. "
            "Install with: pip install Pillow"
        )

    path = Path(image_path)
    img = Image.open(path)

    if img.mode == 'P':
        # Indexed image: extract palette directly
        raw_palette = img.getpalette()
        if raw_palette is None:
            raise ValueError(f"{path.name}: indexed image has no palette")

        palette_rgb = []
        for i in range(0, len(raw_palette), 3):
            palette_rgb.append(
                (raw_palette[i], raw_palette[i + 1], raw_palette[i + 2])
            )
    elif img.mode in ('RGB', 'RGBA'):
        # RGB image: build palette from unique colors
        _, palette_rgb = _rgb_to_indexed(img)
    else:
        raise ValueError(
            f"{path.name}: unsupported color mode '{img.mode}'. "
            f"Expected indexed (P), RGB, or RGBA."
        )

    # Convert to SNES BGR555 and pack as little-endian 16-bit
    return _pack_bgr555_palette(palette_rgb)


def _pack_bgr555_palette(
    palette_rgb: list[tuple[int, int, int]],
    total_colors: int = MODE7_PALETTE_COLORS,
) -> bytes:
    """Pack an RGB palette into SNES BGR555 format.

    Args:
        palette_rgb: List of (r, g, b) tuples.
        total_colors: Total number of colors to output (pad with black).

    Returns:
        total_colors * 2 bytes of BGR555 palette data (little-endian).
    """
    output = bytearray()
    for i in range(total_colors):
        if i < len(palette_rgb):
            r, g, b = palette_rgb[i]
            bgr = rgb_to_bgr555(r, g, b)
        else:
            bgr = 0x0000  # Black for unused entries
        output.extend(struct.pack('<H', bgr))
    return bytes(output)


def build_palette_from_rgb(colors: list[tuple[int, int, int]]) -> bytes:
    """Build a 512-byte SNES BGR555 palette from a list of RGB colors.

    Convenience function for programmatic palette creation.

    Args:
        colors: List of (r, g, b) tuples, up to 256 entries.

    Returns:
        512 bytes of SNES BGR555 palette data.

    Raises:
        ValueError: If more than 256 colors provided.
    """
    if len(colors) > MODE7_PALETTE_COLORS:
        raise ValueError(
            f"Too many colors: {len(colors)}, maximum is {MODE7_PALETTE_COLORS}"
        )
    return _pack_bgr555_palette(colors)


# ---------------------------------------------------------------------------
# VRAM Validator
# ---------------------------------------------------------------------------

def validate_mode7_assets(
    tileset_path: str,
    tilemap_data,
    palette_path: Optional[str] = None,
) -> list[str]:
    """Validate Mode 7 assets against hardware constraints.

    Checks:
      - Tile count <= 256
      - Single 256-color palette
      - Tilemap is 128x128
      - All tilemap indices reference valid tiles

    Args:
        tileset_path: Path to the tileset PNG image.
        tilemap_data: 2D list or flat list of tile indices.
        palette_path: Optional path to a separate palette PNG.

    Returns:
        List of error strings. Empty list means all checks passed.
    """
    errors: list[str] = []

    # --- Validate tileset ---
    try:
        from PIL import Image
        img = Image.open(tileset_path)

        if img.width % MODE7_TILE_SIZE != 0 or img.height % MODE7_TILE_SIZE != 0:
            errors.append(
                f"Tileset dimensions {img.width}x{img.height} not divisible "
                f"by tile size {MODE7_TILE_SIZE}"
            )
        else:
            tiles_w = img.width // MODE7_TILE_SIZE
            tiles_h = img.height // MODE7_TILE_SIZE
            tile_count = tiles_w * tiles_h

            if tile_count > MODE7_MAX_TILES:
                errors.append(
                    f"Tileset has {tile_count} tiles, maximum is {MODE7_MAX_TILES}"
                )
    except ImportError:
        errors.append("PIL/Pillow not available for tileset validation")
    except Exception as e:
        errors.append(f"Cannot open tileset '{tileset_path}': {e}")

    # --- Validate tilemap ---
    # Flatten 2D array if needed
    if tilemap_data and isinstance(tilemap_data[0], (list, tuple)):
        flat = []
        for row in tilemap_data:
            flat.extend(row)
    else:
        flat = list(tilemap_data)

    expected_size = MODE7_TILEMAP_WIDTH * MODE7_TILEMAP_HEIGHT
    if len(flat) != expected_size:
        errors.append(
            f"Tilemap has {len(flat)} entries, expected {expected_size} "
            f"(128x128)"
        )

    # Check index range
    try:
        # Get actual tile count from tileset
        img = Image.open(tileset_path)
        tiles_w = img.width // MODE7_TILE_SIZE
        tiles_h = img.height // MODE7_TILE_SIZE
        actual_tile_count = tiles_w * tiles_h
    except Exception:
        actual_tile_count = MODE7_MAX_TILES  # Assume max if we cannot check

    for i, idx in enumerate(flat):
        if idx < 0 or idx > 255:
            row = i // MODE7_TILEMAP_WIDTH
            col = i % MODE7_TILEMAP_WIDTH
            errors.append(
                f"Tilemap index {idx} at ({col}, {row}) out of range [0, 255]"
            )
        elif idx >= actual_tile_count:
            row = i // MODE7_TILEMAP_WIDTH
            col = i % MODE7_TILEMAP_WIDTH
            errors.append(
                f"Tilemap index {idx} at ({col}, {row}) references tile "
                f"beyond tileset ({actual_tile_count} tiles available)"
            )

    # --- Validate palette (optional) ---
    if palette_path is not None:
        try:
            img = Image.open(palette_path)
            if img.mode == 'P':
                raw_palette = img.getpalette()
                if raw_palette is None:
                    errors.append("Palette image has no embedded palette")
                else:
                    num_colors = len(raw_palette) // 3
                    if num_colors > MODE7_PALETTE_COLORS:
                        errors.append(
                            f"Palette has {num_colors} colors, "
                            f"maximum is {MODE7_PALETTE_COLORS}"
                        )
        except ImportError:
            errors.append("PIL/Pillow not available for palette validation")
        except Exception as e:
            errors.append(f"Cannot open palette image '{palette_path}': {e}")

    return errors


# ---------------------------------------------------------------------------
# Pure-data validation (no PIL required)
# ---------------------------------------------------------------------------

def validate_mode7_data(
    tile_data: bytes,
    tilemap_data: bytes,
    palette_data: bytes,
) -> list[str]:
    """Validate pre-converted Mode 7 binary data against hardware constraints.

    This validator works on already-converted binary data and does not
    require PIL/Pillow.

    Args:
        tile_data: Raw 8bpp tile data (should be 16,384 bytes).
        tilemap_data: Raw tilemap data (should be 16,384 bytes).
        palette_data: Raw BGR555 palette data (should be 512 bytes).

    Returns:
        List of error strings. Empty list means all checks passed.
    """
    errors: list[str] = []

    if len(tile_data) != MODE7_TILEDATA_SIZE:
        errors.append(
            f"Tile data is {len(tile_data)} bytes, "
            f"expected {MODE7_TILEDATA_SIZE}"
        )

    if len(tilemap_data) != MODE7_TILEMAP_SIZE:
        errors.append(
            f"Tilemap is {len(tilemap_data)} bytes, "
            f"expected {MODE7_TILEMAP_SIZE}"
        )

    if len(palette_data) != MODE7_PALETTE_SIZE:
        errors.append(
            f"Palette is {len(palette_data)} bytes, "
            f"expected {MODE7_PALETTE_SIZE}"
        )

    # Count actual tiles (non-zero tile data)
    if len(tile_data) == MODE7_TILEDATA_SIZE:
        actual_tiles = 0
        for t in range(MODE7_MAX_TILES):
            tile_start = t * MODE7_TILE_BYTES
            tile_slice = tile_data[tile_start:tile_start + MODE7_TILE_BYTES]
            if any(b != 0 for b in tile_slice):
                actual_tiles = t + 1

        # Check tilemap references
        if len(tilemap_data) == MODE7_TILEMAP_SIZE:
            max_ref = max(tilemap_data) if tilemap_data else 0
            if max_ref >= actual_tiles and actual_tiles > 0:
                errors.append(
                    f"Tilemap references tile index {max_ref} but only "
                    f"{actual_tiles} non-empty tiles exist"
                )

    return errors


# ---------------------------------------------------------------------------
# Test Asset Generators
# ---------------------------------------------------------------------------

def generate_checkerboard_tileset() -> tuple[bytes, bytes, bytes]:
    """Generate a simple checkerboard tileset for testing.

    Returns (tile_data, tilemap, palette):
      - 2 tiles: tile 0 = all color 0 (black), tile 1 = all color 1 (white)
      - 128x128 tilemap alternating tiles 0 and 1 in a checkerboard pattern
      - Simple 256-color palette (color 0 = black, color 1 = white, rest = black)

    All outputs are correctly sized for Mode 7:
      tile_data: 16,384 bytes
      tilemap:   16,384 bytes
      palette:   512 bytes
    """
    # --- Tile data: 256 tiles x 64 bytes ---
    tile_data = bytearray(MODE7_TILEDATA_SIZE)

    # Tile 0: all pixels = color index 0 (black) -- already zero
    # Tile 1: all pixels = color index 1 (white)
    tile1_offset = MODE7_TILE_BYTES  # 64
    for i in range(MODE7_TILE_BYTES):
        tile_data[tile1_offset + i] = 1

    # --- Tilemap: 128x128, checkerboard pattern ---
    tilemap = bytearray(MODE7_TILEMAP_SIZE)
    for row in range(MODE7_TILEMAP_HEIGHT):
        for col in range(MODE7_TILEMAP_WIDTH):
            idx = row * MODE7_TILEMAP_WIDTH + col
            tilemap[idx] = (row + col) & 1  # Alternating 0 and 1

    # --- Palette: 256 colors x 2 bytes BGR555 ---
    palette_colors = [(0, 0, 0)] * MODE7_PALETTE_COLORS
    palette_colors[0] = (0, 0, 0)      # Black
    palette_colors[1] = (255, 255, 255)  # White

    palette = _pack_bgr555_palette(palette_colors)

    return bytes(tile_data), bytes(tilemap), palette


def generate_grid_tileset() -> tuple[bytes, bytes, bytes]:
    """Generate a grid tileset for visual Mode 7 testing.

    Returns (tile_data, tilemap, palette):
      - 4 tiles with distinct solid colors for four quadrants
      - 128x128 tilemap with a visible grid pattern (quadrant coloring)
      - 256-color palette with distinct colors per quadrant

    Tile layout:
      Tile 0: solid color 1 (red)    - top-left quadrant
      Tile 1: solid color 2 (green)  - top-right quadrant
      Tile 2: solid color 3 (blue)   - bottom-left quadrant
      Tile 3: solid color 4 (yellow) - bottom-right quadrant
    """
    # --- Tile data: 256 tiles x 64 bytes ---
    tile_data = bytearray(MODE7_TILEDATA_SIZE)

    # Tile 0: all pixels = color 1 (red)
    for i in range(MODE7_TILE_BYTES):
        tile_data[0 * MODE7_TILE_BYTES + i] = 1

    # Tile 1: all pixels = color 2 (green)
    for i in range(MODE7_TILE_BYTES):
        tile_data[1 * MODE7_TILE_BYTES + i] = 2

    # Tile 2: all pixels = color 3 (blue)
    for i in range(MODE7_TILE_BYTES):
        tile_data[2 * MODE7_TILE_BYTES + i] = 3

    # Tile 3: all pixels = color 4 (yellow)
    for i in range(MODE7_TILE_BYTES):
        tile_data[3 * MODE7_TILE_BYTES + i] = 4

    # --- Tilemap: 128x128, four quadrants ---
    tilemap = bytearray(MODE7_TILEMAP_SIZE)
    half_w = MODE7_TILEMAP_WIDTH // 2   # 64
    half_h = MODE7_TILEMAP_HEIGHT // 2  # 64

    for row in range(MODE7_TILEMAP_HEIGHT):
        for col in range(MODE7_TILEMAP_WIDTH):
            idx = row * MODE7_TILEMAP_WIDTH + col
            if row < half_h:
                tilemap[idx] = 0 if col < half_w else 1  # Top: red / green
            else:
                tilemap[idx] = 2 if col < half_w else 3  # Bottom: blue / yellow

    # --- Palette: 256 colors ---
    palette_colors = [(0, 0, 0)] * MODE7_PALETTE_COLORS
    palette_colors[0] = (0, 0, 0)        # Black (background/transparent)
    palette_colors[1] = (255, 0, 0)      # Red
    palette_colors[2] = (0, 255, 0)      # Green
    palette_colors[3] = (0, 0, 255)      # Blue
    palette_colors[4] = (255, 255, 0)    # Yellow

    palette = _pack_bgr555_palette(palette_colors)

    return bytes(tile_data), bytes(tilemap), palette



# ---------------------------------------------------------------------------
# Full Pipeline: image files -> interleaved binary
# ---------------------------------------------------------------------------

def convert_mode7_full(
    tileset_path: str,
    tilemap_data,
    palette_path: Optional[str] = None,
) -> tuple[bytes, bytes]:
    """Run the full Mode 7 asset pipeline: validate, convert, interleave.

    Args:
        tileset_path: Path to the tileset PNG.
        tilemap_data: 2D or flat list of tile indices (128x128).
        palette_path: Optional separate palette PNG. If None, extracted
                      from the tileset image.

    Returns:
        (interleaved_vram, palette) where:
          interleaved_vram: 32,768 bytes for DMA to Mode 7 VRAM.
          palette: 512 bytes for CGRAM.

    Raises:
        ValueError: If any validation check fails.
    """
    # Validate first
    errors = validate_mode7_assets(tileset_path, tilemap_data, palette_path)
    if errors:
        raise ValueError(
            "Mode 7 asset validation failed:\n  " + "\n  ".join(errors)
        )

    # Convert tileset
    tile_data = convert_mode7_tileset(tileset_path)

    # Convert tilemap
    tilemap = convert_mode7_tilemap(tilemap_data)

    # Extract palette
    pal_source = palette_path if palette_path else tileset_path
    palette = extract_mode7_palette(pal_source)

    # Interleave
    interleaved = interleave_mode7_data(tilemap, tile_data)

    logger.info(
        f"[MODE7] Full pipeline complete: {len(interleaved)} bytes VRAM + "
        f"{len(palette)} bytes palette"
    )

    return interleaved, palette


# ---------------------------------------------------------------------------
# Assembly data emission
# ---------------------------------------------------------------------------

def mode7_data_to_asm(
    interleaved: bytes,
    palette: bytes,
    tileset_label: str = "mode7_vram_data",
    palette_label: str = "mode7_palette_data",
) -> str:
    """Convert Mode 7 binary data to ca65-compatible .byte directives.

    Args:
        interleaved: 32,768 bytes of interleaved VRAM data.
        palette: 512 bytes of BGR555 palette data.
        tileset_label: Assembly label for the VRAM data.
        palette_label: Assembly label for the palette data.

    Returns:
        String containing ca65-compatible assembly source.
    """
    lines = []
    lines.append(f"; Mode 7 VRAM data — {len(interleaved)} bytes (interleaved)")
    lines.append(f"; Generated by toolchain/mode7_assets.py")
    lines.append(f"")
    lines.append(f"{tileset_label}:")

    for i in range(0, len(interleaved), 16):
        chunk = interleaved[i:i + 16]
        hex_bytes = ", ".join(f"${b:02X}" for b in chunk)
        lines.append(f"    .byte {hex_bytes}")

    lines.append(f"{tileset_label}_end:")
    lines.append(f"")
    lines.append(f"; Mode 7 palette — {len(palette)} bytes (BGR555)")
    lines.append(f"{palette_label}:")

    for i in range(0, len(palette), 16):
        chunk = palette[i:i + 16]
        hex_bytes = ", ".join(f"${b:02X}" for b in chunk)
        lines.append(f"    .byte {hex_bytes}")

    lines.append(f"{palette_label}_end:")
    lines.append(f"")

    return "\n".join(lines)
