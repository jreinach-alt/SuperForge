; superforge OBJ viewer probe — a ladder of 32x32 4bpp OBJ frames at true
; scale, so sprite art can be judged in-ROM on cycle-accurate hardware.
;
; A DISPLAY instrument in the probe family's shape (probe_vblank/probe_colmap):
; one allocator-mapped scene, no engine underneath, nothing in engine/ or
; game/ includes it. Eight static frames tile a row edge to edge (8 x 32 px =
; the full 256), each showing its frame index; a ninth slot below cycles
; through the frames every OBJV_RATE emulated frames, and a fresh press of A
; advances it immediately. The backdrop is a neutral mid-gray.
;
; CHR + palette are .incbin'd blobs. The committed placeholders come from
; tools/gen_objview_assets.py; the Makefile rule stages them into
; build/objview_assets/ and PROBE_OBJVIEW_CHR= / PROBE_OBJVIEW_PAL= swap in
; candidate art without committing it (documented at the rule).
;
; All RAM/VRAM/ROM addresses are allocator-emitted (engine_state_probe.inc);
; hardware I/O ports are the only literals.
.p816
.smart

.define SF_HDR_TITLE "SUPERFORGE OBJVIEW"
SF_HDR_TITLE_SET = 1
.include "engine_state_globals.inc"
.include "engine_state_probe.inc"

.include "header.inc"
.include "init.inc"
.include "sf_asm.inc"               ; shared macros: placement assertions + the
                                    ;   data-bank idioms (vendor/rom)

OBJV_FRAMES = 8                     ; ladder width, one 32x32 frame each
OBJV_RATE   = 16                    ; emulated frames per automatic advance
OBJV_ROW_Y  = 80                    ; ladder row's screen Y
OBJV_CYC_Y  = 144                   ; the cycling slot's screen Y
OBJV_CYC_X  = 112                   ; ...and X (centered)

.segment "CODE"

NMI_STUB:
    rti

; --- NMI: pad edge detect, the cycling slot's clock, one OAM word ----------
; All hardware writes here are VBlank-time by construction (this IS the NMI);
; the one OAM word rewritten per frame is the cycling slot's tile+attr.
NMI:
    rep #$30
    .a16
    .i16
    pha
    phx
    sep #$20
    .a8
    phb                         ; save caller DB
    lda #0
    pha
    plb                         ; DB = 0 for I/O
    lda a:$4210                 ; RDNMI: acknowledge
@joy_wait:
    lda a:$4212                 ; HVBJOY bit 0: auto-joypad still reading
    lsr a
    bcs @joy_wait

    lda a:$4218                 ; JOY1L bit 7 = A
    and #128                    ; A = held-now (0 or 128)
    pha                         ; [now] — 1 byte, A8, pulled below
    eor f:US_PREV_LONG          ; changed since last frame
    and 1, s                    ; ... and held now = a fresh press
    beq @no_press
    lda f:US_CUR_LONG           ; manual advance, and restart the clock
    inc a
    and #(OBJV_FRAMES - 1)
    sta f:US_CUR_LONG
    lda #OBJV_RATE
    sta f:US_TICK_LONG
    bra @edge_done
@no_press:
    .a8
    lda f:US_TICK_LONG          ; the automatic clock
    dec a
    sta f:US_TICK_LONG
    bne @edge_done
    lda f:US_CUR_LONG
    inc a
    and #(OBJV_FRAMES - 1)
    sta f:US_CUR_LONG
    lda #OBJV_RATE
    sta f:US_TICK_LONG
@edge_done:
    .a8
    pla                         ; [now]
    sta f:US_PREV_LONG

    ; commit the cycling slot's tile: OAMADD = its tile+attr word
    lda #<((ES_O_LADDER + 8) * 2 + 1)
    sta a:$2102
    lda #>((ES_O_LADDER + 8) * 2 + 1)
    sta a:$2103
    rep #$20
    .a16
    lda f:US_CUR_LONG           ; 16-bit read pairs in US_PREV's byte —
    and #(OBJV_FRAMES - 1)      ; masked off before the transfer
    tax
    sep #$20
    .a8
    lda f:frame_tiles, x
    sta a:$2104                 ; tile byte
    lda #48
    sta a:$2104                 ; attr byte — the write pair commits here

    rep #$20
    .a16
    lda f:US_SEQ_LONG
    inc a
    sta f:US_SEQ_LONG
    sep #$20
    .a8
    plb                         ; caller DB
    rep #$30
    .a16
    .i16
    plx
    pla
    rti

MAIN:
    .a16
    .i16
    ; ---- init contract: the probe's control block (power-on RAM is random) --
    sep #$20
    .a8
    lda #0
    sta f:US_CUR_LONG
    sta f:US_PREV_LONG
    lda #OBJV_RATE
    sta f:US_TICK_LONG
    rep #$20
    .a16
    lda #0
    sta f:US_SEQ_LONG

    ; ---- OBJ CHR: the whole 128-tile page to VRAM under forced blank -------
    ; (still asserted from init.inc; NMI not yet enabled, so the long CPU
    ; upload cannot be preempted — the NMI-mask discipline by construction)
    sep #$20
    .a8
    lda #$80
    sta $2115                   ; VMAIN: word step after $2119
    rep #$20
    .a16
    lda #ES_V_OBJV_CHR
    sta $2116                   ; VMADD = emitted OBJ page base
    ldx #0
@chr_loop:
    lda f:objview_chr_bin, x
    sta $2118                   ; A16 store: low -> $2118, high -> $2119
    inx
    inx
    cpx #ES_R_OBJV_CHR_ROM_SIZE
    bne @chr_loop

    ; ---- CGRAM: mid-gray backdrop at word 0, OBJ palette 0 at word 128 -----
    sep #$20
    .a8
    lda #ES_C_OBJV_BACK
    sta $2121                   ; CGADD = backdrop word
    lda f:backdrop_gray
    sta $2122
    lda f:backdrop_gray+1
    sta $2122
    lda #ES_C_OBJV_PAL
    sta $2121                   ; CGADD = OBJ palette 0 base
    ldx #0
@pal_loop:
    lda f:objview_pal_bin, x
    sta $2122
    inx
    cpx #ES_R_OBJV_PAL_ROM_SIZE
    bne @pal_loop

    ; ---- OAM: the 9 ladder entries, then park the rest, then the hi-table --
    stz $2102
    stz $2103                   ; OAMADD = word 0 (sprite 0)
    ldx #0                      ; X walks the 4-byte-per-sprite init table
@oam_loop:
    lda f:oam_init, x
    sta $2104
    inx
    cpx #(ES_O_LADDER_SPRITES * 4)
    bne @oam_loop
    ldy #(128 - ES_O_LADDER_SPRITES)
@park_loop:                     ; power-on OAM is random: park every unused
    .a8                         ; sprite offscreen (x=0, y=240, tile 0, attr 0)
    stz $2104
    lda #240
    sta $2104
    stz $2104
    stz $2104
    dey
    bne @park_loop
    stz $2102                   ; OAMADD = word 256: the hi-table base —
    lda #1                      ; explicit rather than trusting the
    sta $2103                   ; auto-increment across the table boundary
    ldx #0
@hi_loop:                       ; hi-table: 2 bits per sprite (X9, size) —
    lda f:oam_hi, x             ; ladder sprites LARGE (32x32), rest small
    sta $2104
    inx
    cpx #32
    bne @hi_loop

    ; ---- display on: OBJ only over the gray backdrop, NMI + auto-joypad ----
    lda #((1 << 5) | ES_V_OBJV_CHR_OBSEL_BASE)
    sta $2101                   ; OBSEL: size mode 1 (8x8 small / 32x32 large),
                                ;   OBJ CHR base from the claim
    lda #16
    sta $212C                   ; TM: OBJ layer only (bit 4)
    lda #15
    sta $2100                   ; INIDISP: full brightness, forced blank off
    lda #129
    sta $4200                   ; NMITIMEN: NMI on + auto-joypad

@spin:
    wai
    bra @spin

; ===========================================================================
; ROM data: the two viewer blobs, staged by the Makefile rule (override with
; PROBE_OBJVIEW_CHR= / PROBE_OBJVIEW_PAL=). Claim sites .assert their linker
; placement against the emitted symbols — the .incbin convention.
; ===========================================================================
.segment "RODATA"

backdrop_gray:                  ; BGR555 mid-gray (12,12,12 of 31)
    .word $318C

; frame index -> top-left tile number in the 16-tile-wide OBJ grid: frame I
; sits at grid column (I mod 4)*4, grid row (I/4)*4, and a 32x32 sprite
; reads tiles {N..N+3, N+16..} — the layout gen_objview_assets.py emits.
frame_tiles:
.repeat OBJV_FRAMES, I
    .byte (I / 4) * 64 + (I .MOD 4) * 4
.endrepeat

; the 9 ladder entries: x, y, tile, attr (attr 48 = priority 3, palette 0)
oam_init:
.repeat OBJV_FRAMES, I
    .byte I * 32, OBJV_ROW_Y, (I / 4) * 64 + (I .MOD 4) * 4, 48
.endrepeat
    .byte OBJV_CYC_X, OBJV_CYC_Y, 0, 48   ; the cycling slot, frame 0 first

; hi-table: 2 bits per sprite (bit 0 X9, bit 1 size). Ladder sprites are
; LARGE (32x32 in OBSEL size mode 1) with X9 clear -> %10 each; everything
; else small, X9 clear.
oam_hi:
    .byte 170, 170, 2           ; sprites 0-3, 4-7 all %10; sprite 8 %10
    .res 29, 0                  ; sprites 12..127 small (and parked at y=240)

.segment "BANK1"
objview_chr_bin:
    .incbin "objview_chr.bin"
.assert ^objview_chr_bin = ES_R_OBJV_CHR_ROM_BANK, error, "objview chr bank drifted"
.assert .loword(objview_chr_bin) = ES_R_OBJV_CHR_ROM_ADDR, error, "objview chr addr drifted"

objview_pal_bin:
    .incbin "objview_pal.bin"
.assert ^objview_pal_bin = ES_R_OBJV_PAL_ROM_BANK, error, "objview pal bank drifted"
.assert .loword(objview_pal_bin) = ES_R_OBJV_PAL_ROM_ADDR, error, "objview pal addr drifted"
