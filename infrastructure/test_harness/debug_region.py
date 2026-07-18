"""
debug_region.py — Python mirror of debug_region.inc constants.

Single source of truth (assembly side) is engine/debug_region.inc.
This file must be kept in sync manually.
"""

# Base address within WRAM (for MesenRunner offset)
DEBUG_BASE_WRAM = 0xE000

# Field offsets (relative to DEBUG_BASE_WRAM)
DBG_MAGIC           = 0x0000    # 4 bytes: "SFDB"
DBG_VERSION         = 0x0004    # 2 bytes: major, minor
DBG_FRAME_CTR_LO    = 0x0006    # 2 bytes: low word
DBG_FRAME_CTR_HI    = 0x0008    # 2 bytes: high word
DBG_ASSERT_PASS     = 0x000A    # 2 bytes
DBG_ASSERT_FAIL     = 0x000C    # 2 bytes
DBG_ASSERT_LAST_ID  = 0x000E    # 2 bytes
DBG_HALT_FLAG       = 0x0010    # 1 byte
DBG_BKPT_PC         = 0x0011    # 3 bytes
DBG_TRACE_INDEX     = 0x0014    # 2 bytes
DBG_TRACE_BUFFER    = 0x0018    # 512 bytes (256 x 2)
DBG_TIMING          = 0x0218    # 40 bytes (5 x 8)
DBG_REGSNAPSHOT     = 0x0240    # 16 bytes
DBG_RESERVED_START  = 0x0250    # Start of reserved/test-use area

# Magic bytes
MAGIC_BYTES = b"SFDB"
VERSION_MAJOR = 0x00
VERSION_MINOR = 0x01

# Trace buffer
TRACE_ENTRIES = 256
TRACE_ENTRY_SIZE = 2

# Timing phases
PHASE_UPDATE  = 0
PHASE_DRAW    = 1
PHASE_RESOLVE = 2
PHASE_VBLANK  = 3
PHASE_IDLE    = 4
TIMING_PHASES = 5
TIMING_ENTRY_SIZE = 8


def abs_addr(field_offset: int) -> int:
    """Return absolute WRAM address for a debug region field."""
    return DEBUG_BASE_WRAM + field_offset
