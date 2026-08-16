; =============================================================================
; oam_sprites.asm — OAM shadow runtime: boot park + per-VBlank commit
; =============================================================================
; The 544-B shadow (ES_OAM_SHADOW) is the single source of truth for OAM.
; oam_park_all writes EVERY byte at boot (Y=$F0 hides all 128 sprites; hi
; table zeroed: X9=0, size=small) — the DMA below then only ever reads
; initialized bytes. Scenes edit their claimed slots directly in the shadow.

OAMQ_REGS = $4300 + ES_H_OAMQ_CH * 16   ; the oamq channel's register file

; --- oam_park_all: park all 128 sprites + clear the hi table (boot init) ----
; In/out: A16/I16, DB=0. The shadow lives in low WRAM (bank-0 mirror).
OAM_LOW_BYTES = ES_OAM_SHADOW_SIZE - 32     ; 512-B entry table, 32-B hi table

oam_park_all:
    .a16
    .i16
    ldx #0
    lda #(240 << 8)                 ; entry bytes 0-1: X=0, Y=$F0 (off-screen)
:   sta a:ES_OAM_SHADOW, x
    inx
    inx
    stz a:ES_OAM_SHADOW, x          ; entry bytes 2-3: tile 0, attr 0
    inx
    inx
    cpx #OAM_LOW_BYTES
    bcc :-
:   stz a:ES_OAM_SHADOW, x          ; hi table: X9=0, size=small everywhere
    inx
    inx
    cpx #ES_OAM_SHADOW_SIZE
    bcc :-
    rts

; --- oam_nmi_dma: commit the shadow to hardware OAM (every armed VBlank) ----
; In: A8/I16, DB=0 (sm_nmi_hook contract). Clobbers A. One declared 544-B
; GP-DMA on the oamq vblank channel; OAMADD reset to 0 first (the PPU
; address advances with every OAM write and render — never assume it).
oam_nmi_dma:
    .a8
    .i16
    stz a:$2102                     ; OAMADD lo = 0
    stz a:$2103                     ; OAMADD hi = 0
    lda #ES_H_OAMQ_DMAP
    sta a:OAMQ_REGS + 0             ; DMAP: mode 0, A->B
    lda #ES_H_OAMQ_BBAD
    sta a:OAMQ_REGS + 1             ; BBAD: OAMDATA
    lda #ES_OAM_SHADOW_BANK
    sta a:OAMQ_REGS + 4             ; A1B
    rep #$20
    .a16
    lda #ES_OAM_SHADOW
    sta a:OAMQ_REGS + 2             ; A1T
    lda #ES_OAM_SHADOW_SIZE
    sta a:OAMQ_REGS + 5             ; DAS (single transfer, re-armed per frame)
    sep #$20
    .a8
    lda #(1 << ES_H_OAMQ_CH)
    sta a:$420B                     ; fire
    rts
