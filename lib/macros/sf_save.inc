; =============================================================================
; sf_save.inc — battery-SRAM save/load macros (macro library)
; =============================================================================
; The front door over the engine's save/load engine: battery-backed game
; saves with integrity checking, 4 slots of 2KB each at $70:0000-$70:1FFF.
;
;   sf_save        slot, src, len, ver   — save a WRAM block to a slot
;   sf_load        slot, dest        -> A — load a slot back to WRAM
;   sf_save_exists slot              -> A — is there a valid save? (1/0)
;   sf_save_clear  slot                  — invalidate a slot
;
; Per-slot format (2048 bytes, written by the engine):
;   +$000  2 bytes magic "SF"
;   +$002  1 byte  version (yours — bump it when your save layout changes)
;   +$003  1 byte  reserved
;   +$004  2 bytes data length (0-2040)
;   +$006  2 bytes CRC-16 (CCITT, poly $1021, over header + payload)
;   +$008  payload (up to 2040 bytes)
;
; CORRUPTION / REJECTION SEMANTICS (what the return codes mean):
;   sf_load verifies the magic AND the CRC-16 BEFORE copying a single byte
;   to WRAM. A slot whose bytes were altered after the save (bit rot, a
;   dying battery, a partial write) fails the CRC and the load REJECTS:
;     A = data length (1-2040)  -> success, payload copied to dest
;     A = $FFFF                 -> no save (magic missing) — dest untouched
;     A = $FFFE                 -> corrupt (CRC mismatch)  — dest untouched
;   sf_save_exists runs the same magic+CRC check without copying: a corrupt
;   or cleared slot answers 0. Always gate on these codes — never branch on
;   raw SRAM bytes (see the battery caveat below).
;
;   SETUP CONTRACT: link the ROM with infrastructure/rom_template/
;   lorom_sram.cfg — the kit cfg that maps the $70:0000-$70:1FFF SRAM
;   window (the stock header.inc already declares cartridge type ROM+SRAM
;   and the 8KB SRAM size; the cfg header documents why no header variant
;   is needed). Include engine/save_load_engine.asm anywhere in the CODE
;   segment. The engine is self-contained: no NMI dependency, no engine
;   init, no tick — its only RAM footprint is the reserved WRAM scratch
;   $0590-$059F (SL_*) plus the 512-byte CRC table in ROM. Slots hold 2040
;   payload bytes; a save bigger than that must be split across slots.
;
; BATTERY-EMULATION CAVEAT (how persistence actually behaves under Mesen):
;   The emulator sizes SRAM from the ROM header and persists it to
;   <mesen-home>/Saves/<rom>.srm when the ROM is UNLOADED (next load_rom /
;   stop) — not on every SRAM write. Inside a run, read the live SRAM
;   (MesenRunner MemoryType.SnesSaveRam), not the .srm file. And note that
;   virgin SRAM (no .srm on disk) is power-on GARBAGE, not zeros — exactly
;   like a real cart's first power-up. That is why the magic+CRC gate
;   exists: sf_save_exists / the sf_load return code are the ONLY valid
;   "is there a save?" tests.
;   Test-side pattern: tests/_srm.py carries the shared .srm hygiene
;   helpers (flush_srm / virgin_srm — the neutral-ROM-first ordering that
;   defeats the unload-flush resurrection trap). They need a built neutral
;   ROM (`make testroms`; text_test.sfc is the convention).
;
; WIDTH-RISK: every macro here forces A16/I16 on entry (rep #$30) — the
; engine entries are .a16/.i16 by contract and toggle A-width internally,
; exiting A16/I16. Call from any width; the macro owns the contract.
; All four clobber A, X, Y.
; =============================================================================

.ifndef SF_SAVE_INC
SF_SAVE_INC = 1

SF_SAVE_SLOT_SIZE = $0800       ; 2KB per slot (engine SRAM_SLOT_SIZE)
SF_SAVE_MAX_DATA  = 2040        ; 2048 - 8-byte header (engine SRAM_MAX_DATA)

; -----------------------------------------------------------------------------
; sf_save slot, src, len, ver — save a WRAM block to an SRAM slot.
; -----------------------------------------------------------------------------
;   slot  0-3       (assemble-time constant — bounds .assert-ed)
;   src   WRAM source address, bank $7E (verbatim 16-bit operand —
;         `#$1800` or a memory operand holding the address)
;   len   payload bytes, 0-2040 (assemble-time constant — .assert-ed; the
;         slot is 2048 bytes minus the 8-byte header)
;   ver   save-format version byte, 0-255 (assemble-time constant) —
;         stored in the slot header for YOUR migration logic; the engine
;         does not interpret it
; Writes header + payload + CRC-16 to the slot. Returns A = 0.
; Clobbers A, X, Y.
; WIDTH-RISK: forces A16/I16 entry; engine_save exits A16/I16.
.macro sf_save sf_slot, sf_src, sf_len, sf_ver
    .assert (sf_slot) >= 0 && (sf_slot) <= 3, error, "sf_save: slot must be 0-3"
    .assert (sf_len) >= 0 && (sf_len) <= SF_SAVE_MAX_DATA, error, "sf_save: len must be 0-2040 (2KB slot minus 8-byte header)"
    .assert (sf_ver) >= 0 && (sf_ver) <= 255, error, "sf_save: ver must be 0-255"
    rep #$30
    .a16
    .i16
    lda #((sf_slot) * SF_SAVE_SLOT_SIZE)
    sta SL_SLOT_BASE
    lda sf_src
    sta SL_SRC_ADDR
    lda #(sf_len)
    sta SL_LENGTH
    lda #(sf_ver)
    sta SL_VERSION
    jsr engine_save
.endmacro

; -----------------------------------------------------------------------------
; sf_load slot, dest -> A — load a slot's payload back into WRAM.
; -----------------------------------------------------------------------------
;   slot  0-3       (assemble-time constant — bounds .assert-ed)
;   dest  WRAM destination address, bank $7E (verbatim 16-bit operand)
; Verifies magic + CRC-16 FIRST; only a valid slot is copied.
; Returns A = length (success) / $FFFF (no save) / $FFFE (corrupt) —
; on $FFFF/$FFFE the destination is untouched. Clobbers A, X, Y.
; Idiom:  sf_load 0, #$1800  /  cmp #$FFFE  /  beq corrupt  /
;         cmp #$FFFF  /  beq no_save
; WIDTH-RISK: forces A16/I16 entry; engine_load exits A16/I16.
.macro sf_load sf_slot, sf_dest
    .assert (sf_slot) >= 0 && (sf_slot) <= 3, error, "sf_load: slot must be 0-3"
    rep #$30
    .a16
    .i16
    lda #((sf_slot) * SF_SAVE_SLOT_SIZE)
    sta SL_SLOT_BASE
    lda sf_dest
    sta SL_SRC_ADDR
    jsr engine_load
.endmacro

; -----------------------------------------------------------------------------
; sf_save_exists slot -> A — does the slot hold a VALID save? (magic + CRC)
; -----------------------------------------------------------------------------
;   slot  0-3       (assemble-time constant — bounds .assert-ed)
; Returns A = 1 (valid save) / 0 (empty, cleared, or corrupt). No copy.
; Clobbers A, X, Y. Idiom:  sf_save_exists 0  /  bne has_save
; WIDTH-RISK: forces A16/I16 entry; engine_save_exists exits A16/I16.
.macro sf_save_exists sf_slot
    .assert (sf_slot) >= 0 && (sf_slot) <= 3, error, "sf_save_exists: slot must be 0-3"
    rep #$30
    .a16
    .i16
    lda #((sf_slot) * SF_SAVE_SLOT_SIZE)
    sta SL_SLOT_BASE
    jsr engine_save_exists
.endmacro

; -----------------------------------------------------------------------------
; sf_save_clear slot — invalidate a slot (zero its magic bytes).
; -----------------------------------------------------------------------------
;   slot  0-3       (assemble-time constant — bounds .assert-ed)
; After this, sf_save_exists answers 0 and sf_load answers $FFFF. The
; payload bytes are NOT wiped — clear is an invalidation, not an erase.
; Returns A = 0. Clobbers A, X, Y.
; WIDTH-RISK: forces A16/I16 entry; engine_save_clear exits A16/I16.
.macro sf_save_clear sf_slot
    .assert (sf_slot) >= 0 && (sf_slot) <= 3, error, "sf_save_clear: slot must be 0-3"
    rep #$30
    .a16
    .i16
    lda #((sf_slot) * SF_SAVE_SLOT_SIZE)
    sta SL_SLOT_BASE
    jsr engine_save_clear
.endmacro

.endif ; SF_SAVE_INC
