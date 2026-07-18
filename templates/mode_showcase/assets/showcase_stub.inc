; =============================================================================
; showcase_stub.inc — the GENERIC STUB PAGE for the not-yet-authored modes.
; =============================================================================
; Deliverable 7: ONE shared stub page so EVERY menu slot (modes 0,2,3,4,5,6,7)
; is live and the dispatch is provable across all 8 modes. The stub is a real,
; minimal page: it enters its mode under forced blank, paints a legible BG, and
; exposes ~3 real knobs (brightness + BG scroll) so the HUD/sheet/meter all work
; and a knob change is visible. The fan-out REPLACES each stub's registration row
; in place with the real page's row (same vtable slot) — no table/Makefile/
; main.asm edits.
;
; ONE set of shared procs covers every stub mode: the mode number is read at
; RUNTIME from SHOW_CUR_MODE (= the registered slot), so stub_demo_init passes
; the right mode to engine_gfxmode. All stub modes share one small param table +
; name tables (the knob model is identical); the macro `show_register_stub N`
; registers a mode against these shared symbols.
;
; Knob model (the stub's tiny but REAL surface — slot-major [slot*5+param]):
;   slot 0 BG    : SCX (BG1 X scroll) SCY (BG1 Y scroll)  - - -
;   slot 1 -     : (unused)
;   slot 2 LIGHT : BRT (screen brightness 0..15)          - - - -
;   slots 3-5    : (unused)
; The meter cost knob is the brightness knob (a visible, tunable proxy).
; =============================================================================

STUB_KN_SCX   = 0     ; slot 0 param 0 : BG1 X scroll
STUB_KN_SCY   = 1     ; slot 0 param 1 : BG1 Y scroll
STUB_KN_BRT   = 10    ; slot 2 param 0 : screen brightness
STUB_COST_KNOB = STUB_KN_BRT

; -----------------------------------------------------------------------------
; stub_param_tbl — 30 descriptors (min,max,step,default), slot-major. Only the
; three real knobs above carry a range; the rest are inert (0,1,1,0).
; -----------------------------------------------------------------------------
stub_param_tbl:
    ; slot 0 BG
    .byte 0, 255, 4, 0     ; SCX  BG1 X scroll
    .byte 0, 255, 4, 0     ; SCY  BG1 Y scroll
    .byte 0, 1, 1, 0       ; (unused)
    .byte 0, 1, 1, 0       ; (unused)
    .byte 0, 1, 1, 0       ; (unused)
    ; slot 1 (unused)
    .byte 0, 1, 1, 0
    .byte 0, 1, 1, 0
    .byte 0, 1, 1, 0
    .byte 0, 1, 1, 0
    .byte 0, 1, 1, 0
    ; slot 2 LIGHT
    .byte 0, 15, 1, 15     ; BRT  brightness 0..15 (def full)
    .byte 0, 1, 1, 0
    .byte 0, 1, 1, 0
    .byte 0, 1, 1, 0
    .byte 0, 1, 1, 0
    ; slot 3 (unused)
    .byte 0, 1, 1, 0
    .byte 0, 1, 1, 0
    .byte 0, 1, 1, 0
    .byte 0, 1, 1, 0
    .byte 0, 1, 1, 0
    ; slot 4 (unused)
    .byte 0, 1, 1, 0
    .byte 0, 1, 1, 0
    .byte 0, 1, 1, 0
    .byte 0, 1, 1, 0
    .byte 0, 1, 1, 0
    ; slot 5 (unused)
    .byte 0, 1, 1, 0
    .byte 0, 1, 1, 0
    .byte 0, 1, 1, 0
    .byte 0, 1, 1, 0
    .byte 0, 1, 1, 0

; --- slot labels (<=6 glyphs) ---
stub_sl0: .byte "BG", 0
stub_sl1: .byte "-", 0
stub_sl2: .byte "LIGHT", 0
stub_sl3: .byte "-", 0
stub_sl4: .byte "-", 0
stub_sl5: .byte "-", 0
stub_slot_name:
    .addr stub_sl0, stub_sl1, stub_sl2, stub_sl3, stub_sl4, stub_sl5

; --- param tags (<=3 glyphs) ---
stub_pn_scx: .byte "SCX", 0
stub_pn_scy: .byte "SCY", 0
stub_pn_brt: .byte "BRT", 0
stub_pn_dash: .byte "-", 0
stub_parm_name:
    .addr stub_pn_scx, stub_pn_scy, stub_pn_dash, stub_pn_dash, stub_pn_dash   ; slot 0
    .addr stub_pn_dash, stub_pn_dash, stub_pn_dash, stub_pn_dash, stub_pn_dash ; slot 1
    .addr stub_pn_brt, stub_pn_dash, stub_pn_dash, stub_pn_dash, stub_pn_dash  ; slot 2
    .addr stub_pn_dash, stub_pn_dash, stub_pn_dash, stub_pn_dash, stub_pn_dash ; slot 3
    .addr stub_pn_dash, stub_pn_dash, stub_pn_dash, stub_pn_dash, stub_pn_dash ; slot 4
    .addr stub_pn_dash, stub_pn_dash, stub_pn_dash, stub_pn_dash, stub_pn_dash ; slot 5

; --- a tiny BG1 4bpp tile: a solid block (idx 1) so the painted BG is legible --
stub_bg1_chr:
    .res 32, $00                      ; tile 0 transparent
    .byte $FF,$FF,$FF,$FF,$FF,$FF,$FF,$FF   ; tile 1 plane0 = all set (idx 1)
    .byte $00,$00,$00,$00,$00,$00,$00,$00
    .res 16, $00
stub_bg1_chr_end:

; =============================================================================
; stub_demo_init — enter SHOW_CUR_MODE under forced blank, paint a legible BG.
; =============================================================================
; WIDTH-RISK: A16/I16 entry; A8 around the VRAM/PPU byte writes; exits A16/I16.
.proc stub_demo_init
    rep #$30
    .a16
    .i16
    ; Forced blank for the VRAM authoring + mode switch.
    sep #$20
    .a8
    lda #$80
    sta $2100                       ; forced blank
    rep #$20
    .a16

    ; Re-seed the knob model to the stub defaults (preserves SHOW_CUR_MODE).
    jsr show_param_init

    ; Upload a single BG1 tile + a simple BG palette under forced blank.
    jsr stub_build_bg

    ; Enter the selected mode via the dispatcher (clears the shadow tilemaps).
    sep #$20
    .a8
    lda f:SHOW_CUR_MODE
    and #$07
    rep #$20
    .a16
    and #$00FF
    sta API_BLOCK_BASE + 0          ; param 0 = mode
    stz API_BLOCK_BASE + 2
    jsr engine_gfxmode

    ; Paint the BG1 shadow tilemap with a sparse pattern so the BG is visible and
    ; scroll is legible (NMI DMAs the shadow to VRAM).
    jsr stub_paint_tilemap

    ; Seed the limit-meter heartbeat snapshot (avoid a false RED on the first
    ; frame's stale-counter delta).
    lda FRAME_COUNTER
    sta f:SHOW_LAST_HEART

    ; Apply once + lift forced blank at the brightness knob.
    jsr stub_apply
    sep #$20
    .a8
    lda f:SHOW_KNOB_VAL + STUB_KN_BRT
    and #$0F
    sta SHADOW_INIDISP              ; NMI commits $2100
    sta $2100
    rep #$20
    .a16
    rts
.endproc

; =============================================================================
; stub_build_bg — BG1 chr (1 solid tile) + a 2-colour BG palette (forced blank).
; =============================================================================
; WIDTH-RISK: A16/I16 entry; A8 around the PPU byte writes; exits A16/I16.
.proc stub_build_bg
    rep #$30
    .a16
    .i16
    ; BG palette: pal 0 colour 0 = black, colour 1 = teal ($7E00 = G+B).
    sep #$20
    .a8
    stz $2121                         ; CGADD 0
    stz $2122
    stz $2122                         ; colour 0 = black
    lda #$E0
    sta $2122
    lda #$03
    sta $2122                         ; colour 1 = $03E0 green
    rep #$20
    .a16

    ; BG1 chr -> VRAM word $2000 (Mode-1 BG1 base; other modes use their own base
    ; from engine_gfxmode, but $2000 is a safe shared spot for the stub tile).
    sep #$20
    .a8
    lda #$80
    sta $2115                         ; VMAIN: inc after high
    rep #$20
    .a16
    lda #$2000
    sta $2116
    ldx #$0000
@b1:
    sep #$20
    .a8
    lda f:stub_bg1_chr, x
    sta $2118
    inx
    lda f:stub_bg1_chr, x
    sta $2119
    inx
    rep #$20
    .a16
    cpx #(stub_bg1_chr_end - stub_bg1_chr)
    bcc @b1
    rts
.endproc

; =============================================================================
; stub_paint_tilemap — fill the BG1 SHADOW tilemap with a sparse checker of the
; solid tile (tile 1) so the BG is legible + scroll is visible; mark BG1 dirty.
; =============================================================================
; WIDTH-RISK: A16/I16 entry; DB=$7E bracket for the shadow writes; exits A16/I16.
.proc stub_paint_tilemap
    rep #$30
    .a16
    .i16
    phb
    sep #$20
    .a8
    lda #$7E
    pha
    plb                               ; DB = $7E (shadow tilemaps live here)
    rep #$20
    .a16

    ldx #0                            ; flat tile index 0..1023
@b1:
    ; sparse checker: tile 1 where (row ^ col) & 1, else 0 (every other cell)
    txa
    lsr
    lsr
    lsr
    lsr
    lsr                               ; row
    pha                               ; [1,s] = row
    txa
    and #$1F                          ; col
    eor 1, s                          ; row ^ col
    ply                               ; balance pha (Y restored by the loop)
    and #$0001
    beq @blank
    lda #$0001                        ; tile 1 (solid)
    bra @put
@blank:
    lda #$0000
@put:
    phx                               ; save flat index
    pha                               ; save tile word
    txa
    asl                               ; X*2 = byte offset
    tay
    pla                               ; tile word
    sta SHADOW_BG1_TILEMAP, y         ; word store
    plx
    inx
    cpx #1024
    bcc @b1

    plb                               ; restore DB = $00

    ; Mark BG1 dirty so the NMI DMAs the shadow tilemap to VRAM.
    sep #$20
    .a8
    lda f:BG_TILEMAP_DIRTY
    ora #$01                          ; bit0 = BG1
    sta BG_TILEMAP_DIRTY
    rep #$20
    .a16
    rts
.endproc

; =============================================================================
; stub_apply — push the stub knobs to engine shadows (per frame). Brightness +
; BG1 scroll. Shadow-only (NMI commits) — no direct PPU writes in this path.
; =============================================================================
; WIDTH-RISK: A16/I16 entry; A8 for the byte stores; exits A16/I16.
.proc stub_apply
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    ; brightness -> SHADOW_INIDISP (forced-blank bit stays clear)
    lda f:SHOW_KNOB_VAL + STUB_KN_BRT
    and #$0F
    sta SHADOW_INIDISP
    ; BG1 X/Y scroll -> scroll shadows
    lda f:SHOW_KNOB_VAL + STUB_KN_SCX
    sta SHADOW_BG1HOFS
    stz SHADOW_BG1HOFS+1
    lda f:SHOW_KNOB_VAL + STUB_KN_SCY
    sta SHADOW_BG1VOFS
    stz SHADOW_BG1VOFS+1
    rep #$20
    .a16
    rts
.endproc

; =============================================================================
; stub_field_tick — the stub has no sprite field; just hold the field band base
; and record the realized OAM count so the meter's O signal reads reality.
; =============================================================================
; WIDTH-RISK: A16/I16 entry; A8 for the byte store; exits A16/I16.
.proc stub_field_tick
    rep #$30
    .a16
    .i16
    lda #SHOW_OAM_FIELD_BASE
    sta SPRITE_COUNT                  ; field band base (no field sprites placed)
    sep #$20
    .a8
    lda SPRITE_COUNT
    sta f:SHOW_OAM_USED              ; realized OAM = the HUD's high-water mark
    rep #$20
    .a16
    rts
.endproc

; =============================================================================
; stub_arena_ind — the stub holds no $C000 heavy effect; render the dash glyph
; (no owner) at the arena-indicator band (OBJ 39) so the band is consistent.
; =============================================================================
; WIDTH-RISK: A16/I16 entry; A8 for byte math; engine_spr A16/I16; exits A16/I16.
.proc stub_arena_ind
    rep #$30
    .a16
    .i16
    sep #$20
    .a8
    lda #SHOW_OAM_ARENA_BASE
    rep #$20
    .a16
    sta SPRITE_COUNT
    lda #SF_OBJG_DASH
    and #$00FF
    sta SF_SPR_TILE
    lda #200
    sta SF_SPR_X
    lda #6
    sta SF_SPR_Y
    lda #SF_OBJ_HUD_FLAGS
    sta SF_SPR_FLAGS
    lda #0
    sta SF_SPR_PRI
    jsr engine_spr
    rts
.endproc

; -----------------------------------------------------------------------------
; show_register_stub — register mode N against the shared stub symbols. The
; fan-out replaces this line with the real page's show_register_mode N, ... .
; -----------------------------------------------------------------------------
.macro show_register_stub N
    show_register_mode N, stub_demo_init, stub_apply, stub_field_tick, stub_arena_ind, stub_param_tbl, stub_slot_name, stub_parm_name, STUB_COST_KNOB
.endmacro

; --- register every not-yet-authored mode (2,3,4,5,6,7) ---
; Mode 0 is now a REAL page (showcase_mode0.inc / showcase_scene0.inc) — its
; show_register_stub 0 row was removed here per the fan-out stub->real swap.
show_register_stub 2
show_register_stub 3
show_register_stub 4
show_register_stub 5
show_register_stub 6
show_register_stub 7
