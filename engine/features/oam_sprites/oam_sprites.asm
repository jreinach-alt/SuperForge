; =============================================================================
; oam_sprites.asm — OAM shadow runtime: boot park + per-VBlank commit
; =============================================================================
; The 544-B shadow (ES_OAM_SHADOW) is the single source of truth for OAM.
; oam_park_all writes EVERY byte at boot (Y=$F0 hides all 128 sprites; hi
; table zeroed: X9=0, size=small) — the DMA below then only ever reads
; initialized bytes. Scenes edit their claimed slots directly in the shadow.

OAMQ_REGS = $4300 + ES_H_OAMQ_CH * 16   ; the oamq channel's register file

; --- oam_park_all: park all 128 sprites + clear the hi table (boot init) ----
OAM_LOW_BYTES = ES_OAM_SHADOW_SIZE - 32     ; 512-B entry table, 32-B hi table

; CONTRACT oam_park_all
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      EVERY byte of the 544-B shadow written — Y=$F0 hides all 128
;             sprites, and the hi table is zeroed (X9=0, size=small). That
;             is what lets the per-VBlank DMA below only ever read
;             initialised bytes
;   clobbers: A, X, N, Z, C
;   assumes:  ONCE, at boot, before the first oam_nmi_dma. The shadow
;             lives in low WRAM (the bank-0 mirror), which is why the walk
;             is plain absolute-indexed
;   tail:     rts
oam_park_all:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "oam_park_all"
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
; CONTRACT oam_nmi_dma
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   in:       ES_OAM_SHADOW — the 544 bytes scenes edit in place
;   out:      hardware OAM committed by one declared 544-B GP-DMA on the
;             oamq vblank channel, with OAMADD reset to 0 first (the PPU
;             address advances with every OAM write AND every render —
;             never assume it)
;   clobbers: A, N, Z. The index registers are untouched
;   assumes:  VBlank, from the rail's sm_nmi_hook, in that hook's A8/I16
;             convention
;   tail:     rts
;
; GP-DMA on the oamq vblank channel; OAMADD reset to 0 first (the PPU
; address advances with every OAM write and render — never assume it).
oam_nmi_dma:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "oam_nmi_dma"
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
