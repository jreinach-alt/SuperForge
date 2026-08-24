; =============================================================================
; player_car.asm — the race scene's screen-fixed 16x16 player sprite
; =============================================================================
; CHR + palette from the car_rom claims; OBSEL name base from the emitted
; encoding (obj chr claim — the allocator floored it past the Mode-7
; region); one OAM slot written into the oam_sprites shadow. All entry
; layout math is assemble-time expressions over emitted symbols.

CAR_SCREEN_X = 120                  ; centered: 128 - half a 16x16 sprite
CAR_SCREEN_Y = CAR_LINE             ; the game's declared car line (world.inc)
CAR_ATTR     = 3 << 4               ; priority 3, OBJ palette 0, no flips
CAR_ENTRY    = ES_OAM_SHADOW + ES_O_CAR * 4
CAR_HI_BYTE  = ES_OAM_SHADOW + OAM_LOW_BYTES + (ES_O_CAR >> 2)
CAR_HI_SIZE  = 2 << ((ES_O_CAR & 3) * 2)   ; this slot's size-select bit

; --- car_arm: CHR + palette upload, OBSEL, OAM slot (scene enter) -----------
; In/out: A16/I16, DB=0, forced blank + NMI masked (scene_mgr contract).
; GP-DMA register file addressed through the channel the car_up
; dma_init claim names — the channel number is declared, not assumed.
CAR_REGS = $4300 + ES_D_CAR_UP_CH * 16

car_arm:
    .a16
    .i16
    ; ---- CHR: 1024 B -> the obj chr claim (word port, DMA mode 1) ---------
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after high byte
    rep #$20
    .a16
    lda #ES_V_CAR_CHR
    sta a:$2116                     ; VMADD = claim base (>= the M7 floor)
    lda #.loword(car_chr_bin)
    sta a:CAR_REGS + 2                     ; A1T
    lda #ES_R_CAR_CHR_ROM_SIZE
    sta a:CAR_REGS + 5                     ; DAS
    sep #$20
    .a8
    lda #^car_chr_bin
    sta a:CAR_REGS + 4                     ; A1B
    lda #ES_D_CAR_UP_DMAP
    sta a:CAR_REGS + 0                     ; DMAP: A->B, 2 regs write-once
    lda #ES_D_CAR_UP_BBAD
    sta a:CAR_REGS + 1                     ; BBAD: VMDATAL
    lda #(1 << ES_D_CAR_UP_CH)
    sta a:$420B                     ; fire (enter-time: channel regs free)
    ; ---- palette: OBJ palette 0 (CGRAM words 128..143) --------------------
    lda #ES_C_CAR_PAL
    sta a:$2121                     ; CGADD = 128
    rep #$20
    .a16
    ldx #0
:   lda f:car_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_CAR_PAL_ROM_SIZE
    bcc :-
    ; ---- OBSEL: size mode 0 (8x8/16x16) | emitted name base ---------------
    sep #$20
    .a8
    lda #ES_V_CAR_CHR_OBSEL_BASE
    sta a:$2101
    ; ---- the OAM entry (shadow; the NMI commits it every armed frame) -----
    lda #CAR_SCREEN_X
    sta a:CAR_ENTRY + 0
    lda #CAR_SCREEN_Y
    sta a:CAR_ENTRY + 1
    stz a:CAR_ENTRY + 2             ; tile 0 (grid row pair base)
    lda #CAR_ATTR
    sta a:CAR_ENTRY + 3
    lda #CAR_HI_SIZE
    tsb a:CAR_HI_BYTE               ; large (16x16); X9 stays 0. test-and-set
                                    ;   instead of the load/or/store: the byte
                                    ;   is three other slots' bits too, and the
                                    ;   mask is the only thing this owns. `tsb`
                                    ;   sets Z from A AND memory rather than
                                    ;   from the result — nothing below reads it
    rep #$20
    .a16
    rts

; --- car_disarm: re-park the claimed slot (scene exit) ----------------------
; In/out: A16/I16, DB=0, forced blank.
car_disarm:
    .a16
    .i16
    sep #$20
    .a8
    lda #240
    sta a:CAR_ENTRY + 1             ; Y = $F0: off-screen
    lda #CAR_HI_SIZE
    trb a:CAR_HI_BYTE               ; size back to small, X9 untouched — and
                                    ;   the mask now names the bit being
                                    ;   cleared rather than the seven kept
    rep #$20
    .a16
    rts
