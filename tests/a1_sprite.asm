; =============================================================================
; a1_sprite.asm — macro library rung A1: place sprites via the spr macro
; =============================================================================
; The first rung that links the ENGINE. It proves the keystone calling
; convention: a macro marshals arguments into the engine API block and calls
; the engine function directly, producing correct engine output.
;
; Scope (honest, per the indirect-evidence rule): this rung verifies engine_spr's
; DIRECT output — the WRAM shadow OAM tables, SPRITE_COUNT, and OAM_DIRTY. It
; does NOT enable NMI or DMA, so nothing reaches hardware OAM yet; pushing the
; shadow to SnesSpriteRam over VBlank DMA is the frame loop's job (rung A2).
; The assertions read the shadow OAM region directly (not a proxy variable).
;
; Structure:
;   RESET -> sf_coldstart        (boot + WRAM clear; no engine state needed —
;                                 spr_clear re-inits the shadow OAM itself)
;         -> spr_clear           (all 128 slots Y=$F0, count=0, dirty=1)
;         -> spr  $42,100,80,$00,2   slot 0: plain sprite, priority 2
;         -> spr  $07,300,60,$80,1   slot 1: large + X9 set (x=300 -> bit8)
;         -> sf_debug_magic / sf_debug_complete / STP
;
; No init.inc, no NMI handler logic (NMI never enabled; bare RTI stub).
;
; Build (from repo root):
;   ca65 --cpu 65816 -I infrastructure/rom_template -I asm_repo_staging/lib/macros \
;        -I engine asm_repo_staging/tests/a1_sprite.asm -o a1.o
;   ld65 -C infrastructure/rom_template/lorom.cfg a1.o -o a1.sfc
;
; Verify (MesenRunner, reading engine_spr's direct output in WRAM):
;   $7E:0300 (slot 0) == 64 50 42 20   (x=100,y=80,tile=$42,attr=pri2<<4)
;   $7E:0304 (slot 1) == 2C 3C 07 10   (x=300&FF,y=60,tile=$07,attr=pri1<<4)
;   $7E:0500 (hi byte 0) == 0C         (slot1: X9 bit2 + size bit3)
;   $7E:0130 (SPRITE_COUNT) == 2
;   $7E:0132 (OAM_DIRTY)    == 1
;   $7E:E008 (completion)   == 1
; =============================================================================

.p816
.smart

.include "header.inc"

; --- macro library ---
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic, sf_debug_complete
.include "sf_sprite.inc"        ; spr, spr_clear

; --- engine equates (pure, no code emitted) ---
.include "engine_state.inc"

.segment "CODE"

; NMI is never enabled in A1 (no frame loop). Bare stub.
NMI:
NMI_STUB:
    rti

RESET:
    sf_coldstart                ; native bring-up + WRAM clear; exits A16/I16
    spr_clear                   ; init shadow OAM: Y=$F0 x128, count=0, dirty=1
    spr #$42, #100, #80, #$00, #2  ; slot 0 — plain sprite at (100,80), priority 2
    spr #$07, #300, #60, #$80, #1  ; slot 1 — large size + X=300 (X9 set), priority 1
    sf_debug_magic              ; "SFDB" -> $7E:E000
    sf_debug_complete           ; $0001  -> $7E:E008
    stp

; --- engine code linked into the ROM ---
; sprite_engine.asm's engine_spr_resolve references the DMA scheduler, so
; dma_scheduler.asm is its link partner even though A1 never resolves to
; hardware (no NMI/DMA this rung).
.include "dma_scheduler.asm"    ; dma_queue_add + DMA_STAGE_* (resolve path)
.include "sprite_engine.asm"    ; engine_spr, engine_spr_clear, hi-table masks
