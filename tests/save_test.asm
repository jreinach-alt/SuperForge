; =============================================================================
; save_test — run-gate for the battery-SRAM save/load macros (sf_save.inc)
; =============================================================================
; Two-boot ROM: the FIRST boot drives the full save/corrupt/clear state
; cycle; a SECOND boot (a hard power-cycle — the harness re-loads the ROM
; fresh) proves battery persistence by loading the slot saved by boot one.
; The boot discriminator is sf_save_exists on slot 0: virgin SRAM has no
; valid save (magic + CRC gate), a power-cycled cart does.
;
; WRAM buffers (game-array region $1800-$1DFF):
;   $1800  64-byte source pattern, byte[i] = (3 + 7*i) & $FF  (both boots)
;   $1A00  boot-time load dest (run 2: the restored payload)
;   $1B00  first-boot same-session round-trip dest
;   $1C00  corrupt-slot load dest, $EE sentinel — must stay untouched
;   $1C80  cleared-slot load dest, $EE sentinel — must stay untouched
;
; Debug region map ($7E:E000, 16-bit results unless noted):
;   +$10  boot sf_save_exists(slot0)      run1: 0   run2: 1
;   +$12  boot sf_load(slot0 -> $1A00)    run1: $FFFF/$FFFE (virgin garbage
;         never passes magic+CRC)         run2: 64 (payload restored)
;   ---- first boot only ----
;   +$14  sf_save(slot0, $1800, 64, v1)   -> 0
;   +$16  sf_save_exists(slot0)           -> 1
;   +$18  sf_load(slot0 -> $1B00)         -> 64 (same-boot round trip)
;   +$1A  sf_save(slot1, $1800, 64, v1)   -> 0
;   +$1C  sf_load(slot1 -> $1C00) AFTER a payload byte is corrupted -> $FFFE
;   +$1E  sf_save_exists(slot1)           -> 0 (corrupt = no valid save)
;   +$20  sf_save_exists(slot2) post-save -> 1
;   +$22  sf_save_clear(slot2)            -> 0
;   +$24  sf_save_exists(slot2)           -> 0 (cleared)
;   +$26  sf_load(slot2 -> $1C80)         -> $FFFF (no save)
;   ---- second boot only ----
;   +$28  sf_save_exists(slot1)           -> 0 (corruption survived reset)
;   +$2A  sf_save_exists(slot2)           -> 0 (clear survived reset)
;   ----
;   +$30  boot phase marker: 1 = first boot, 2 = second boot
;
; Corruption is induced ROM-SIDE (the harness has no memory-write API):
; after saving slot 1, payload byte 5 (SRAM $080D) is EOR'd with $FF.
;
; Build:  ca65 ... -I lib/macros -I engine ; ld65 ... lorom_sram.cfg
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic/complete
.include "sf_save.inc"          ; sf_save, sf_load, sf_save_exists, sf_save_clear

PAT_VAL = $32                   ; DP scratch for the pattern fill (game var zone)

.segment "CODE"

NMI:
NMI_STUB:
    rti

RESET:
    sf_coldstart

    ; --- known 64-byte pattern at $7E:1800 (both boots) ---
    rep #$30
    .a16
    .i16
    ldx #$0000
    sep #$20
    .a8
    lda #$03
    sta PAT_VAL
pattern_fill:
    .a8
    lda PAT_VAL
    sta f:$7E1800,x
    clc
    adc #$07
    sta PAT_VAL
    inx
    cpx #$0040
    bne pattern_fill

    ; --- $EE sentinels at $7E:1C00-$7E:1CFF (rejected-load dests) ---
    ldx #$0000
    lda #$EE
sentinel_fill:
    .a8
    sta f:$7E1C00,x
    inx
    cpx #$0100
    bne sentinel_fill
    rep #$20
    .a16

    ; --- boot prologue (both boots): exists? + load slot 0 ---
    sf_save_exists 0
    ldx #$0000
    sta f:$7E0000 + $E010, x
    pha                         ; keep the discriminator

    sf_load 0, #$1A00
    ldx #$0000
    sta f:$7E0000 + $E012, x

    pla
    cmp #$0001
    bne first_boot
    jmp second_boot

; -----------------------------------------------------------------------------
first_boot:
    .a16
    .i16
    lda #$0001
    ldx #$0000
    sta f:$7E0000 + $E030, x

    ; save slot 0 + verify it answers exists + same-boot round trip
    sf_save 0, #$1800, 64, 1
    ldx #$0000
    sta f:$7E0000 + $E014, x

    sf_save_exists 0
    ldx #$0000
    sta f:$7E0000 + $E016, x

    sf_load 0, #$1B00
    ldx #$0000
    sta f:$7E0000 + $E018, x

    ; slot 1: save, then corrupt one payload byte, then the load must REJECT
    sf_save 1, #$1800, 64, 1
    ldx #$0000
    sta f:$7E0000 + $E01A, x

    sep #$20
    .a8
    ldx #$0000
    lda f:$700000 + $080D, x    ; slot 1 payload byte 5
    eor #$FF
    sta f:$700000 + $080D, x
    rep #$20
    .a16

    sf_load 1, #$1C00           ; -> $FFFE, $1C00 sentinels must survive
    ldx #$0000
    sta f:$7E0000 + $E01C, x

    sf_save_exists 1            ; -> 0
    ldx #$0000
    sta f:$7E0000 + $E01E, x

    ; slot 2: save -> exists -> clear -> not exists -> load = no save
    sf_save 2, #$1800, 64, 2
    sf_save_exists 2
    ldx #$0000
    sta f:$7E0000 + $E020, x

    sf_save_clear 2
    ldx #$0000
    sta f:$7E0000 + $E022, x

    sf_save_exists 2
    ldx #$0000
    sta f:$7E0000 + $E024, x

    sf_load 2, #$1C80           ; -> $FFFF, $1C80 sentinels must survive
    ldx #$0000
    sta f:$7E0000 + $E026, x

    jmp finish

; -----------------------------------------------------------------------------
second_boot:
    .a16
    .i16
    lda #$0002
    ldx #$0000
    sta f:$7E0000 + $E030, x

    ; the corrupt and cleared slots must STAY rejected across the reset
    sf_save_exists 1
    ldx #$0000
    sta f:$7E0000 + $E028, x

    sf_save_exists 2
    ldx #$0000
    sta f:$7E0000 + $E02A, x

; -----------------------------------------------------------------------------
finish:
    .a16
    .i16
    sf_debug_magic
    sf_debug_complete
    stp

.include "save_load_engine.asm"
