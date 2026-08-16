; =============================================================================
; split_band.asm — static band tables: Mode-1 HUD rows over the Mode-7 floor
; =============================================================================
; Fixed camera height makes the split static: lines 0..HUD_LINES-1 run
; Mode 1 showing BG3 (the HUD), the rest run Mode 7 showing BG1 (the floor).
; Direct BGMODE table + indirect TM table, both ROM-resident — zero CPU, zero
; WRAM, re-armed each VBlank from the scene_mgr shadow.
;
; THE BINDING CONTRACT. This feature carries NO defaults: the includer supplies
; five
; symbols and each missing one is a named `.error` rather than a silent
; fallback. That is what makes ONE splitter serve two rails with different band
; values — docs/09 finding B1's answer ("do not build a second splitter;
; generalise split_band's hardcoded table") taken literally, with the claim set
; untouched.
;
;  SB_LINES the seam: lines 0..SB_LINES-1 are the top band
;  SB_MODE_TOP BGMODE for the top band
;  SB_MODE_BOT BGMODE from the seam on (the register HOLDS past the table)
;  SB_TM_TOP TM for the top band
;  SB_TM_BOT TM from the seam on
;
; THE FOUR LIVE BINDINGS, and why they differ — which is the whole point. KEEP
; THIS LIST CURRENT WHEN A RAIL BINDS THIS FEATURE: it said "the two live
; bindings" through `racer` and into `mode7_chamber`, and both of those rails'
; own docs then repeated the stale count from here — the audit record The
; census is one command: the rails that BIND are the ones naming split_band in
; game.toml's `features = [...]`, not the several that only discuss it in
; comments.
;
;  microzero/race SB_LINES = HUD_LINES (44), $09/$07, $16/$11. The top band
;  shows BG2 (sky_band's ramp) + BG3 (the HUD) + OBJ; the
;  floor band shows BG1 + OBJ (the car).
;  split_h_demo SB_LINES = HUD_LINES (40), $09/$07, $04/$01. That rail has
;  no sky BG2 and no OBJ at all, so its top band is BG3 ALONE
;  over a BG1-alone floor. A hardcoded $16/$11 would enable
;  two layers with no content in them, and the picture the
;  test reads would be of the wrong composition.
;  racer SB_LINES = HUD_LINES (44), $09/$07, $12/$11. No BG3 in the
;  top band at all — Mode 7 has one BG plus OBJ, so there is
;  no text renderer to give a canvas to and the sky band is
;  BG2 (sky_band's ramp) + OBJ (the speed bar).
;  mode7_chamber SB_LINES = MB_SEAM (32), $09/$07, $00/$01. TM_TOP is
;  NOTHING: the band is the backdrop alone. This rail
;  composes no OBJ feature, so enabling OBJ would put
;  POWER-ON OAM GARBAGE on screen. The one binding that
;  turns a layer OFF, and it is only expressible because
;  the contract has no defaults.
.ifndef SB_LINES
    .error "split_band: SB_LINES undefined -- the includer must bind the seam scanline (see split_band.asm's binding contract)"
.endif
.ifndef SB_MODE_TOP
    .error "split_band: SB_MODE_TOP undefined -- the includer must bind the top band's BGMODE byte"
.endif
.ifndef SB_MODE_BOT
    .error "split_band: SB_MODE_BOT undefined -- the includer must bind the bottom band's BGMODE byte"
.endif
.ifndef SB_TM_TOP
    .error "split_band: SB_TM_TOP undefined -- the includer must bind the top band's TM byte"
.endif
.ifndef SB_TM_BOT
    .error "split_band: SB_TM_BOT undefined -- the includer must bind the bottom band's TM byte"
.endif
; The seam has to land inside the frame with a line left for the second entry;
; a table whose counts sum past 224 parks its final entry outside the frame
; (see the alignment note below, which was written by the audit that measured
; it).
.assert SB_LINES > 0 && SB_LINES < 224, error, "split_band: SB_LINES must be 1..223"

; HDMA line alignment, MEASURED. A table unit whose cumulative line index is K
; is visible at exactly scanline K. HdmaInit runs at scanline 0 clock 12 and
; the unit transferred on the PRE-RENDER line covers the first visible line, so
; the first entry covers scanline 0 and no table needs to close the frame.
; These two tables therefore cover 0..43 and 44..223 as written.
;
; An earlier version of this note claimed a "known artifact": that scanline 0
; rendered black because the tables ran out and the registers kept their last
; values.
; That artifact DOES NOT EXIST — the frame has 224 non-black content rows and
; the "black line" was a screenshot-anchor error in the test fixture. The note
; also recorded a failed experiment (a one-line entry appended to re-latch the
; sky for the wrap, which landed on scanline 223) as evidence of an unexplained
; offset. It is explained: those pre-final counts summed to 223, so the final
; entry's cumulative index WAS 223. Summing to 224 parks it past the frame.
; There was never an inconsistency, only a bad anchor.

sb_bgmode_tab:                      ; direct: [count, value] ... [0]
    .byte SB_LINES, SB_MODE_TOP     ; the top band's video mode
    .byte 1, SB_MODE_BOT            ; from here on (the register HOLDS)
    .byte 0
sb_tm_tab:                          ; indirect: [count, ptr] ... [0]
    .byte SB_LINES
    .word sb_tm_hud
    .byte 1
    .word sb_tm_m7
    .byte 0
sb_tm_hud: .byte SB_TM_TOP          ; TM: the top band's enabled layers
sb_tm_m7:  .byte SB_TM_BOT          ; TM: the bottom band's enabled layers
