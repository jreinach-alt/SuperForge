; =============================================================================
; svd_bg.asm — the vertical window dual-view: one stage, two cameras, one seam
; =============================================================================
; BG1 and BG2 render the SAME stage bytes at two different scroll offsets, and
; PPU window 1 shows BG1 left of the seam and BG2 right of it. Window 2 is a
; thin band about the seam that masks BOTH, so what shows there is the BACKDROP
; — CGRAM word 0, authored white — and the seam bar costs zero sprites and zero
; tiles. That is the OPPOSITE polarity to split_v_bg's, which draws a real
; bevel on BG3 and therefore masks BG3 *outside* the band. BG3 here carries
; nothing and is off TM.
;
; ONE COPY OF THE STAGE. BG1SC and BG2SC both name ES_V_STAGE_MAP and both
; BG12NBA nibbles carry ES_V_STAGE_CHR_NBA, so the two cameras read one upload
; and only the scroll differs.'s header says the caller must duplicate
; CHR+tilemap per layer; its own shipping rail does not. The code is primary.
;
; ONE HDMA CHANNEL DRIVES ALL FOUR EDGES. WH0/WH1/WH2/WH3 are $2126..$2129 —
; four consecutive B-bus ports, which is exactly what DMAP mode 4 addresses
; from one BBAD. So a single 4-byte group per scanline carries the whole seam
; geometry, and the difference between a straight seam and a slanted one is
; only WHICH TABLE the channel reads:
;
;  straight ES_SVD_TAB, 11 B of WRAM, rebuilt every VBlank from the live
;  seam. Two NON-REPEAT entries ("one transfer, then idle N-1
;  lines"); the window registers HOLD through the idle lines, so
;  224 scanlines cost two groups rather than 224.
;  diagonal svd_diag_tab_bin, 899 B of ROM, 224 per-line groups, static —
;  the slant is built once, so there is nothing per-frame to
;  rebuild.
;
; The mode switch therefore repoints A1T/A1B in the scene_mgr HDMA shadow. It
; is NOT a mechanism switch, which is what keeps WH0..WH3 off this feature's
; `[[claims.reg]]` and out of a `seed = true` that would be untrue whenever the
; slant is off (feature.toml carries the full argument).
;
; Every base and every channel number comes from the allocator's emitted
; symbols. Nothing here does mask arithmetic on a register value.

; The enter-time GP-DMA register file, addressed through the channel the svd_up
; dma_init claim names — a declared resource, not a hard-coded 0.
SVD_REGS = $4300 + ES_D_SVD_UP_CH * 16

; The seam channel's slot in the 128-byte scene_mgr shadow the NMI MVNs to
; $4300 every armed frame. Same derivation, from the hdma claim's channel.
SVD_CH = ES_H_SVDW_CH * 16

SVD_BAND_HW = 6                 ; half the bar's width: the bar is 2*HW px

; The boot state.
SVD_CAM_A0 = 0
SVD_CAM_B0 = 192                ; frames the far side of the asymmetric world
SVD_SEAM0  = 128                ; screen centre

; Window-select fields, per layer nibble of W12SEL. Bit0 = invert (mask OUTSIDE
; rather than inside), bit1 = enable; the window-2 field is the same two bits
; shifted left by 2. Derived from Mesen2 Core/SNES/SnesPpu.cpp:1487-1498
; (ProcessWindowMaskSettings decodes each 2-bit field as bit1 = active, bit0 =
; inverted: 0/1 disabled, 2 inside, 3 outside), per AGENTS.md's standing
; practice.
SVD_W1_INSIDE  = $02
SVD_W1_OUTSIDE = $03
SVD_W2_INSIDE  = $08

; W12SEL: BG1 = win1-inside | win2-inside (hidden right of the seam AND in the
; band); BG2 = win1-outside | win2-inside (hidden left of it AND in the band).
; The win2 term on BOTH is what cuts the bar: without it the two layers cover
; the band between them and the backdrop never shows.
SVD_W12SEL_BG1 = SVD_W1_INSIDE | SVD_W2_INSIDE
SVD_W12SEL_BG2 = SVD_W1_OUTSIDE | SVD_W2_INSIDE
SVD_W12SEL = SVD_W12SEL_BG1 | (SVD_W12SEL_BG2 << 4)

; TMW: which layers the window masks on the main screen. BG1|BG2 always; the
; OBJ bit joins in the clip mode, and it is REQUIRED — WOBJSEL alone does
; nothing, because a BG/OBJ layer's window is gated by TMW
; (SnesPpu.cpp:980-981; only the colour-math window bypasses it).
SVD_TMW_BG     = $03
SVD_TMW_BG_OBJ = $13

; The seam modes. A STATE, cycled in both directions by the scene, so every
; teaching this rail carries is reachable from every other one in one binary.
SVD_MODE_STRAIGHT = 0           ; moving seam, OBJ crosses it intact
SVD_MODE_OBJCLIP  = 1           ; moving seam + OBJ confined to the left half
SVD_MODE_DIAG     = 2           ; the static slanted seam, from ROM
SVD_MODE_COUNT    = 3

; The straight table's two entry counts. 127 is the per-entry ceiling (the
; count field is 7 bits and $00 terminates), so the screen's 224 lines take two
; entries — window_iris's split, for the same hardware reason.
SVD_RUN0 = 127
SVD_RUN1 = 97

; --- svd_up: one VRAM upload. VMADD must already be set by the caller -------
; In: A16/I16, DB=0, forced blank. X = source addr, Y = byte count,
;  A = source bank in the low byte. Clobbers A, X, Y.
; DAS is single-shot — consumed by the transfer — so it is re-armed HERE, per
; call: one arming site is the only shape a caller cannot forget.
svd_up:
    .a16
    .i16
    stx a:SVD_REGS + 2              ; A1T
    sty a:SVD_REGS + 5              ; DAS (re-armed for THIS transfer)
    sep #$20
    .a8
    sta a:SVD_REGS + 4              ; A1B — the bank byte the caller passed
    lda #ES_D_SVD_UP_DMAP
    sta a:SVD_REGS + 0              ; DMAP: A->B, 2 regs write-once (mode 1)
    lda #ES_D_SVD_UP_BBAD
    sta a:SVD_REGS + 1              ; BBAD: VMDATAL
    lda #(1 << ES_D_SVD_UP_CH)
    sta a:$420B                     ; fire (enter-time: channel regs are free)
    rep #$20
    .a16
    rts

; --- svd_arm: uploads, layer registers, the window recipe, the channel ------
; CONTRACT svd_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the uploads, the layer registers, the window recipe and the
;             seam channel
;   clobbers: A, X, Y, N, Z, C
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract. Everything here is written once, at enter
;   tail:     rts
;
; Forced blank alone does NOT mask NMI — the enter contract does both, which is
; what makes these CPU-side VRAM/CGRAM writes safe.
svd_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "svd_arm"
    ; ---- the live state, seeded before anything can read it --------------
    lda #SVD_CAM_A0
    sta z:ES_SVD_CAM + 0
    lda #SVD_CAM_B0
    sta z:ES_SVD_CAM + 2
    lda #SVD_SEAM0
    sta z:ES_SVD_CAM + 4
    lda #SVD_MODE_STRAIGHT
    sta z:ES_SVD_MODE
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: +1 word after the high byte
    rep #$20
    .a16
    ; ---- stage CHR: tile 0 empty, 1 sky, 2 grass, 3 mountain, 4 dirt -----
    lda #ES_V_STAGE_CHR
    sta a:$2116                     ; VMADD = the claim's word base
    ldx #.loword(svd_stage_chr_bin)
    ldy #ES_R_SVD_STAGE_CHR_SIZE
    lda #^svd_stage_chr_bin
    jsr svd_up
    ; ---- the shared stage tilemap (BOTH cameras read this one copy) ------
    lda #ES_V_STAGE_MAP
    sta a:$2116
    ldx #.loword(svd_stage_map_bin)
    ldy #ES_R_SVD_STAGE_MAP_SIZE
    lda #^svd_stage_map_bin
    jsr svd_up
    ; ---- BG palette 0, INCLUDING word 0 ----------------------------------
    ; Word 0 is colour 0 and the backdrop at once, and here that is not a
    ; formality: the seam bar IS word 0 showing through window 2.
    sep #$20
    .a8
    lda #ES_C_STAGE_PAL
    sta a:$2121                     ; CGADD = the claim base (word 0)
    rep #$20
    .a16
    ldx #0
:   lda f:svd_stage_pal_bin, x
    sep #$20
    .a8
    sta a:$2122                     ; low byte
    xba
    sta a:$2122                     ; high byte
    rep #$20
    .a16
    inx
    inx
    cpx #ES_R_SVD_STAGE_PAL_SIZE
    bcc :-
    jsr svd_bg_regs
.ifdef SVD_NOWIN
    ; ---- THE NON-VACUITY CONTROL (tools/build_svd_nowin.sh) --------------
    ; No window recipe and no seam channel: nothing is masked, so BG1 — the
    ; higher-priority layer in Mode 1, and opaque everywhere — fills the whole
    ; screen and the vertical split COLLAPSES. Every assertion about the two
    ; regions or the seam bar must FAIL on this build, which is what proves
    ; those assertions are about the WINDOW rather than about any picture with
    ; detail on both sides of x = 128.
    sep #$20
    .a8
    stz a:$2123                     ; W12SEL
    stz a:$2124                     ; W34SEL
    stz a:$2125                     ; WOBJSEL
    stz a:$212A                     ; WBGLOG
    stz a:$212E                     ; TMW: no layer window-masked
    stz a:$212F                     ; TSW
    rep #$20
    .a16
.else
    jsr svd_window_arm
    jsr svd_ch_arm
.endif
    rts

; --- svd_bg_regs: the two layers' bases, and the pinned vertical scroll -----
; In/out: A16/I16, DB=0, forced blank. Clobbers A.
svd_bg_regs:
    .a16
    .i16
    sep #$20
    .a8
    ; BG1SC and BG2SC BOTH name the ONE stage map. This single pair of writes
    ; is the entire reason the split costs one copy of the stage instead of two
    ; — one upload, two cameras.
    lda #ES_V_STAGE_MAP_SC_BASE
    sta a:$2107                     ; BG1SC (32x32)
    sta a:$2108                     ; BG2SC — same base, deliberately
    ; ...and both BG12NBA nibbles name the ONE stage CHR page (its `$22`).
    lda #(ES_V_STAGE_CHR_NBA | (ES_V_STAGE_CHR_NBA << 4))
    sta a:$210B                     ; BG12NBA: BG1 low nibble, BG2 high
    rep #$20
    .a16
    ; Vertical scroll is pinned for the rail's life: the stage is one screen
    ; tall and only the horizontal cameras move. −1 rather than 0 because
    ; scanline N shows tilemap line VOFS + N and the first ACTIVE scanline is
    ; 1, so −1 puts world row 0 on it (the correction every SuperForge BG
    ; feature carries; modular, so it needs no clamp).
    lda #0
    dec a
    sep #$20
    .a8
    sta a:$210E                     ; BG1VOFS, low
    xba
    sta a:$210E                     ; BG1VOFS, high
    rep #$20
    .a16
    lda #0
    dec a
    sep #$20
    .a8
    sta a:$2110                     ; BG2VOFS, low
    xba
    sta a:$2110                     ; BG2VOFS, high
    rep #$20
    .a16
    rts

; --- svd_window_arm: the static half of the window recipe -------------------
; In/out: A16/I16, DB=0, forced blank. Clobbers A. The four EDGE registers are
; not here: they are the HDMA channel's, every scanline of every frame. What is
; here is which layers each window applies to, how the two windows combine, and
; which of them mask the main screen.
svd_window_arm:
    .a16
    .i16
    sep #$20
    .a8
    lda #SVD_W12SEL
    sta a:$2123                     ; W12SEL
    stz a:$2124                     ; W34SEL: BG3/BG4 unwindowed — neither is
                                    ; on the main screen, and a window term for
                                    ; a layer TM does not show is a write with
                                    ; no effect
    stz a:$212A                     ; WBGLOG: all-OR, combining win1 and win2
    stz a:$212F                     ; TSW: no subscreen windowing
    rep #$20
    .a16
    rts

; --- svd_ch_arm: the seam channel's fixed shadow fields (scene enter) -------
; In/out: A16/I16, DB=0. Clobbers A, X. DMAP and BBAD never change; A1T/A1B are
; the MODE, and svd_mode_apply owns them from the first armed VBlank onward.
; The straight table is built here too, so the channel has a valid source
; before HDMAEN is ever set — the svd_tab claim's write-before-read contract,
; discharged.
svd_ch_arm:
    .a16
    .i16
    sep #$20
    .a8
    ldx #SVD_CH
    lda #ES_H_SVDW_DMAP
    sta f:ES_SM_HDMA_LONG + 0, x    ; DMAP: direct, mode 4 (4 regs write once)
    lda #ES_H_SVDW_BBAD
    sta f:ES_SM_HDMA_LONG + 1, x    ; BBAD: WH0 (mode 4 reaches WH1/WH2/WH3)
    jsr svd_seam_table
    jsr svd_mode_apply
    rep #$20
    .a16
    rts

; --- svd_seam_table: the STRAIGHT seam's 11-byte table ----------------------
; In/out: A8/I16, DB=0. Clobbers A, X.
;
;  +0 127 non-repeat: ONE 4-byte group, then 126 idle lines
;  +1..+4 WH0 = seam, WH1 = 255, WH2 = seam - hw, WH3 = seam + hw
;  +5 97 non-repeat: one group, then 96 idle lines (127 + 97 = 224)
;  +6..+9 the same four bytes
;  +10 0 terminator
;
; Rebuilt every VBlank, unconditionally — including while the DIAGONAL mode has
; the channel pointed at ROM. Eight byte writes buy the property that the table
; is always current, so switching back is a pointer change and never a frame of
; stale geometry.
svd_seam_table:
    .a8
    .i16
    ldx #0
    lda #SVD_RUN0
    sta f:ES_SVD_TAB_LONG + 0, x
    lda #SVD_RUN1
    sta f:ES_SVD_TAB_LONG + 5, x
    lda z:ES_SVD_CAM + 4            ; the seam, low byte (it is 0..255)
    sta f:ES_SVD_TAB_LONG + 1, x    ; WH0: window 1's left edge
    sta f:ES_SVD_TAB_LONG + 6, x
    lda #255
    sta f:ES_SVD_TAB_LONG + 2, x    ; WH1: window 1's right edge = screen edge
    sta f:ES_SVD_TAB_LONG + 7, x
    lda z:ES_SVD_CAM + 4
    sec
    sbc #SVD_BAND_HW
    sta f:ES_SVD_TAB_LONG + 3, x    ; WH2: the band's left edge
    sta f:ES_SVD_TAB_LONG + 8, x
    lda z:ES_SVD_CAM + 4
    clc
    adc #SVD_BAND_HW
    sta f:ES_SVD_TAB_LONG + 4, x    ; WH3: the band's right edge
    sta f:ES_SVD_TAB_LONG + 9, x
    lda #0
    sta f:ES_SVD_TAB_LONG + 10, x   ; terminator
    rts

; --- svd_mode_apply: the three mode-dependent decisions ---------------------
; In/out: A8/I16, DB=0. Clobbers A, X.
;
; Run unconditionally every VBlank rather than on a dirty flag: it is a dozen
; byte writes, and a dirty flag is persistent state whose power-on value would
; have to be seeded and whose staleness would present as "the mode changed but
; the screen did not" — a bug several frames from its cause.
svd_mode_apply:
    .a8
    .i16
    lda z:ES_SVD_MODE
    cmp #SVD_MODE_DIAG
    beq @diag
    cmp #SVD_MODE_OBJCLIP
    beq @clip
    ; ---- straight: OBJ unwindowed, so a marker crosses the seam intact ----
    .a8
    stz a:$2125                     ; WOBJSEL
    lda #SVD_TMW_BG
    sta a:$212E                     ; TMW: BG1|BG2
    bra @wram_tab
@clip:
    ; ---- per-half OBJ clipping: OBJ hidden INSIDE window 1, i.e. right of
    ;  the seam. The marker straddling it is CUT; the one in the right
    ;  half vanishes. Both are picture-only facts — the OAM entries are
    ;  byte-identical to the straight mode's.
    .a8
    .i16
    lda #SVD_W1_INSIDE
    sta a:$2125                     ; WOBJSEL
    lda #SVD_TMW_BG_OBJ
    sta a:$212E                     ; TMW: BG1|BG2|OBJ — WOBJSEL is inert
                                    ; without the OBJ bit here
@wram_tab:
    ; ---- the channel reads the 11-byte WRAM table (a STRAIGHT seam) -------
    .a8
    .i16
    ldx #SVD_CH
    lda #ES_SVD_TAB_BANK
    sta f:ES_SM_HDMA_LONG + 4, x    ; A1B
    rep #$20
    .a16
    lda #ES_SVD_TAB
    sta f:ES_SM_HDMA_LONG + 2, x    ; A1T
    sep #$20
    .a8
    rts
@diag:
    ; ---- the channel reads the static ROM table (a SLANTED seam) ---------
    .a8
    .i16
    stz a:$2125                     ; WOBJSEL: OBJ crosses the slant intact
    lda #SVD_TMW_BG
    sta a:$212E                     ; TMW: BG1|BG2
    ldx #SVD_CH
    lda #^svd_diag_tab_bin
    sta f:ES_SM_HDMA_LONG + 4, x    ; A1B — the blob's linker bank
    rep #$20
    .a16
    lda #.loword(svd_diag_tab_bin)
    sta f:ES_SM_HDMA_LONG + 2, x    ; A1T
    sep #$20
    .a8
    rts

; --- svd_nmi_commit: the two cameras, the seam, the mode -------------------
; CONTRACT svd_nmi_commit
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   out:      the two cameras, the seam and the mode committed
;   clobbers: A, X, N, Z
;   assumes:  VBlank, from the rail's sm_nmi_hook, in that hook's A8/I16
;             convention
;   tail:     rts
;
; BOTH CAMERAS AND THE SEAM FROM ONE PLACE, in one VBlank, so they cannot
; disagree about the frame they describe. BG1HOFS/BG2HOFS are write-twice 8-bit
; latches; both cameras are masked to a byte by the scene, because the stage
; map is 256 px periodic and mod-256 IS the correct screen mapping.
;
; WIDTH-RISK: entered A8/I16 and MUST return A8/I16. Svd_seam_table and
; svd_mode_apply are both A8/I16 in and out; svd_mode_apply toggles A16 for its
; two 16-bit A1T stores and narrows back on every arm.
svd_nmi_commit:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "svd_nmi_commit"
    lda z:ES_SVD_CAM + 0
    sta a:$210D                     ; BG1HOFS, low  (camera A — the left half)
    lda z:ES_SVD_CAM + 1
    sta a:$210D                     ; BG1HOFS, high
    lda z:ES_SVD_CAM + 2
    sta a:$210F                     ; BG2HOFS, low  (camera B — the right half)
    lda z:ES_SVD_CAM + 3
    sta a:$210F                     ; BG2HOFS, high
.ifndef SVD_NOWIN
    jsr svd_seam_table
    jsr svd_mode_apply
.endif
    rts

; --- svd_disarm: put the window and the seam channel back (scene exit) ------
; CONTRACT svd_disarm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the window and the seam channel put back for the next scene
;   clobbers: A, N, Z
;   assumes:  forced blank, at scene exit
;   tail:     rts
;
; A single-scene rail still disarms: a window mask left over a screen this
; scene no longer owns dims or hides layers a later scene never asked about,
; through registers it has no reason to look at (window_iris's wi_disarm, same
; argument). Clearing the HDMAEN shadow bit is the other half — an armed
; channel whose table this scene owned would keep streaming into WH0..WH3.
svd_disarm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "svd_disarm"
    sep #$20
    .a8
    stz a:$212E                     ; TMW: no layer window-masked
    stz a:$2123                     ; W12SEL
    stz a:$2124                     ; W34SEL
    stz a:$2125                     ; WOBJSEL
    lda z:ES_SM_NMI+2
    and #(255 ^ (1 << ES_H_SVDW_CH))
    sta z:ES_SM_NMI+2               ; the seam channel, disarmed
    rep #$20
    .a16
    rts
