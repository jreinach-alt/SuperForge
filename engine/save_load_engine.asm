; =============================================================================
; save_load_engine.asm — Save/Load Engine (SRAM)
; =============================================================================
; Provides battery-backed save/load to SRAM with CRC-16 integrity checking.
;
; SRAM layout (8KB at $70:0000 - $70:1FFF):
;   Slot 0: $70:0000 - $70:07FF (2048 bytes)
;   Slot 1: $70:0800 - $70:0FFF (2048 bytes)
;   Slot 2: $70:1000 - $70:17FF (2048 bytes)
;   Slot 3: $70:1800 - $70:1FFF (2048 bytes)
;
; Per-slot format (2048 bytes):
;   $000: 2 bytes magic "SF" ($53, $46)
;   $002: 1 byte version
;   $003: 1 byte reserved ($00)
;   $004: 2 bytes data length (0-2040)
;   $006: 2 bytes CRC-16 checksum (CCITT, poly $1021)
;   $008: 2040 bytes data payload
;
; CRC-16 (CRC-CCITT) with 256-entry lookup table (512 bytes in ROM).
;
; Must NOT have .p816/.smart (included into parent).
; Prerequisites: engine_state.inc included, .p816/.smart set by parent.
;
; Cross-ref: engine_state.inc, lib/macros/sf_save.inc (the kit front door)
; =============================================================================

; === Constants ===
SRAM_BASE        = $700000   ; 24-bit address for long addressing
SRAM_SLOT_SIZE   = $0800     ; 2048 bytes per slot
SRAM_MAGIC_LO    = $53       ; 'S'
SRAM_MAGIC_HI    = $46       ; 'F'
SRAM_HEADER_SIZE = 8         ; magic(2) + version(1) + reserved(1) + length(2) + crc(2)
SRAM_MAX_DATA    = 2040      ; 2048 - 8

; === Scratch addresses (WRAM $0590-$059F) — RESERVED ===
;
; This 16-byte range is reserved exclusively for the save/load engine's
; SL_* scratch (8 two-byte equates fill it exactly). The engine WRAM map
; was collision-audited when this range was consolidated: the neighbouring
; allocations are the HDMA wave / tilemap-dims scratch ($0580-$058D) below
; and the iris Bresenham table ($05A0+) above; the kit's macro scratch
; tops out at $053F and the game-array region starts at $1800.
;
; DO NOT REUSE $0590-$059F for any other subsystem. New low-WRAM scratch
; should claim from the still-free regions documented in
; engine/engine_state.inc.
SL_SLOT_BASE     = $0590     ; 2 bytes: computed SRAM slot offset (low 16 bits)
SL_SRC_ADDR      = $0592     ; 2 bytes: WRAM source/dest address (bank $7E)
SL_LENGTH        = $0594     ; 2 bytes: data length
SL_VERSION       = $0596     ; 2 bytes: version byte (low byte used)
SL_CRC_START     = $0598     ; 2 bytes: CRC computation start offset in SRAM
SL_CRC_LEN       = $059A     ; 2 bytes: CRC computation length
SL_CRC_ACCUM     = $059C     ; 2 bytes: CRC accumulator
SL_TEMP          = $059E     ; 2 bytes: temporary


; =============================================================================
; engine_save — Save data to SRAM slot
; =============================================================================
; Input (set up by the sf_save macro layer before call):
;   SL_SLOT_BASE = SRAM slot offset ($0000, $0800, $1000, $1800)
;   SL_SRC_ADDR  = WRAM source address (bank $7E)
;   SL_LENGTH    = data length (0-2040, already validated by the caller)
;   SL_VERSION   = save format version (low byte)
;
; Returns: A = 0 (success)
; Clobbers: A, X, Y
; =============================================================================
engine_save:
    .a16
    .i16

    ; --- Write header to SRAM ---
    ldx SL_SLOT_BASE

    ; Magic "SF" at offset $000-$001
    sep #$20
    .a8
    lda #SRAM_MAGIC_LO              ; $53 = 'S'
    sta f:SRAM_BASE,x
    lda #SRAM_MAGIC_HI              ; $46 = 'F'
    sta f:SRAM_BASE+1,x

    ; Version at $002
    lda SL_VERSION
    sta f:SRAM_BASE+2,x

    ; Reserved at $003
    lda #$00
    sta f:SRAM_BASE+3,x

    rep #$20
    .a16

    ; Data length at $004-$005
    lda SL_LENGTH
    sta f:SRAM_BASE+4,x

    ; Zero CRC field at $006-$007 (will be computed after data copy)
    lda #$0000
    sta f:SRAM_BASE+6,x

    ; --- Copy data from WRAM to SRAM ---
    lda SL_LENGTH
    beq @save_do_crc                ; skip copy if length = 0

    ldy #$0000                      ; Y = byte index
@save_copy:
    ; Compute WRAM source address: SL_SRC_ADDR + Y
    tya
    clc
    adc SL_SRC_ADDR
    tax

    sep #$20
    .a8
    lda f:$7E0000,x                 ; read byte from WRAM

    ; Compute SRAM dest offset: SL_SLOT_BASE + SRAM_HEADER_SIZE + Y
    rep #$20
    .a16
    pha                             ; save byte (pushed as 16-bit, low byte is our data)
    tya
    clc
    adc SL_SLOT_BASE
    clc
    adc #SRAM_HEADER_SIZE
    tax
    pla                             ; restore byte (16-bit pop, low byte is data)

    sep #$20
    .a8
    sta f:SRAM_BASE,x               ; write byte to SRAM

    rep #$20
    .a16
    iny
    cpy SL_LENGTH
    bne @save_copy

@save_do_crc:
    ; --- Compute CRC-16 over header + data (with CRC field = $0000) ---
    lda SL_SLOT_BASE
    sta SL_CRC_START
    lda SL_LENGTH
    clc
    adc #SRAM_HEADER_SIZE
    sta SL_CRC_LEN

    jsr crc16_compute_sram          ; A = CRC-16

    ; Write CRC to SRAM at $006
    ldx SL_SLOT_BASE
    sta f:SRAM_BASE+6,x

    ; Return success
    lda #$0000
    rts


; =============================================================================
; engine_load — Load data from SRAM slot to WRAM
; =============================================================================
; Input (set up by the sf_save macro layer before call):
;   SL_SLOT_BASE = SRAM slot offset
;   SL_SRC_ADDR  = WRAM destination address (bank $7E)
;
; Returns: A = data length (>0 = success), $FFFF (no save), $FFFE (corrupt)
; Clobbers: A, X, Y
; =============================================================================
engine_load:
    .a16
    .i16
    ldx SL_SLOT_BASE

    ; --- Check magic bytes ---
    sep #$20
    .a8
    lda f:SRAM_BASE,x
    cmp #SRAM_MAGIC_LO
    bne @load_no_save
    lda f:SRAM_BASE+1,x
    cmp #SRAM_MAGIC_HI
    bne @load_no_save
    rep #$20
    .a16

    ; --- Read data length ---
    lda f:SRAM_BASE+4,x
    sta SL_LENGTH

    ; --- Read stored CRC ---
    lda f:SRAM_BASE+6,x
    pha                             ; push stored CRC (SL_TEMP clobbered by CRC routine)

    ; --- Zero CRC field temporarily for verification ---
    lda #$0000
    sta f:SRAM_BASE+6,x

    ; --- Compute CRC ---
    lda SL_SLOT_BASE
    sta SL_CRC_START
    lda SL_LENGTH
    clc
    adc #SRAM_HEADER_SIZE
    sta SL_CRC_LEN

    jsr crc16_compute_sram          ; A = computed CRC
    sta SL_TEMP                     ; save computed CRC (now safe, CRC routine done)

    ; --- Restore stored CRC to SRAM ---
    ldx SL_SLOT_BASE
    pla                             ; A = stored CRC (from stack)
    sta f:SRAM_BASE+6,x            ; restore SRAM

    ; --- Compare CRCs ---
    cmp SL_TEMP                     ; stored CRC vs computed CRC
    bne @load_corrupt

    ; --- Copy data from SRAM to WRAM ---
    lda SL_LENGTH
    beq @load_done                  ; skip copy if length = 0

    ldy #$0000                      ; Y = byte index
@load_copy:
    ; Compute SRAM source offset: SL_SLOT_BASE + SRAM_HEADER_SIZE + Y
    tya
    clc
    adc SL_SLOT_BASE
    clc
    adc #SRAM_HEADER_SIZE
    tax

    sep #$20
    .a8
    lda f:SRAM_BASE,x               ; read byte from SRAM

    rep #$20
    .a16
    pha                             ; save byte

    ; Compute WRAM dest address: SL_SRC_ADDR + Y
    tya
    clc
    adc SL_SRC_ADDR
    tax

    pla                             ; restore byte
    sep #$20
    .a8
    sta f:$7E0000,x                 ; write byte to WRAM

    rep #$20
    .a16
    iny
    cpy SL_LENGTH
    bne @load_copy

@load_done:
    lda SL_LENGTH
    rts

@load_no_save:
    rep #$20
    .a16
    lda #$FFFF
    rts

@load_corrupt:
    lda #$FFFE
    rts


; =============================================================================
; engine_save_exists — Check if SRAM slot has a valid save
; =============================================================================
; Input: SL_SLOT_BASE = SRAM slot offset
; Returns: A = 1 (valid save), 0 (no save or corrupt)
; Clobbers: A, X, Y
; =============================================================================
engine_save_exists:
    .a16
    .i16
    ldx SL_SLOT_BASE

    ; --- Check magic bytes ---
    sep #$20
    .a8
    lda f:SRAM_BASE,x
    cmp #SRAM_MAGIC_LO
    bne @exists_none
    lda f:SRAM_BASE+1,x
    cmp #SRAM_MAGIC_HI
    bne @exists_none
    rep #$20
    .a16

    ; --- Read stored CRC and data length ---
    lda f:SRAM_BASE+6,x
    pha                             ; push stored CRC (SL_TEMP clobbered by CRC routine)
    lda f:SRAM_BASE+4,x
    sta SL_LENGTH

    ; --- Zero CRC field temporarily ---
    lda #$0000
    sta f:SRAM_BASE+6,x

    ; --- Compute CRC ---
    lda SL_SLOT_BASE
    sta SL_CRC_START
    lda SL_LENGTH
    clc
    adc #SRAM_HEADER_SIZE
    sta SL_CRC_LEN

    jsr crc16_compute_sram          ; A = computed CRC
    sta SL_TEMP                     ; save computed CRC (safe now, CRC routine done)

    ; --- Restore stored CRC ---
    ldx SL_SLOT_BASE
    pla                             ; A = stored CRC (from stack)
    sta f:SRAM_BASE+6,x

    ; --- Compare ---
    cmp SL_TEMP                     ; stored CRC vs computed CRC
    bne @exists_invalid

    lda #$0001
    rts

@exists_none:
    rep #$20
    .a16
@exists_invalid:
    lda #$0000
    rts


; =============================================================================
; engine_save_clear — Clear save slot (invalidate magic bytes)
; =============================================================================
; Input: SL_SLOT_BASE = SRAM slot offset
; Returns: A = 0
; =============================================================================
engine_save_clear:
    .a16
    .i16
    ldx SL_SLOT_BASE

    ; Write $00 to first two bytes (invalidate magic)
    sep #$20
    .a8
    lda #$00
    sta f:SRAM_BASE,x
    sta f:SRAM_BASE+1,x
    rep #$20
    .a16

    lda #$0000
    rts


; =============================================================================
; crc16_compute_sram — Compute CRC-16 CCITT over SRAM data
; =============================================================================
; Input:
;   SL_CRC_START = start offset within SRAM
;   SL_CRC_LEN   = number of bytes to process
;
; Output: A = CRC-16 value
; Clobbers: A, X, Y
;
; Algorithm:
;   CRC = $FFFF
;   for each byte:
;     index = (CRC >> 8) ^ byte
;     CRC = (CRC << 8) ^ crc_table[index]
; =============================================================================
crc16_compute_sram:
    .a16
    .i16

    lda #$FFFF
    sta SL_CRC_ACCUM

    ldy #$0000                      ; Y = byte counter

@crc_loop:
    cpy SL_CRC_LEN
    beq @crc_done

    ; Read byte from SRAM at (SL_CRC_START + Y)
    tya
    clc
    adc SL_CRC_START
    tax

    sep #$20
    .a8
    lda f:SRAM_BASE,x               ; read byte
    rep #$20
    .a16
    and #$00FF                      ; zero-extend to 16-bit

    ; index = (CRC >> 8) ^ byte
    sta SL_TEMP                     ; save byte
    lda SL_CRC_ACCUM
    xba                             ; A high byte -> low byte
    and #$00FF                      ; isolate (CRC >> 8) in low byte
    eor SL_TEMP                     ; ^ byte
    asl                             ; * 2 for word table lookup
    tax

    ; new_crc = (CRC << 8) ^ crc_table[index]
    lda f:crc16_table,x             ; table value
    sta SL_TEMP                     ; save table value
    lda SL_CRC_ACCUM
    xba                             ; CRC << 8 (swap high/low bytes)
    and #$FF00                      ; mask: keep shifted high byte, clear low
    eor SL_TEMP                     ; ^ table value
    sta SL_CRC_ACCUM

    iny
    bra @crc_loop

@crc_done:
    lda SL_CRC_ACCUM
    rts


; =============================================================================
; CRC-16 CCITT Lookup Table
; =============================================================================
; Polynomial: $1021, 256 entries x 2 bytes = 512 bytes
; Standard CRC-CCITT (XModem): init=$FFFF, poly=$1021, no bit reflection
; =============================================================================
crc16_table:
    .word $0000, $1021, $2042, $3063, $4084, $50A5, $60C6, $70E7
    .word $8108, $9129, $A14A, $B16B, $C18C, $D1AD, $E1CE, $F1EF
    .word $1231, $0210, $3273, $2252, $52B5, $4294, $72F7, $62D6
    .word $9339, $8318, $B37B, $A35A, $D3BD, $C39C, $F3FF, $E3DE
    .word $2462, $3443, $0420, $1401, $64E6, $74C7, $44A4, $5485
    .word $A56A, $B54B, $8528, $9509, $E5EE, $F5CF, $C5AC, $D58D
    .word $3653, $2672, $1611, $0630, $76D7, $66F6, $5695, $46B4
    .word $B75B, $A77A, $9719, $8738, $F7DF, $E7FE, $D79D, $C7BC
    .word $48C4, $58E5, $6886, $78A7, $0840, $1861, $2802, $3823
    .word $C9CC, $D9ED, $E98E, $F9AF, $8948, $9969, $A90A, $B92B
    .word $5AF5, $4AD4, $7AB7, $6A96, $1A71, $0A50, $3A33, $2A12
    .word $DBFD, $CBDC, $FBBF, $EB9E, $9B79, $8B58, $BB3B, $AB1A
    .word $6CA6, $7C87, $4CE4, $5CC5, $2C22, $3C03, $0C60, $1C41
    .word $EDAE, $FD8F, $CDEC, $DDCD, $AD2A, $BD0B, $8D68, $9D49
    .word $7E97, $6EB6, $5ED5, $4EF4, $3E13, $2E32, $1E51, $0E70
    .word $FF9F, $EFBE, $DFDD, $CFFC, $BF1B, $AF3A, $9F59, $8F78
    .word $9188, $81A9, $B1CA, $A1EB, $D10C, $C12D, $F14E, $E16F
    .word $1080, $00A1, $30C2, $20E3, $5004, $4025, $7046, $6067
    .word $83B9, $9398, $A3FB, $B3DA, $C33D, $D31C, $E37F, $F35E
    .word $02B1, $1290, $22F3, $32D2, $4235, $5214, $6277, $7256
    .word $B5EA, $A5CB, $95A8, $8589, $F56E, $E54F, $D52C, $C50D
    .word $34E2, $24C3, $14A0, $0481, $7466, $6447, $5424, $4405
    .word $A7DB, $B7FA, $8799, $97B8, $E75F, $F77E, $C71D, $D73C
    .word $26D3, $36F2, $0691, $16B0, $6657, $7676, $4615, $5634
    .word $D94C, $C96D, $F90E, $E92F, $99C8, $89E9, $B98A, $A9AB
    .word $5844, $4865, $7806, $6827, $18C0, $08E1, $3882, $28A3
    .word $CB7D, $DB5C, $EB3F, $FB1E, $8BF9, $9BD8, $ABBB, $BB9A
    .word $4A75, $5A54, $6A37, $7A16, $0AF1, $1AD0, $2AB3, $3A92
    .word $FD2E, $ED0F, $DD6C, $CD4D, $BDAA, $AD8B, $9DE8, $8DC9
    .word $7C26, $6C07, $5C64, $4C45, $3CA2, $2C83, $1CE0, $0CC1
    .word $EF1F, $FF3E, $CF5D, $DF7C, $AF9B, $BFBA, $8FD9, $9FF8
    .word $6E17, $7E36, $4E55, $5E74, $2E93, $3EB2, $0ED1, $1EF0
