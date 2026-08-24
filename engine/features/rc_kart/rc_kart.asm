; =============================================================================
; rc_kart.asm — the racer's OBJ surface: kart with lean frames + speed bar
; =============================================================================
; player_car's shape with the two things that rail does not have: a SECOND draw
; frame (the kart leans into a turn; the right lean is the left one H-flipped,
; so two directions cost one frame of CHR) and a SIX-TICK SPEED BAR, which is a
; HUD made of sprites because Mode 7 has no BG3 to print on.
;
; All entry layout math is assemble-time expressions over emitted symbols; the
; OBSEL name base is the allocator's ES_V_KART_CHR_OBSEL_BASE, so the "OBJ over
; Mode 7" gotcha — the map owns VRAM words $0000-$3FFF, so the OBJ base must be
; floored past it — is discharged by the claim rather than by a hand-narrated
; mask.
;
; THE BINDING CONTRACT: the includer supplies where the kart is drawn, because
; the screen line a rail plants its vehicle on is the rail's look and not this
; feature's (player_car takes CAR_LINE from world.inc for the same reason).
;
;  RCK_LINE the kart sprite's top scanline
;  RCK_BAR_LINE the speed bar's top scanline (in the sky band)
.ifndef RCK_LINE
    .error "rc_kart: the includer must define RCK_LINE (the kart's top scanline)"
.endif
.ifndef RCK_BAR_LINE
    .error "rc_kart: the includer must define RCK_BAR_LINE (the speed bar's top scanline)"
.endif

KART_X      = 120                   ; centred: 128 - half a 16x16 sprite
KART_ATTR   = 3 << 4                ; priority 3, OBJ palette 0, no flips
KART_ATTR_F = (3 << 4) | $40        ; ...H-flipped: the right lean
KART_T_STR  = 0                     ; straight frame: tiles 0,1,16,17
KART_T_LEAN = 2                     ; lean frame:     tiles 2,3,18,19
TICK_T_DIM  = 4                     ; speed-bar tick, unlit
TICK_T_LIT  = 5                     ; speed-bar tick, lit
BAR_X0      = 16                    ; first tick's x
BAR_DX      = 12                    ; tick pitch
BAR_ATTR    = 3 << 4                ; priority 3, OBJ palette 0
BAR_TICKS   = ES_O_BAR_SPRITES      ; DERIVED from the claim, not narrated

KART_ENTRY   = ES_OAM_SHADOW + ES_O_KART * 4
BAR_ENTRY    = ES_OAM_SHADOW + ES_O_BAR * 4
KART_HI_BYTE = ES_OAM_SHADOW + OAM_LOW_BYTES + (ES_O_KART >> 2)
KART_HI_SIZE = 2 << ((ES_O_KART & 3) * 2)   ; this slot's size-select bit

KART_REGS = $4300 + ES_D_KART_UP_CH * 16

; --- kart_arm: CHR + palette upload, OBSEL, the OAM slots (scene enter) -----
; CONTRACT kart_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the kart's CHR, palettes and OBSEL written
;   clobbers: A, X, Y, N, Z, C, V
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract
;   tail:     rts
kart_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "kart_arm"
    ; ---- CHR -> the obj chr claim (word port, DMA mode 1) -----------------
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    lda #ES_V_KART_CHR
    sta a:$2116                     ; VMADD = the claim base (past the M7 map)
    lda #.loword(kart_chr_bin)
    sta a:KART_REGS + 2             ; A1T
    lda #ES_R_KART_CHR_ROM_SIZE
    sta a:KART_REGS + 5             ; DAS
    sep #$20
    .a8
    lda #^kart_chr_bin
    sta a:KART_REGS + 4             ; A1B
    lda #ES_D_KART_UP_DMAP
    sta a:KART_REGS + 0             ; DMAP: A->B, 2 regs write-once
    lda #ES_D_KART_UP_BBAD
    sta a:KART_REGS + 1             ; BBAD: VMDATAL
    lda #(1 << ES_D_KART_UP_CH)
    sta a:$420B                     ; fire (enter-time: the channel regs free)
    ; ---- palette: OBJ palette 0 (CGRAM words 128..143) --------------------
    lda #ES_C_KART_PAL
    sta a:$2121                     ; CGADD = 128
    rep #$20
    .a16
    ldx #0
:   lda f:kart_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_KART_PAL_ROM_SIZE
    bcc :-
    ; ---- OBSEL: size mode 0 (8x8 small / 16x16 large) | emitted name base --
    sep #$20
    .a8
    lda #ES_V_KART_CHR_OBSEL_BASE
    sta a:$2101
    ; ---- the kart's OAM entry (shadow; the NMI commits it every frame) -----
    lda #KART_X
    sta a:KART_ENTRY + 0
    lda #RCK_LINE
    sta a:KART_ENTRY + 1
    lda #KART_T_STR
    sta a:KART_ENTRY + 2
    lda #KART_ATTR
    sta a:KART_ENTRY + 3
    ; The kart is the ONLY large sprite: the hi-table byte is rebuilt whole
    ; rather than read-modify-written, which is why the claim covers all four
    ; slots of it (hud_obj's argument). X9 stays 0 — every x here is < 256.
    lda #KART_HI_SIZE
    sta a:KART_HI_BYTE
    ; ---- the speed bar: six 8x8 ticks across the sky band ------------------
    ldx #0
    ldy #BAR_X0
@bar:
    .a8
    .i16
    tya
    sta a:BAR_ENTRY + 0, x          ; x
    lda #RCK_BAR_LINE
    sta a:BAR_ENTRY + 1, x          ; y
    lda #TICK_T_DIM
    sta a:BAR_ENTRY + 2, x          ; tile (kart_draw lights them)
    lda #BAR_ATTR
    sta a:BAR_ENTRY + 3, x
    ; Y += BAR_DX in A16, for the reason rc_grad's skeleton loop carries:
    ; `tya`/`tay` in A8/I16 move the FULL 16-bit C.
    rep #$20
    .a16
    tya
    clc
    adc #BAR_DX
    tay
    sep #$20
    .a8
    inx
    inx
    inx
    inx
    cpx #(BAR_TICKS * 4)
    bcc @bar
    rep #$20
    .a16
    rts

; --- kart_draw: this frame's kart frame + lit tick count --------------------
; CONTRACT kart_draw
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       X = the lean (0 straight, 1 lean-left, 2 lean-right)
;   out:      the kart's entries staged for that lean
;   clobbers: A, X, Y, N, Z, C
;   assumes:  once per frame from the scene tick, during active display
;   tail:     rts
;
; Y = number of lit ticks (0..BAR_TICKS). Writes the OAM SHADOW only — the
; declared VBlank GP-DMA owns hardware OAM.
;
; WIDTH-RISK: entry A16/I16; the body runs A8 for the byte-wide OAM stores and
; restores A16 before rts. Y is live across the whole A8 section, so I width is
; never touched (`sep #$20` alone, never `sep #$30`).
kart_draw:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "kart_draw"
    sep #$20
    .a8
    ; ---- kart frame: tile + attribute from the lean index -----------------
    cpx #1
    beq @lean_l
    cpx #2
    beq @lean_r
    lda #KART_T_STR
    sta a:KART_ENTRY + 2
    lda #KART_ATTR
    bra @frame_done
@lean_l:
    .a8
    .i16
    lda #KART_T_LEAN
    sta a:KART_ENTRY + 2
    lda #KART_ATTR                  ; the CHR leans LEFT as drawn
    bra @frame_done
@lean_r:
    .a8
    .i16
    lda #KART_T_LEAN
    sta a:KART_ENTRY + 2
    lda #KART_ATTR_F                ; ...H-flipped = leans right
@frame_done:
    .a8
    .i16
    sta a:KART_ENTRY + 3
    ; ---- speed bar: ticks 0..Y-1 lit, the rest dim ------------------------
    ldx #0
@tick:
    .a8
    .i16
    cpx #(BAR_TICKS * 4)
    bcs @done
    lda #TICK_T_LIT
    cpy #0
    bne @put
    lda #TICK_T_DIM
@put:
    .a8
    .i16
    sta a:BAR_ENTRY + 2, x
    cpy #0
    beq :+
    dey
:   inx
    inx
    inx
    inx
    bra @tick
@done:
    .a8
    .i16
    rep #$20
    .a16
    rts

; --- kart_disarm: re-park every claimed slot (scene exit) -------------------
; CONTRACT kart_disarm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the kart's slots parked and its registers put back
;   clobbers: A, X, N, Z, C
;   assumes:  forced blank, at scene exit
;   tail:     rts
kart_disarm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "kart_disarm"
    sep #$20
    .a8
    lda #240
    sta a:KART_ENTRY + 1            ; Y = $F0: off-screen
    ldx #0
@park:
    .a8
    .i16
    lda #240
    sta a:BAR_ENTRY + 1, x
    inx
    inx
    inx
    inx
    cpx #(BAR_TICKS * 4)
    bcc @park
    stz a:KART_HI_BYTE              ; size back to small, X9 clear
    rep #$20
    .a16
    rts
