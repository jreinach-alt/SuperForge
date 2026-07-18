"""
Phase 8E: Mode 7 Asset Pipeline CLI

Command-line interface for converting Mode 7 assets. Can be called
from the build pipeline or used standalone.

Usage:
    # Convert a tileset + tilemap + palette into interleaved binary
    python -m toolchain.mode7_assets_cli \\
        --tileset input.png \\
        --tilemap map.csv \\
        --output build/mode7_vram.bin

    # Convert with a separate palette image
    python -m toolchain.mode7_assets_cli \\
        --tileset input.png \\
        --tilemap map.csv \\
        --palette palette.png \\
        --output build/mode7_vram.bin

    # Generate test assets (checkerboard + grid)
    python -m toolchain.mode7_assets_cli \\
        --generate-test-assets \\
        --output-dir build/

    # Validate assets without converting
    python -m toolchain.mode7_assets_cli \\
        --validate \\
        --tileset input.png \\
        --tilemap map.csv

    # Convert and emit ca65 assembly .inc files
    python -m toolchain.mode7_assets_cli \\
        --tileset input.png \\
        --tilemap map.csv \\
        --output-asm build/mode7_data.inc
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from toolchain.mode7_assets import (
    convert_mode7_tileset,
    convert_mode7_tilemap,
    extract_mode7_palette,
    interleave_mode7_data,
    validate_mode7_assets,
    generate_checkerboard_tileset,
    generate_grid_tileset,
    mode7_data_to_asm,
    MODE7_TILEMAP_WIDTH,
    MODE7_TILEMAP_HEIGHT,
    MODE7_TILEMAP_SIZE,
    MODE7_TILEDATA_SIZE,
    MODE7_INTERLEAVED_SIZE,
    MODE7_PALETTE_SIZE,
)


def load_tilemap_csv(csv_path: str) -> list[int]:
    """Load a tilemap from a CSV file.

    The CSV should contain 128 rows of 128 comma-separated tile indices.
    Values are integers 0-255.

    Args:
        csv_path: Path to the CSV file.

    Returns:
        Flat list of 16,384 tile indices.

    Raises:
        ValueError: If the CSV dimensions or values are wrong.
    """
    flat = []
    path = Path(csv_path)

    with open(path, 'r', newline='') as f:
        reader = csv.reader(f)
        row_count = 0
        for row in reader:
            # Skip empty rows and comment rows
            if not row or (row[0].strip().startswith('#')):
                continue
            values = [int(v.strip()) for v in row if v.strip()]
            if len(values) != MODE7_TILEMAP_WIDTH:
                raise ValueError(
                    f"{path.name}: row {row_count} has {len(values)} values, "
                    f"expected {MODE7_TILEMAP_WIDTH}"
                )
            flat.extend(values)
            row_count += 1

    if row_count != MODE7_TILEMAP_HEIGHT:
        raise ValueError(
            f"{path.name}: has {row_count} data rows, "
            f"expected {MODE7_TILEMAP_HEIGHT}"
        )

    return flat


def load_tilemap_json(json_path: str) -> list[int]:
    """Load a tilemap from a JSON file.

    The JSON should contain a 2D array (list of lists) of tile indices,
    or a flat list of 16,384 values.

    Args:
        json_path: Path to the JSON file.

    Returns:
        Flat list of 16,384 tile indices.
    """
    with open(json_path, 'r') as f:
        data = json.load(f)

    if isinstance(data, list) and data and isinstance(data[0], list):
        # 2D array
        flat = []
        for row in data:
            flat.extend(row)
        return flat
    elif isinstance(data, list):
        # Already flat
        return data
    else:
        raise ValueError(f"Unexpected JSON format in {json_path}")


def load_tilemap(path: str) -> list[int]:
    """Load a tilemap from a file, auto-detecting format by extension.

    Supports .csv and .json formats.

    Args:
        path: Path to the tilemap file.

    Returns:
        Flat list of 16,384 tile indices.
    """
    ext = Path(path).suffix.lower()
    if ext == '.csv':
        return load_tilemap_csv(path)
    elif ext == '.json':
        return load_tilemap_json(path)
    else:
        raise ValueError(
            f"Unsupported tilemap format '{ext}'. Use .csv or .json."
        )


def cmd_convert(args: argparse.Namespace) -> int:
    """Convert tileset + tilemap + palette into interleaved binary."""
    tileset_path = args.tileset
    tilemap_path = args.tilemap
    palette_path = args.palette
    output_path = args.output

    # Load tilemap
    tilemap_flat = load_tilemap(tilemap_path)

    # Convert tileset
    print(f"Converting tileset: {tileset_path}")
    tile_data = convert_mode7_tileset(tileset_path)

    # Convert tilemap
    print(f"Converting tilemap: {tilemap_path}")
    tilemap = convert_mode7_tilemap(tilemap_flat)

    # Extract palette
    pal_source = palette_path if palette_path else tileset_path
    print(f"Extracting palette from: {pal_source}")
    palette = extract_mode7_palette(pal_source)

    # Interleave
    print("Interleaving VRAM data...")
    interleaved = interleave_mode7_data(tilemap, tile_data)

    # Write output
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    vram_path = output_path
    pal_path = str(Path(output_path).with_suffix('.pal.bin'))

    with open(vram_path, 'wb') as f:
        f.write(interleaved)
    print(f"Wrote VRAM data: {vram_path} ({len(interleaved)} bytes)")

    with open(pal_path, 'wb') as f:
        f.write(palette)
    print(f"Wrote palette: {pal_path} ({len(palette)} bytes)")

    # Write assembly include if requested
    if args.output_asm:
        asm_content = mode7_data_to_asm(interleaved, palette)
        with open(args.output_asm, 'w') as f:
            f.write(asm_content)
        print(f"Wrote assembly include: {args.output_asm}")

    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate assets without converting."""
    tilemap_flat = load_tilemap(args.tilemap)
    errors = validate_mode7_assets(args.tileset, tilemap_flat, args.palette)

    if errors:
        print("Validation FAILED:")
        for err in errors:
            print(f"  - {err}")
        return 1
    else:
        print("Validation PASSED: all Mode 7 asset constraints satisfied.")
        return 0


def cmd_generate_test_assets(args: argparse.Namespace) -> int:
    """Generate test assets (checkerboard + grid)."""
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Checkerboard
    print("Generating checkerboard test assets...")
    cb_tiles, cb_map, cb_pal = generate_checkerboard_tileset()
    cb_interleaved = interleave_mode7_data(cb_map, cb_tiles)

    cb_vram_path = output_dir / "mode7_checkerboard.bin"
    cb_pal_path = output_dir / "mode7_checkerboard.pal.bin"
    cb_asm_path = output_dir / "mode7_checkerboard.inc"

    with open(cb_vram_path, 'wb') as f:
        f.write(cb_interleaved)
    with open(cb_pal_path, 'wb') as f:
        f.write(cb_pal)

    asm_content = mode7_data_to_asm(
        cb_interleaved, cb_pal,
        tileset_label="mode7_checkerboard_vram",
        palette_label="mode7_checkerboard_palette",
    )
    with open(cb_asm_path, 'w') as f:
        f.write(asm_content)

    print(f"  VRAM:    {cb_vram_path} ({len(cb_interleaved)} bytes)")
    print(f"  Palette: {cb_pal_path} ({len(cb_pal)} bytes)")
    print(f"  ASM:     {cb_asm_path}")

    # Grid
    print("Generating grid test assets...")
    gr_tiles, gr_map, gr_pal = generate_grid_tileset()
    gr_interleaved = interleave_mode7_data(gr_map, gr_tiles)

    gr_vram_path = output_dir / "mode7_grid.bin"
    gr_pal_path = output_dir / "mode7_grid.pal.bin"
    gr_asm_path = output_dir / "mode7_grid.inc"

    with open(gr_vram_path, 'wb') as f:
        f.write(gr_interleaved)
    with open(gr_pal_path, 'wb') as f:
        f.write(gr_pal)

    asm_content = mode7_data_to_asm(
        gr_interleaved, gr_pal,
        tileset_label="mode7_grid_vram",
        palette_label="mode7_grid_palette",
    )
    with open(gr_asm_path, 'w') as f:
        f.write(asm_content)

    print(f"  VRAM:    {gr_vram_path} ({len(gr_interleaved)} bytes)")
    print(f"  Palette: {gr_pal_path} ({len(gr_pal)} bytes)")
    print(f"  ASM:     {gr_asm_path}")

    print("Test asset generation complete.")
    return 0


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="mode7_assets_cli",
        description="SuperForge Mode 7 Asset Pipeline — convert and validate Mode 7 graphics",
    )

    # Mode flags (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--convert",
        action="store_true",
        help="Convert tileset + tilemap to interleaved VRAM binary",
    )
    mode_group.add_argument(
        "--validate",
        action="store_true",
        help="Validate assets without converting",
    )
    mode_group.add_argument(
        "--generate-test-assets",
        action="store_true",
        help="Generate checkerboard and grid test assets",
    )

    # Input files
    parser.add_argument(
        "--tileset",
        help="Path to tileset PNG image (16 tiles wide, 8x8 tiles)",
    )
    parser.add_argument(
        "--tilemap",
        help="Path to tilemap file (.csv or .json, 128x128 entries)",
    )
    parser.add_argument(
        "--palette",
        help="Path to separate palette PNG (optional, defaults to tileset)",
    )

    # Output paths
    parser.add_argument(
        "--output", "-o",
        help="Output path for interleaved VRAM binary (.bin)",
    )
    parser.add_argument(
        "--output-asm",
        help="Output path for ca65 assembly .inc file",
    )
    parser.add_argument(
        "--output-dir",
        default="build/",
        help="Output directory for generated test assets (default: build/)",
    )

    args = parser.parse_args()

    # Validate required arguments for each mode
    if args.convert:
        if not args.tileset or not args.tilemap:
            parser.error("--convert requires --tileset and --tilemap")
        if not args.output:
            parser.error("--convert requires --output")
        return cmd_convert(args)

    elif args.validate:
        if not args.tileset or not args.tilemap:
            parser.error("--validate requires --tileset and --tilemap")
        return cmd_validate(args)

    elif args.generate_test_assets:
        return cmd_generate_test_assets(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
