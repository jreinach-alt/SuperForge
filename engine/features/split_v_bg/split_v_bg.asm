; =============================================================================
; split_v_bg.asm — the seamless vertical dual-camera stage (BG1 + BG2 + BG3)
; =============================================================================
; BG1 and BG2 render the SAME stage bytes at two different scroll offsets, and
; PPU window 1 shows BG1 left of the seam and BG2 right of it. Diverge the two
; scrolls and the view splits; converge them and the halves become pixel-
; identical and the seam vanishes. That is the whole mechanism — no HDMA, no
; mid-scanline writes, three CPU byte writes a frame.
;
; ONE COPY OF THE STAGE. BG1SC and BG2SC both point at ES_V_STAGE_MAP and both
; BG12NBA nibbles carry ES_V_STAGE_CHR_NBA. Duplicating CHR+tilemap into each
; layer's own region is the obvious reading of a two-camera split, and it is
; not needed: the split is purely camera scroll over one copy.
;
; BG3 carries the divider: its tilemap is filled with the bevel tile, and
; window 2 — a band of half-width hw about the seam — is the only place BG3 is
; shown. Hw ramps from zero, so at merge the bar occupies no screen at all.
;
; Every base comes from the allocator's emitted encoding. Nothing here does
; mask arithmetic on a register value.

; The enter-time GP-DMA register file, addressed through the channel the sv_up
; dma_init claim names — a declared resource, not a hard-coded 0.
SV_REGS = $4300 + ES_D_SV_UP_CH * 16

; The seam is fixed at the screen centre: the cameras move, not the seam. A
; moving seam would make the merge non-identical (the two halves would sample
; the stage at different screen columns), which is the property this rail is
; built to demonstrate.
SV_CENTRE = 128

; The BG3 tilemap ENTRY the divider column is drawn from. A tilemap word is not
; a bare tile number: bits 0-9 are the tile, bits 10-12 the PALETTE, 13
; priority, 14/15 the flips. All of it is tile-space, not address-space, so
; no_literals has nothing to object to.
;
; THE PALETTE FIELD IS LOAD-BEARING and was omitted at first. BG3 is 2bpp, so
; its palette N is CGRAM words 4N..4N+3 and the bevel's claim sits at 8..11 —
; palette 2. Writing a bare tile number selects palette 0, i.e. CGRAM 0..3,
; which is the STAGE's sky/outline/dirt/grass. The bar then still renders, in
; muddy stage tones, and every "the divider is present" assertion still passes
; — it is only wrong against the neutral grey bevel the divider is supposed to
; be, which no byte assertion catches and a side-by-side render does.
SV_BEVEL_PALNO = 2
SV_BEVEL_TILE  = (SV_BEVEL_PALNO << 10) | 0

; Window-select fields, per layer nibble of W12SEL/W34SEL. Bit0 = invert (mask
; OUTSIDE rather than inside), bit1 = enable, and the window-2 field is the
; same two bits shifted left by 2.
SV_W1_INSIDE  = $02
SV_W1_OUTSIDE = $03
SV_W2_INSIDE  = $08
SV_W2_OUTSIDE = $0C

; --- sv_up: one VRAM upload. VMADD must already be set by the caller -------
; In: A16/I16, DB=0, forced blank. X = source addr, Y = byte count,
;  ES_ESCR+0 = source bank (byte). Clobbers A, X, Y.
; DAS is single-shot — consumed by the transfer — so it is re-armed HERE, per
; call, giving exactly one arming site that cannot be forgotten (room_bg's
; reasoning). Arm it once outside a multi-slot loop and only the first
; transfer moves bytes.
sv_up:
    .a16
    .i16
    stx a:SV_REGS + 2               ; A1T
    sty a:SV_REGS + 5               ; DAS (re-armed for THIS transfer)
    sep #$20
    .a8
    lda z:ES_ESCR + 0
    sta a:SV_REGS + 4               ; A1B
    lda #ES_D_SV_UP_DMAP
    sta a:SV_REGS + 0               ; DMAP: A->B, 2 regs write-once
    lda #ES_D_SV_UP_BBAD
    sta a:SV_REGS + 1               ; BBAD: VMDATAL
    lda #(1 << ES_D_SV_UP_CH)
    sta a:$420B                     ; fire (enter-time: channel regs free)
    rep #$20
    .a16
    rts

; Palette uploads are written inline at each site rather than factored into a
; routine: the loop bound is a different assemble-time constant per palette, so
; a shared routine would need a runtime count — i.e. A WRAM cell, which in this
; repo is a CLAIM. Room_bg inlines them for the same reason. `SV_PAL_UP` keeps
; the duplication honest without inventing state.
;
; WIDTH-RISK: entered A16/I16, toggles A8 for the two byte stores per word and
; restores A16 before the loop test. X is the caller's source index and must
; arrive zeroed; the macro leaves it at `size`.
.macro SV_PAL_UP sv_at, sv_blob, sv_size
    .local loop
    sep #$20
    .a8
    lda #sv_at
    sta a:$2121                     ; CGADD = the claim's base word
    rep #$20
    .a16
    ldx #0
loop:
    lda f:sv_blob, x                ; long: the blob's bank is the linker's
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #sv_size
    bcc loop
.endmacro

; --- sv_arm: uploads + BG1/BG2/BG3 registers + the window recipe -----------
; CONTRACT sv_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the uploads, the BG1/BG2/BG3 registers and the window recipe
;   clobbers: A, X, Y, N, Z
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract. Everything here is written once, at enter
;   tail:     rts
;
; Forced blank alone does NOT mask NMI — the enter contract does both, which is
; what makes these long CPU-side VRAM writes safe. Under forced blank alone,
; an NMI landing mid-upload re-points VMADD and the rest of the transfer lands
; somewhere else in VRAM.
sv_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "sv_arm"
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    ; ---- stage CHR -------------------------------------------------------
    sep #$20
    .a8
    lda #^sv_stage_chr_bin
    sta z:ES_ESCR + 0
    rep #$20
    .a16
    lda #ES_V_STAGE_CHR
    sta a:$2116
    ldx #.loword(sv_stage_chr_bin)
    ldy #ES_R_SV_STAGE_CHR_SIZE
    jsr sv_up
    ; ---- the shared stage tilemap (BOTH cameras read this one copy) ------
    sep #$20
    .a8
    lda #^sv_stage_map_bin
    sta z:ES_ESCR + 0
    rep #$20
    .a16
    lda #ES_V_STAGE_MAP
    sta a:$2116
    ldx #.loword(sv_stage_map_bin)
    ldy #ES_R_SV_STAGE_MAP_SIZE
    jsr sv_up
    ; ---- bevel CHR -------------------------------------------------------
    sep #$20
    .a8
    lda #^sv_bevel_chr_bin
    sta z:ES_ESCR + 0
    rep #$20
    .a16
    lda #ES_V_BEVEL_CHR
    sta a:$2116
    ldx #.loword(sv_bevel_chr_bin)
    ldy #ES_R_SV_BEVEL_CHR_SIZE
    jsr sv_up
    jsr sv_fill_bevel_map
    ; ---- palettes --------------------------------------------------------
    SV_PAL_UP ES_C_STAGE_PAL, sv_stage_pal_bin, ES_R_SV_STAGE_PAL_SIZE
    SV_PAL_UP ES_C_BEVEL_PAL, sv_bevel_pal_bin, ES_R_SV_BEVEL_PAL_SIZE
    jsr sv_bg_regs
    jsr sv_window_arm
    rts

; --- sv_fill_bevel_map: BG3's tilemap is uniformly the bevel tile ----------
; In/out: A16/I16, DB=0, forced blank. Clobbers A, X. No ROM blob for this:
; 1024 identical words is 2 KB of ROM to say one number. The BAR's shape comes
; from window 2, not from the tilemap — BG3 is drawn everywhere and shown only
; inside the band.
sv_fill_bevel_map:
    .a16
    .i16
    lda #ES_V_BEVEL_MAP
    sta a:$2116                     ; VMADD
    ldx #ES_V_BEVEL_MAP_WORDS
@loop:
    .a16
    .i16
    lda #SV_BEVEL_TILE
    sta a:$2118                     ; VMDATAL+H (word port, VMAIN +1 word)
    dex
    bne @loop
    rts

; --- sv_bg_regs: the three layers' bases -----------------------------------
; In/out: A16/I16, DB=0, forced blank. Clobbers A.
sv_bg_regs:
    .a16
    .i16
    sep #$20
    .a8
    ; BG1SC and BG2SC BOTH name the ONE stage map. This single pair of writes
    ; is the entire reason the split costs one copy of the stage instead of
    ; two, and it is what makes a merged view pixel-identical rather than
    ; merely similar: the two halves are literally the same bytes.
    lda #ES_V_STAGE_MAP_SC_BASE
    sta a:$2107                     ; BG1SC (32x32)
    sta a:$2108                     ; BG2SC — same base, deliberately
    lda #ES_V_BEVEL_MAP_SC_BASE
    sta a:$2109                     ; BG3SC
    ; ...and both BG12NBA nibbles name the ONE stage CHR page.
    lda #(ES_V_STAGE_CHR_NBA | (ES_V_STAGE_CHR_NBA << 4))
    sta a:$210B                     ; BG12NBA: BG1 low nibble, BG2 high
    lda #ES_V_BEVEL_CHR_NBA
    sta a:$210C                     ; BG34NBA: BG3 low nibble
    ; Vertical scroll is pinned: the arena is one screen tall. A scene must not
    ; inherit whatever the previous one left in these write-twice latches.
    stz a:$210E                     ; BG1VOFS
    stz a:$210E
    stz a:$2110                     ; BG2VOFS
    stz a:$2110
    stz a:$2112                     ; BG3VOFS
    stz a:$2112
    ; BG3 horizontal is pinned too: the bar's position is the WINDOW's, not the
    ; layer's. Scrolling BG3 would slide the bevel out of its own band.
    stz a:$2111                     ; BG3HOFS
    stz a:$2111
    rep #$20
    .a16
    rts

; --- sv_window_arm: the static half of the window recipe -------------------
; In/out: A16/I16, DB=0, forced blank. Clobbers A.
;
; Window 1 = [seam, 255]: BG1 hidden INSIDE it (so BG1 shows left), BG2 hidden
; OUTSIDE it (so BG2 shows right). Window 2 = the divider band about the seam,
; and BG3 is hidden OUTSIDE it — the bar exists only in the band.
;
; NOTE the BG3 polarity is the opposite of the usual seam recipe, which masks
; BG1+BG2+BG3 *inside* the band so the CGRAM-0 BACKDROP shows through as a
; flat seam colour. This rail draws a real 3-tone bevel on BG3, so BG3 must be
; VISIBLE inside the band and hidden everywhere else.
sv_window_arm:
    .a16
    .i16
    sep #$20
    .a8
    ; W12SEL: BG1 = win1-inside | win2-inside ($0A)
    ;  BG2 = win1-outside | win2-inside ($0B), high nibble
    ; The win2 term on BOTH is load-bearing and is easy to leave out: without
    ; it BG1/BG2 still cover the band, and since BG3 is the LOWEST priority
    ; layer in Mode 1, the bevel would be hidden behind the opaque floor and
    ; visible only against the transparent sky — a bar that stops at the
    ; horizon. Masking both inside the band cuts a full-height channel for it.
    lda #(SV_W1_INSIDE | SV_W2_INSIDE | ((SV_W1_OUTSIDE | SV_W2_INSIDE) << 4))
    sta a:$2123
    ; W34SEL: BG3 = win2-OUTSIDE, i.e. Hidden everywhere except the band. This
    ; is the OPPOSITE polarity to the usual seam recipe, which masks BG3
    ; *inside* the band so the CGRAM-0 backdrop shows through as a flat
    ; colour. A real bevel is drawn there, so BG3 must survive inside it.
    lda #SV_W2_OUTSIDE
    sta a:$2124
    stz a:$2125                     ; WOBJSEL: OBJ unwindowed — the fighters
                                    ; must cross the seam intact (clipping OBJ
                                    ; at the seam is svd_obj's mode, not this
                                    ; rail's)
    stz a:$212A                     ; WBGLOG: all-OR, combining win1 and win2
    lda #$07                        ; TMW: window-mask BG1|BG2|BG3 on main
    sta a:$212E
    stz a:$212F                     ; TSW: no subscreen windowing
    rep #$20
    .a16
    rts

; --- sv_vblank: the two cameras and the divider band, committed ------------
; CONTRACT sv_vblank
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   out:      both cameras and the divider band committed
;   clobbers: A, X, Y, N, Z, C, V
;   assumes:  VBlank, from the rail's sm_nmi_hook, in that hook's A8/I16
;             convention
;   tail:     rts
;
; BOTH CAMERAS AND THE BAND FROM ONE SHADOW, IN ONE PLACE. Cam A, cam B and the
; band half-width are all derived from ES_SV_MID and ES_SV_SPREAD in the same
; VBlank, so they cannot disagree about where the seam is — the same discipline
; platformer_bg applies to its foreground and sky.
;
; The seam itself never moves: it is SV_CENTRE. Only the cameras diverge.
sv_vblank:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "sv_vblank"
    rep #$20
    .a16
    ; ---- cam A = mid - spread, cam B = mid + spread ----------------------
    ; Masked to a byte: the stage map is 256 px periodic, so mod-256 IS the
    ; correct screen mapping and a negative camera wraps rather than clamps.
    ; Both cameras are carried in INDEX registers, not on the stack. A PHA in
    ; A16 pushes 2 bytes and a PLA in A8 pops 1, so staging one of them across
    ; the width toggle would drift SP by a byte every frame — the documented
    ; A8/A16 stack-balance class, and it would present as the NMI returning to
    ; garbage minutes after boot rather than as anything near this code.
    lda z:ES_SV_MID
    sec
    sbc z:ES_SV_SPREAD
    and #$00FF
    tax                             ; X = cam A
    lda z:ES_SV_MID
    clc
    adc z:ES_SV_SPREAD
    and #$00FF
    tay                             ; Y = cam B
    ; ---- BG1HOFS = cam A, BG2HOFS = cam B (write-twice latches) ----------
    sep #$20
    .a8
    txa                             ; A8 + I16: transfers X's low byte
    sta a:$210D                     ; BG1HOFS low
    stz a:$210D                     ; high — both cameras are 0..255
    tya
    sta a:$210F                     ; BG2HOFS low
    stz a:$210F
    rep #$20
    .a16
    jsr sv_band
    sep #$20
    .a8
    rts

; --- sv_band: window 1's edge and window 2's band, from the spread ---------
; In/out: A16/I16, DB=0. Clobbers A, X.
;
; Window 1 is [SV_CENTRE, 255] — constant, but rewritten every frame anyway so
; the scene cannot inherit a stale edge from whatever ran before it.
;
; Window 2 is the divider band, [centre-hw, centre+hw], with hw = spread >> 4.
; THE EMPTY-BAND CASE IS THE SEAMLESS PROPERTY. At hw = 0 the band is written
; INVERTED — left edge 1, right edge 0 — and the PPU treats a range whose left
; exceeds its right as an inactive window. That is what lets the divider ramp
; out of existence instead of collapsing to a 1px sliver: at merge there is no
; band at all, so BG1/BG2 are unmasked across the whole screen and the two
; halves compose into one picture.
sv_band:
    .a16
    .i16
    sep #$20
    .a8
    lda #SV_CENTRE
    sta a:$2126                     ; WH0: window-1 left = the seam
    lda #255
    sta a:$2127                     ; WH1: window-1 right = screen edge
    rep #$20
    .a16
    lda z:ES_SV_SPREAD
    lsr a
    lsr a
    lsr a
    lsr a                           ; hw = spread >> 4
    and #$00FF
    beq @empty
    tax                             ; X holds hw across the width toggles —
                                    ; not the stack, for sv_vblank's reason
    ; right edge = centre + hw
    clc
    adc #SV_CENTRE
    sep #$20
    .a8
    sta a:$2129                     ; WH3
    rep #$20
    .a16
    ; left edge = centre - hw, via two's complement (there is no 16-bit
    ; reverse-subtract, and reloading centre would cost the same)
    txa
    eor #$FFFF
    inc a                           ; A = -hw
    clc
    adc #SV_CENTRE
    sep #$20
    .a8
    sta a:$2128                     ; WH2
    rep #$20
    .a16
    rts
@empty:
    .a16
    .i16
    sep #$20
    .a8
    lda #1
    sta a:$2128                     ; WH2 left = 1
    stz a:$2129                     ; WH3 right = 0  -> left > right, inactive
    rep #$20
    .a16
    rts
