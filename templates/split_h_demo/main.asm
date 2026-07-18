; =============================================================================
; split_h_demo — cockpit-style horizontal raster-band split (sf_split_h v1 demo)
; =============================================================================
; Proves the horizontal raster-band split primitive: a Mode-7 PERSPECTIVE FLOOR
; (a receding textured ground plane) in the LOWER band, under a GENUINE TILE
; INSTRUMENT BAND (a real BG3 2bpp tile layer) in the TOP band. HDMA rewrites
; BGMODE + TM at a fixed scanline, so the top band renders as Mode 1 (BG3
; visible) and the bottom band as Mode 7 (the floor) — one clean scanline seam.
;
; This is the "cockpit rail": a receding ground plane under a live instrument
; panel. Minimal by design — it proves the primitive, not a game.
;
; THE SPLIT (routed through the HDMA allocator, NOT hand-hardcoded channels):
;   sf_split_h_2band SF_SPLIT_BGMODE, $09, $07, SPLIT, ... — top = Mode 1 + BG3
;       priority ($09); bottom = Mode 7 ($07).
;   sf_split_h_2band SF_SPLIT_TM,     $04, $01, SPLIT, ... — top = BG3 only
;       ($04); bottom = BG1 = the Mode-7 floor ($01).
; Each band's channel comes from hdma_request; hdma_bind_direct programs it.
;
; ARCHETYPE-D COMPANION (armed by default; -DNO_COLORBAND compiles it out):
;   sf_split_h_2band SF_SPLIT_COLDATA, ... — a fixed-colour band that tints the
;   lower floor WITHOUT a mode change (additive colour math on), proving the
;   cheap window/colour-band archetype alongside the mode split.
;
; VRAM BUDGET (spec §2.3 — Mode 7 owns the low 32 KB; tile layers live above):
;   Mode 7 map + CHR  VRAM word $0000..$3FFF  (interleaved, sf_mode7_load_map)
;   BG3 tilemap       VRAM word $4800         (BG3SC=$48 — upper 32 KB)
;   BG3 CHR           VRAM word $5000         (BG34NBA=$05 — upper 32 KB)
;   Per-band CGRAM:   floor -> CGRAM 0..5 (group 0);  BG3 -> CGRAM 16..19 (group 4,
;                     tile hi-byte $10) — the regions DO NOT overlap.
; BG3 is set up MANUALLY (NOT the engine gfxmode / mset path — its default
; BG34NBA=$0A wraps to word $2000, inside Mode 7, and its BG3 tilemap DMA targets
; word $6000). The base regs $2109/$210C are not committed by the engine NMI, so
; set once and they persist.
;
; THE DYNAMIC INSTRUMENT (D3): a horizontal fill-bar (BG3 tilemap row 2) whose
; filled tile length tracks a state variable that advances with input (P1
; Left/Right) or, in -DAUTODEMO, the frame counter. The bar row is rewritten to
; VRAM each frame under a brief top-of-frame forced blank, so the rendered bar
; RESPONDS — the done-condition asserts the fill length differs between states.
;
; CONTROLS:
;   P1 D-pad Left/Right  -> drive the instrument bar fill down / up
;   P1 L / R shoulders   -> spin the Mode-7 camera CCW / CW. A changing angle
;                           forces a FULL matrix rebuild every frame, so this is
;                           the "split under load" stress: the mode-band HDMA
;                           must hold while the Mode-7 matrix churns. Idle (no
;                           shoulder) = a cheap origin re-anchor, split at rest.
;
; COMPILE-TIME SWITCHES (the generic make rule can't pass -D):
;   -DNO_SPLIT=1     non-vacuity control: the mode/TM split is compiled out, so
;                    the whole screen is a single Mode-7 floor with NO tile band
;                    — the D1 top-band tile signature MUST be ABSENT.
;   -DNO_COLORBAND=1 non-vacuity control: the COLDATA companion band is compiled
;                    out — the D4 colour-band pixel change MUST be ABSENT.
;   -DFREEZE_BAR=1   non-vacuity control: the bar fill is pinned constant — the
;                    D3 two-state fill-difference MUST be ABSENT.
;   -DAUTODEMO=1     self-running (no controller): the bar sweeps up/down on the
;                    frame counter AND the camera spins continuously — so the
;                    split-under-load stress runs without input (for CI / the
;                    rotation done-condition).
;
; Build:  make split_h_demo
;         bash templates/split_h_demo/build_split_h_variants.sh   (the -D ROMs)
; LDCFG: lorom_64k.cfg
;   ^ Linker-config sentinel: 64KB image, the 32KB Mode 7 floor-map blob fills
;     BANK1 (same pattern as the racer / chamber rails).
; =============================================================================

.p816
.smart

.include "header.inc"
.include "sf_core.inc"          ; sf_coldstart, sf_debug_magic
.include "sf_frame.inc"         ; sf_engine_init, sf_frame_begin/end
.include "sf_mode7.inc"         ; the Mode 7 perspective macro group
.include "sf_split_h.inc"       ; the horizontal raster-band split front door
.include "sf_fx.inc"            ; colour math (additive — the COLDATA-band dep)
.include "sf_input.inc"         ; btn
.include "buttons.inc"
.include "engine_state.inc"

; --- the cockpit camera (floor fills line SPLIT..224 under the tile band) -----
SPLIT             = 40          ; the HUD/floor split scanline (band boundary)
PV_L0             = SPLIT       ; perspective horizon = the split line
PV_L1             = 224
PV_S0             = 320         ; far-scale (the floor recedes)
PV_S1             = 64          ; near-scale
PV_SH             = 640         ; vertical texel height (row density)
PV_INTERP         = 1
PV_WRAP           = 1
FOCUS_Y           = 128
START_X           = 512
START_Y           = 512

; --- the mode-split band bytes (the proven archetype-A recipe) ---------------
BGM_TOP = $09                   ; top band: Mode 1 + BG3 priority (BG3 shows)
BGM_BOT = $07                   ; bottom band: Mode 7 (the floor)
TM_TOP  = $04                   ; top band: BG3 only (the instrument panel)
TM_BOT  = $01                   ; bottom band: BG1 only (the Mode-7 floor)

; --- the COLDATA companion band (archetype D — a fixed-colour tint band) ------
COL_TOP = $80                   ; top band: no added colour (bit7 = 0 intensity)
COL_BOT = $E4                   ; bottom band: add a mid grey (R+G+B intensity 4)

; --- the brightness band (archetype D — -DBRIGHT_BAND; SF_SPLIT_BRIGHT/INIDISP)
;     top band FULL brightness ($0F), bottom band DIMMED ($08 = half). INIDISP
;     bits 0-3 = master brightness; bit7 (force-blank) stays 0 in both. This
;     exercises SF_SPLIT_BRIGHT, a registry equate the default demo never uses. -
BRT_TOP = $0F                   ; top band: brightness 15 (full)
BRT_BOT = $08                   ; bottom band: brightness 8 (dimmed ~half)

; --- HDMA allocator effect tags (distinct per band) ---------------------------
FX_BGM  = $11
FX_TM   = $12
FX_COL  = $13
FX_BRT  = $14                   ; -DBRIGHT_BAND brightness band
FX_3B   = $15                   ; -DTHREEBAND 3-band TM split

; --- the 3-band brightness split (-DTHREEBAND) — demonstrates sf_split_h_bands
;     with THREE distinct regions on INIDISP ($2100) brightness: top FULL ($0F),
;     middle HALF ($08), bottom DIM ($04). Three horizontal brightness regions
;     render distinctly regardless of layer content (unlike a TM band, which is
;     invisible where the enabled layer has no content). Band 0 = SPLIT lines,
;     band 1 = 80 lines, then the dim floor holds to the frame end. -
B3_B0    = $0F                  ; band 0 (top): full brightness
B3_B1    = $08                  ; band 1 (middle): half brightness
B3_B2    = $04                  ; band 2 (bottom): dim
B3_LINES0 = SPLIT               ; band-0 line count
B3_LINES1 = 80                  ; band-1 line count

; --- BG3 placement in the UPPER 32 KB (clear of Mode 7's $0000..$3FFF) --------
BG3_TM_VRAM  = $4800            ; BG3 tilemap word address
BG3_CHR_VRAM = $5000            ; BG3 CHR word address
BG3SC_VAL    = $48              ; $2109: tilemap word $4800 (($48 & $7C) << 8)
BG34NBA_VAL  = $05              ; $210C: BG3 CHR word $5000 (($05 & $07) << 12)

; --- the instrument-band tilemap layout (32-col BG3 tilemap rows) -------------
BAND_ROW_FRAME_T = 0            ; top frame rule row
BAND_ROW_GAUGE   = 1            ; decorative gauge-light row
BAND_ROW_BAR     = 2            ; the DYNAMIC fill-bar row
BAND_ROW_FRAME_B = 4            ; bottom frame rule row
BAR_COL0         = 2            ; bar left column
BAR_LEN          = 24           ; bar length in tiles (max fill)
PAL_HI           = $1000        ; BG3 tilemap-word palette bits (group 4 = bits
                                ;   10-12; $1000 puts $10 in the HIGH byte). NOTE:
                                ;   this is the 16-bit word OR value, NOT a low
                                ;   byte — draw_band writes full words to $2118.

BAR_MAX  = BAR_LEN
BAR_SPD  = 1                    ; fill change per frame while held

; --- CGRAM budget (archetype A) — the two band palettes MUST NOT overlap ------
; The Mode-7 floor palette lives in group 0 (CGRAM 0..); the BG3 HUD palette in
; group 4 (CGRAM 16..). The BG3 tilemap word's palette bits (PAL_HI = $1000 ->
; $10 in the tilemap-word HIGH byte) select group 4, so BG3 reads CGRAM 16..19.
; If a future edit grew the floor palette past index 15 (or moved the HUD group
; down) the two would collide — a silent trap (the HUD would render in floor
; colours). The .assert below FAILS the build if they ever overlap.
FLOOR_CGRAM_BASE = 0            ; Mode-7 floor palette first CGRAM index (group 0)
FLOOR_CGRAM_END  = FLOOR_CGRAM_BASE + FLOOR_PAL_COUNT - 1  ; last floor index
BG3_CGRAM_BASE   = 16           ; BG3 HUD palette first CGRAM index (group 4;
                                ;   PAL_HI $1000 -> tilemap hi-byte $10 -> grp 4)
BG3_CGRAM_END    = BG3_CGRAM_BASE + DASH_PAL_COUNT - 1     ; last HUD index
.assert FLOOR_CGRAM_END < BG3_CGRAM_BASE, error, "CGRAM overlap: Mode-7 floor palette (0..FLOOR_CGRAM_END) collides with BG3 HUD group 4 (base 16) — shrink the floor palette or move the HUD palette group"
ROT_SPD  = 2                    ; Mode-7 camera angle units/frame while a
                                ;   shoulder is held (256 = a full turn) — a
                                ;   changing angle forces sf_mode7_tick to do a
                                ;   FULL matrix rebuild every frame (the "under
                                ;   load" stress: CH5/CH6 matrix HDMA churns
                                ;   while the CH2/CH3 BGMODE+TM split HDMA runs).

; --- game DP state (kit contract: $32-$5F) -----------------------------------
; NOTE: sf_mode7_cam treats the camera Y source as a multi-byte (16.8) value, so
; the camera state effectively spans $32-$37 — keep game state clear of that.
C_POSX   = $32                  ; word: Mode-7 camera X (fixed — the camera spins
                                ;   in place around FOCUS_Y, it does not travel)
C_POSY   = $34                  ; word: Mode-7 camera Y (fixed; engine may touch +2)
G_FILL   = $50                  ; word: current bar fill (0..BAR_LEN)
G_AUTOD  = $52                  ; word: autodemo phase accumulator
G_ANGLE  = $54                  ; word: Mode-7 camera angle (low byte = 0..255);
                                ;   L/R shoulders spin it -> per-frame rebuild
G_MSK_BGM = $56                 ; word: CH mask for the BGMODE band (for _off/re-arm)
G_MSK_TM  = $58                 ; word: CH mask for the TM band (for _off/re-arm)
G_TGL_ST  = $5A                 ; word: -DTOGGLE_SPLIT phase (0=armed,1=off,2=rearmed)
G_TGL_PREV = $5C                ; word: previous frame's A-button state (edge detect)

; --- the dynamic bar-row VRAM staging buffer (WRAM debug region, 24 words) -----
; draw_bar builds the bar row HERE (a stable WRAM source); the game loop then
; enqueues a GP-DMA of these 48 bytes -> VRAM on the engine VBlank queue (the
; kit-idiomatic path — no mid-frame forced blank). $7EE020 is free debug region
; ($E000 = SFDB magic, $E010 = heartbeat; $E0A0+/$E100+ owned by the engine).
BAR_BUF      = $7EE020          ; 48 bytes = BAR_LEN words
BAR_BUF_VRAM = BG3_TM_VRAM + BAND_ROW_BAR * 32 + BAR_COL0  ; VRAM word dest

.segment "CODE"

NMI:
.include "nmi_handler.asm"      ; pulls mode7_nmi.inc (M7SEL/M7X/M7Y commit)

NMI_STUB:
    rti

RESET:
    sf_coldstart                ; forced blank; WRAM/CGRAM/VRAM cleared
    sf_engine_init
    jsr hdma_alloc_init         ; allocator baseline (reserves CH0/CH1)

    ; --- Mode-7 floor map upload (under the coldstart forced blank) ---
    sf_mode7_load_map floor_map, #$8000

    ; --- Mode 7 floor palette -> CGRAM 0.. (idx 0 = backdrop) ---
    sep #$20
    .a8
    rep #$10
    .i16
    stz $2121                   ; CGADD = 0
    ldx #$0000
fpal_loop:
    .a8
    lda f:floor_pal, x
    sta $2122
    inx
    cpx #(FLOOR_PAL_COUNT * 2)
    bne fpal_loop

    ; --- BG3 instrument palette -> CGRAM[16..19] (group 4) ---
    lda #$10                    ; CGADD = 16
    sta $2121
    ldx #$0000
dpal_loop:
    .a8
    lda f:dash_pal, x
    sta $2122
    inx
    cpx #(DASH_PAL_COUNT * 2)
    bne dpal_loop

    ; --- Upload BG3 CHR (2bpp) -> VRAM word $5000 (upper 32 KB) ---
    lda #$80
    sta $2115                   ; VMAIN: increment after $2119, +1 word
    rep #$20
    .a16
    lda #BG3_CHR_VRAM
    sta $2116                   ; VMADD word address
    sep #$20
    .a8
    rep #$10
    .i16
    ldx #$0000
chr_loop:
    .a8
    .i16
    lda f:dash_chr, x
    sta $2118                   ; VMDATA low
    inx
    lda f:dash_chr, x
    sta $2119                   ; VMDATA high (triggers word increment)
    inx
    cpx #DASH_CHR_BYTES
    bcc chr_loop

    ; --- point BG3 at its upper-32KB regions (NOT NMI-committed; set once) ---
    lda #BG3SC_VAL
    sta $2109                   ; BG3SC: tilemap word $4800
    lda #BG34NBA_VAL
    sta $210C                   ; BG34NBA: BG3 CHR word $5000
    stz SHADOW_BG3HOFS
    stz SHADOW_BG3HOFS + 1
    stz SHADOW_BG3VOFS
    stz SHADOW_BG3VOFS + 1       ; BG3 scroll = 0 (band content unscrolled)
    rep #$30
    .a16
    .i16

    ; --- write the BG3 instrument-band tilemap to VRAM $4800 (forced blank) ---
    lda #(BAR_MAX / 2)
    sta G_FILL                  ; start half-full
    stz G_AUTOD
    stz G_ANGLE                 ; camera faces forward (angle 0) at boot
    stz G_TGL_ST                ; -DTOGGLE_SPLIT phase 0 (split armed)
    stz G_TGL_PREV              ; A-button edge-detect state
    jsr draw_band_static
    jsr draw_bar                ; build the bar row into WRAM BAR_BUF
    jsr bar_buf_to_vram         ; boot: copy it to VRAM directly (forced blank)

    ; --- additive colour math so the COLDATA companion band is VISIBLE (D). On
    ;     BG1 (the floor) + backdrop; tint 0 so the static COLDATA is black and
    ;     the per-band HDMA ramp owns the visible colour step. ---
.ifndef NO_COLORBAND
    sf_colormath_on #1, #$21
    sf_colormath_tint #0, #0, #0
.endif

    ; --- Mode 7 on + the (static) cockpit floor camera ---
    sf_mode7_on
    sf_mode7_perspective #PV_L0, #PV_L1, #PV_S0, #PV_S1, #PV_SH, #PV_INTERP, #PV_WRAP
    sf_mode7_focus #FOCUS_Y
    sf_mode7_flags #$00

    lda #START_X
    sta C_POSX
    lda #START_Y
    sta C_POSY
    sf_mode7_cam C_POSX, C_POSY, #0

    sf_mode7_tick               ; first table build BEFORE screen-on

    ; --- arm the split bands through the allocator (NOT hardcoded channels) ---
    ; Capture each band's channel mask from ENGINE_A0 right after arming so the
    ; -DTOGGLE_SPLIT lifecycle path can sf_split_h_off / re-arm them (harmless in
    ; every build — just two DP words).
    stz G_MSK_BGM
    stz G_MSK_TM
.ifndef NO_SPLIT
.ifdef THREEBAND
    ; -DTHREEBAND: keep the mode/TM split (so the BG3 instrument still shows in
    ; the top band) AND add a 3-region BRIGHTNESS split via sf_split_h_bands —
    ; three horizontal brightness regions (full / half / dim) render distinctly.
    sf_split_h_2band SF_SPLIT_BGMODE, BGM_TOP, BGM_BOT, SPLIT, tbl_bgm, FX_BGM
    lda ENGINE_A0
    sta G_MSK_BGM
    sf_split_h_2band SF_SPLIT_TM, TM_TOP, TM_BOT, SPLIT, tbl_tm, FX_TM
    lda ENGINE_A0
    sta G_MSK_TM
    sf_split_h_bands SF_SPLIT_BRIGHT, tbl_b3, FX_3B, {B3_LINES0, B3_B0, B3_LINES1, B3_B1, 80, B3_B2}
.else
    sf_split_h_2band SF_SPLIT_BGMODE, BGM_TOP, BGM_BOT, SPLIT, tbl_bgm, FX_BGM
    lda ENGINE_A0
    sta G_MSK_BGM
    sf_split_h_2band SF_SPLIT_TM, TM_TOP, TM_BOT, SPLIT, tbl_tm, FX_TM
    lda ENGINE_A0
    sta G_MSK_TM
.endif
.endif
.ifndef NO_COLORBAND
    sf_split_h_2band SF_SPLIT_COLDATA, COL_TOP, COL_BOT, SPLIT, tbl_col, FX_COL
.endif
.ifdef BRIGHT_BAND
    ; archetype-D brightness band on INIDISP ($2100): top full, bottom dimmed.
    sf_split_h_2band SF_SPLIT_BRIGHT, BRT_TOP, BRT_BOT, SPLIT, tbl_brt, FX_BRT
.endif

    sf_debug_magic

    ; --- screen on + NMI on ---
    sep #$20
    .a8
    lda #$0F
    sta $2100                   ; INIDISP: bright 15, display on
    sta SHADOW_INIDISP          ; the NMI re-commits INIDISP from this shadow
    lda #$81
    sta $4200                   ; NMI + auto-joypad
    rep #$30
    .a16
    .i16

; =============================================================================
game_loop:
    .a16
    .i16
    sf_frame_begin              ; wait for the NMI; latch input

    ; --- rotation (the stress test): spin the Mode-7 camera in place. A CHANGING
    ;     angle makes sf_mode7_cam set M7_DIRTY_REBUILD, so sf_mode7_tick does a
    ;     FULL per-scanline matrix rebuild every frame (CH5/CH6 matrix HDMA
    ;     churning) — the split's BGMODE/TM band HDMA (CH2/CH3) must hold under it.
    ;     When no shoulder is held the angle is unchanged -> only a cheap origin
    ;     re-anchor (the split idles at the same low cost as the static rail). ---
.ifdef AUTODEMO
    ; controller-free: continuous slow spin so the stress runs without input.
    lda G_ANGLE
    inc a
    and #$00FF
    sta G_ANGLE
.else
    btn #BTN_R, #0              ; R shoulder: spin clockwise
    cmp #1
    bne @rot_chk_l
    lda G_ANGLE
    clc
    adc #ROT_SPD
    and #$00FF
    sta G_ANGLE
@rot_chk_l:
    .a16
    .i16
    btn #BTN_L, #0             ; L shoulder: spin counter-clockwise
    cmp #1
    bne @rot_done
    lda G_ANGLE
    sec
    sbc #ROT_SPD
    and #$00FF
    sta G_ANGLE
@rot_done:
    .a16
    .i16
.endif
    sf_mode7_cam C_POSX, C_POSY, G_ANGLE
    sf_mode7_tick

.ifdef TOGGLE_SPLIT
    ; --- lifecycle exercise (-DTOGGLE_SPLIT): edge-detected P1 A cycles the
    ;     mode/TM split OFF (sf_split_h_off on the BGMODE+TM channels -> collapses
    ;     to full-screen Mode 7, like -DNO_SPLIT) then back ON (sf_split_h_arm the
    ;     same RODATA tables). Phase 0=armed, 1=off, 2=re-armed. The masks were
    ;     captured into G_MSK_BGM/G_MSK_TM at arm time. ---
    ; Edge-detect P1 A. Only a fresh 0->1 press with a not-yet-latched phase
    ; reaches the dispatch (@tgl_edge); everything else branches SHORT to
    ; @tgl_done (which is far past the macro expansions, so we must not forward-
    ; branch to it across them — hence the invert-to-@tgl_edge pattern here).
    btn #BTN_A, #0              ; A = current press state (1 = down)
    tay                         ; Y = current A state (I16)
    cmp G_TGL_PREV
    bne @tgl_changed
    jmp @tgl_done               ; no change (trampoline — @tgl_done is far)
@tgl_changed:
    .a16
    .i16
    sty G_TGL_PREV              ; store new state
    tya
    cmp #1
    beq @tgl_edge               ; a press EDGE (0->1) — dispatch on phase
    jmp @tgl_done               ; a release edge — ignore
@tgl_edge:
    .a16
    .i16
    lda G_TGL_ST
    beq @tgl_off                ; phase 0 -> OFF
    cmp #1
    beq @tgl_rearm              ; phase 1 -> re-arm
    jmp @tgl_done               ; phase >=2 -> latched, no more toggles
@tgl_off:
    .a16
    .i16
    ; phase 0 -> OFF: release + disarm the BGMODE and TM channels.
    sf_split_h_off G_MSK_BGM
    sf_split_h_off G_MSK_TM
    lda #1
    sta G_TGL_ST
    jmp @tgl_done
@tgl_rearm:
    .a16
    .i16
    ; phase 1 -> re-arm the SAME RODATA tables on fresh allocator channels.
    sf_split_h_arm SF_SPLIT_BGMODE, tbl_bgm, FX_BGM
    lda ENGINE_A0
    sta G_MSK_BGM
    sf_split_h_arm SF_SPLIT_TM, tbl_tm, FX_TM
    lda ENGINE_A0
    sta G_MSK_TM
    lda #2
    sta G_TGL_ST
@tgl_done:
    .a16
    .i16
.endif

.ifdef FREEZE_BAR
    ; non-vacuity control: the bar fill never changes -> D3 must FAIL.
    jmp @commit
.endif

.ifdef AUTODEMO
    ; self-running: sweep the fill up then down on a triangle wave.
    lda G_AUTOD
    inc a
    and #$00FF
    sta G_AUTOD
    lsr
    lsr                         ; phase/4 (0..63)
    and #$003F
    cmp #32
    bcc @auto_up
    eor #$FFFF
    clc
    adc #64                     ; falling half: 64 - phase
@auto_up:
    .a16
    cmp #(BAR_MAX + 1)
    bcc :+
    lda #BAR_MAX
:   sta G_FILL
    jmp @commit
.endif

    ; --- P1 Right: fill up (clamped at BAR_MAX) ---
    btn #BTN_RIGHT, #0
    cmp #1
    bne @chk_left
    lda G_FILL
    cmp #BAR_MAX
    bcs @chk_left               ; already full
    inc a                       ; += BAR_SPD (1)
    sta G_FILL
@chk_left:
    .a16
    .i16
    ; --- P1 Left: fill down (clamped at 0) ---
    btn #BTN_LEFT, #0
    cmp #1
    bne @commit
    lda G_FILL
    beq @commit                 ; already empty
    dec a                       ; -= BAR_SPD (1)
    sta G_FILL
@commit:
    .a16
    .i16
    ; --- update the dynamic bar row via the engine VBlank DMA queue (the kit
    ;     idiom — NO mid-frame forced blank). draw_bar builds the row into WRAM
    ;     BAR_BUF (touches no PPU port); bar_enqueue sets VMAIN/VMADD and queues a
    ;     GP-DMA of the 24 words. The NMI drains it during the NEXT VBlank (Phase
    ;     3, before any tilemap/stream DMA), so the port is stable and the display
    ;     never blanks. sf_frame_end below calls dma_queue_signal. ---
    jsr draw_bar
    jsr bar_enqueue

    ; --- heartbeat mirror ($7E:E010) — SEQUENCING screenshots only ---
    lda FRAME_COUNTER
    ldx #$0000
    sta f:$7E0000 + $E010, x

    sf_frame_end
    jmp game_loop

; =============================================================================
; draw_band_static — write the FIXED instrument-band tilemap cells directly to
; the BG3 tilemap in VRAM (word $4800): top frame rule (row 0), a row of
; alternating gauge lights (row 1), bottom frame rule (row 4). Written under
; forced blank (VRAM port stable). VMAIN=$80 (+1 word).
; WIDTH-RISK: entry A16/I16. A8 for VMAIN; A16 for the word writes; exits A16/I16.
; =============================================================================
draw_band_static:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta $2115                   ; VMAIN: +1 word, increment after $2119
    rep #$30
    .a16
    .i16
    ; --- clear the ENTIRE 32x32 BG3 tilemap to BLANK first (power-on VRAM is
    ;     random; a BG3 tilemap cell that was never written points at garbage
    ;     CHR — so blank every cell, then paint the band rows over it). ---
    lda #BG3_TM_VRAM
    sta $2116
    ldx #$0000
@clr:
    .a16
    .i16
    lda #(DASH_TILE_BLANK | PAL_HI)
    sta $2118
    inx
    cpx #(32 * 32)
    bcc @clr
    ; --- top frame rule (row 0) ---
    lda #(BG3_TM_VRAM + BAND_ROW_FRAME_T * 32)
    sta $2116
    ldx #$0000
@row0:
    .a16
    .i16
    lda #(DASH_TILE_FRAME_TOP | PAL_HI)
    sta $2118                   ; word write (low+high) -> +1 word
    inx
    cpx #(BAR_COL0 + BAR_LEN)
    bcc @row0
    ; --- gauge row (row 1): alternate lit / dim ---
    lda #(BG3_TM_VRAM + BAND_ROW_GAUGE * 32)
    sta $2116
    ldx #$0000
@row1:
    .a16
    .i16
    txa
    and #$0001
    beq @g_lit
    lda #(DASH_TILE_GAUGE_DIM | PAL_HI)
    bra @g_set
@g_lit:
    .a16
    .i16
    lda #(DASH_TILE_GAUGE_LIT | PAL_HI)
@g_set:
    .a16
    .i16
    sta $2118
    inx
    cpx #(BAR_COL0 + BAR_LEN)
    bcc @row1
    ; --- bottom frame rule (row 4) ---
    lda #(BG3_TM_VRAM + BAND_ROW_FRAME_B * 32)
    sta $2116
    ldx #$0000
@row4:
    .a16
    .i16
    lda #(DASH_TILE_FRAME_BOT | PAL_HI)
    sta $2118
    inx
    cpx #(BAR_COL0 + BAR_LEN)
    bcc @row4
    rts

; =============================================================================
; draw_bar — BUILD the DYNAMIC fill-bar row (row 2) into the WRAM staging buffer
; BAR_BUF (24 tilemap words): the first G_FILL cells are BAR_FILL, the rest up to
; BAR_LEN are BAR_EMPTY. The rendered fill length tracks G_FILL (the D3 dynamic
; instrument). This ONLY writes WRAM — it does NOT touch the VRAM port, so it
; needs NO forced blank. bar_enqueue (game loop) / bar_buf_to_vram (boot) push
; the buffer into VRAM. Kit-idiomatic: build a stable source in WRAM, then DMA.
; WIDTH-RISK: entry A16/I16; stays A16/I16 throughout (word stores to BAR_BUF).
; =============================================================================
draw_bar:
    .a16
    .i16
    ; X = byte offset into BAR_BUF (0,2,4,...) — long,X is the only long-indexed
    ; store mode (long,Y is illegal). Y = cell index 0..BAR_LEN-1 (for the fill
    ; compare against G_FILL).
    ldx #$0000
    ldy #$0000
@bar_loop:
    .a16
    .i16
    tya
    cmp G_FILL
    bcc @bar_fill
    lda #(DASH_TILE_BAR_EMPTY | PAL_HI)
    bra @bar_set
@bar_fill:
    .a16
    .i16
    lda #(DASH_TILE_BAR_FILL | PAL_HI)
@bar_set:
    .a16
    .i16
    sta f:BAR_BUF, x            ; WRAM word store (long,X — BAR_BUF is $7Exxxx)
    inx
    inx                         ; +1 word (2 bytes)
    iny                         ; +1 cell
    cpy #BAR_LEN
    bcc @bar_loop
    rts

; =============================================================================
; bar_buf_to_vram — copy the WRAM BAR_BUF into the BG3 tilemap in VRAM directly
; (CPU word writes). Used ONCE at boot, under the coldstart forced blank (no NMI
; queue is running yet). VMAIN=$80 (+1 word). ~24 word writes.
; WIDTH-RISK: entry A16/I16. A8 for VMAIN; A16 for the word copy; exits A16/I16.
; =============================================================================
bar_buf_to_vram:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta $2115                   ; VMAIN: +1 word
    rep #$30
    .a16
    .i16
    lda #BAR_BUF_VRAM
    sta $2116                   ; VMADD = bar row, first bar column
    ldx #$0000                  ; X = byte offset into BAR_BUF (long,X)
@copy:
    .a16
    .i16
    lda f:BAR_BUF, x
    sta $2118                   ; word write -> +1 word (next cell)
    inx
    inx
    cpx #(BAR_LEN * 2)
    bcc @copy
    rts

; =============================================================================
; bar_enqueue — enqueue a GP-DMA of BAR_BUF (48 bytes) -> the BG3 tilemap in
; VRAM on the engine VBlank DMA queue (the kit-idiomatic path). No forced blank:
; the DMA runs during the NEXT VBlank (NMI Phase 3, before any tilemap/stream
; DMA), so the ~24-word write lands with the port stable. We set VMAIN ($2115)
; and VMADD ($2116) in the main loop here; the GP-DMA queue drain does NOT touch
; them (it only sets DMAP/BBAD/src/size on CH0), and nothing between here and the
; NMI writes $2115/$2116 (mode7_tick builds tables in WRAM; sf_frame_end runs
; audio/fade only), so they hold to the drain — the same shadow-then-DMA idiom
; sf_fx.inc uses for CGRAM (it sets $2121 then queues a $2122 DMA). DMAP=$01
; (pair mode: write $2118 then $2119), BBAD=$18 (VMDATAL), priority 1 (never
; dropped — behind OAM).
; WIDTH-RISK: entry A16/I16, DB=$00. A8 for VMAIN + the DMA_STAGE byte fields;
; A16 for VMADD + the word fields + the jsr; exits A16/I16.
; =============================================================================
bar_enqueue:
    .a16
    .i16
    sep #$20
    .a8
    lda #$80
    sta $2115                   ; VMAIN: +1 word (holds to the VBlank drain)
    rep #$20
    .a16
    lda #BAR_BUF_VRAM
    sta $2116                   ; VMADD = bar row dest (holds to the VBlank drain)
    sep #$20
    .a8
    lda #$01
    sta DMA_STAGE_PRIORITY      ; priority 1 (behind OAM; never budget-dropped)
    lda #$01
    sta DMA_STAGE_DMAP          ; DMAP $01: pair mode ($2118 then $2119), src+1
    lda #$18
    sta DMA_STAGE_BBAD          ; dest $2118 (VMDATAL) — VMADD supplies the addr
    lda #^BAR_BUF
    sta DMA_STAGE_SRC_BANK      ; BAR_BUF bank ($7E)
    rep #$20
    .a16
    lda #.loword(BAR_BUF)
    sta DMA_STAGE_SRC_LO        ; src low 16 bits
    lda #(BAR_LEN * 2)
    sta DMA_STAGE_SIZE          ; 48 bytes = 24 tilemap words
    jsr dma_queue_add           ; enqueue on the VBlank queue (needs A16/I16)
    .a16
    .i16
    rts

; =============================================================================
; Engine includes — the documented sf_mode7.inc link-partner order, plus the
; DMA + colour-math engines the macros need, and the input handler for btn.
; =============================================================================
.include "sprite_engine.asm"
.include "dma_scheduler.asm"
.include "input_handler.asm"

mode7_sin_lut:
    .include "mode7_sin_lut.inc"
.include "hdma_alloc.asm"
.include "hdma_engine.asm"
.include "hdma_color_engine.asm"
.include "colormath_engine.asm"
.include "palette_engine.asm"
.include "mode7_math.asm"

.segment "RODATA"
.include "mode7_pv_ztable.inc"

.segment "CODE"
.include "mode7_hdma.asm"
.include "mode7_engine.asm"

; --- first-party data: the instrument-band CHR + palette, the floor palette ---
.segment "RODATA"
.include "assets/dash_chr.inc"
.include "assets/dash_palette.inc"
.include "assets/floor_palette.inc"

; --- the 32KB interleaved Mode-7 floor-map blob (bank 1 of the 64KB image) ---
.segment "BANK1"
floor_map:
    .incbin "assets/floor_map.bin"
