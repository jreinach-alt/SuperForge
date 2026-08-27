; =============================================================================
; haze.asm — heat shimmer: a per-scanline BG1VOFS displacement
; =============================================================================
; THE WHOLE PER-FRAME COST OF THIS EFFECT IS ONE 8-BIT STORE. hz_rom holds 32
; complete HDMA tables at a 256 B stride, so phase p lives at
; hz_warp_bin + (p << 8) — the low byte of the address never changes, and
; advancing the animation is a single write to the channel's A1T HIGH byte in
; the VBlank hook.
;
; The alternative is rebuilding the table every frame. platformer_bg prices
; that shape at ~16 cycles an entry (platformer_bg.asm:386); over this rail's
; 104-line band that is ~1,700 CPU cycles a frame out of the ~28-37k a whole
; frame gets, spent re-deriving a picture that is already in ROM.
;
; WHAT IS NOT HERE: no haze TILES. The distortion is a table, not artwork —
; feature.toml and game.toml both say why at length. The art this bends is
; `hz_bg`'s ordinary desert, unmodified.
;
; WIDTH-RISK: `hz_nmi_commit` runs from the rail's sm_nmi_hook in that hook's
; A8/I16 and must leave it that way; the other two are the main thread's
; A16/I16. Every entry point declares a contract, so the lint's contract pass
; checks the cross-file call sites rather than trusting these comments.

; The channel's slot in scene_mgr's HDMA shadow, addressed through the channel
; the `hzwarp` claim was given — a declared resource, not a hard-coded 0.
; sm_nmi_core MVNs the whole 128-byte block to $4300 on every armed frame,
; AFTER sm_nmi_hook runs (scene_mgr.asm:407 then :415), so a write here in the
; hook reaches the hardware on the same frame.
HZ_SLOT = ES_SM_HDMA_LONG + ES_H_HZWARP_CH * 16

; The 32 phases must not straddle a bank: HDMA increments A1T within a bank and
; does not carry into A1B. The blob is one contiguous claim, so this is a
; property of where the allocator placed it, and it is asserted rather than
; assumed.
.assert (.loword(hz_warp_bin) + HZ_BLOB_COUNT * 256) <= $10000, error, "hz_warp's blobs straddle a bank boundary - HDMA cannot cross one"

; --- hz_arm: the channel, the seed scroll, the phase (scene enter) ----------
; CONTRACT hz_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the warp channel's shadow slots filled and pointing at phase 0,
;             BG1VOFS seeded to the flat base, ES_HZ_PHASE and
;             ES_HZ_FLAT zeroed (the effect is on)
;   clobbers: A, X, N, Z
;   assumes:  forced blank, at scene enter. The caller ORs ES_H_HZWARP_CH's
;             bit into the HDMAEN shadow AFTERWARDS; this routine does not
;   tail:     rts
;
; THE SEED IS DECLARED, NOT INCIDENTAL. `hz_seed` in feature.toml is the
; [[claims.reg]] that lets a CPU write coexist with a transfer claim on the
; same port, and the allocator refuses a seed that nothing overrides — so this
; store and the channel below are a matched pair by construction.
hz_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "hz_arm"
    stz z:ES_HZ_PHASE
    stz z:ES_HZ_FLAT                 ; the effect is ON at scene enter
    sep #$20
    .a8
    ; ---- the flat base the channel holds above the band -------------------
    ; Write-twice: the port takes the low byte then the high. The table's
    ; head-skip entry restates these same values over the lines above the
    ; band every frame, which is why they are declared as `seed` rather than
    ; as owners.
    ;
    ; HZ_VOFS, NOT ZERO. The first active scanline is 1, so -1 is what puts
    ; world row r on picture rows 8r..8r+7 (heathaze.inc). An undistorted
    ; scanline under this table is therefore byte-identical to one the CPU
    ; wrote, which is what makes the flat control a true control.
    lda #<HZ_VOFS
    sta a:$210E                     ; BG1VOFS, low
    lda #>HZ_VOFS
    sta a:$210E                     ; BG1VOFS, high
    ; ---- the channel's shadow slots ---------------------------------------
    ldx #(ES_H_HZWARP_CH * 16)
    lda #ES_H_HZWARP_DMAP
    sta f:ES_SM_HDMA_LONG + 0, x    ; DMAP: direct, mode 2 (write twice)
    lda #ES_H_HZWARP_BBAD
    sta f:ES_SM_HDMA_LONG + 1, x    ; BBAD -> BG1VOFS
    lda #<hz_warp_bin
    sta f:ES_SM_HDMA_LONG + 2, x    ; A1T low — CONSTANT across every blob
    lda #>hz_warp_bin
    sta f:ES_SM_HDMA_LONG + 3, x    ; A1T high — blob 0
    lda #^hz_warp_bin
    sta f:ES_SM_HDMA_LONG + 4, x    ; A1B: the ROM bank the claim landed in
    rep #$20
    .a16
    rts

; --- hz_advance: move the shimmer on by this frame's whole-phase step -------
; CONTRACT hz_advance
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = this frame's step in WHOLE phases (a TS_STEP output)
;   out:      ES_HZ_PHASE advanced and wrapped into 0..HZ_PHASES-1
;   clobbers: A, N, Z, C
;   assumes:  the main thread. The value it writes is read by hz_nmi_commit in
;             the NEXT VBlank, so a partial write cannot be seen: the add and
;             the mask are one A16 sequence with no yield in it
;   tail:     rts
;
; TICK: ok — this routine's unit of time is the DECLARED TICK, not the frame.
;   It adds nothing of its own: `A` arrives as TS_STEP's published whole-unit
;   step, which is the scaler's output and is already expressed against the
;   tick, so the name-matched `_advance` here is a site that CONSUMES a removed
;   frame coupling rather than one that states a new one. Nothing in the body
;   reads a frame counter, and the caller's rate is a base in 8.8, not a
;   per-frame immediate. (water.asm:209 is the same routine shape reaching the
;   same conclusion, and for the same reason.)
;
; THE WRAP IS A MASK, and that is a property of HZ_PHASES rather than a
; convenience — 32 is a power of two AND the point at which both components of
; the wave complete a whole number of cycles, so the animation closes there
; with no seam. tools/gen_haze_assets.py is where those two facts meet.
hz_advance:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "hz_advance"
    clc
    adc z:ES_HZ_PHASE
    and #(HZ_PHASES - 1)
    sta z:ES_HZ_PHASE
    rts

; --- hz_show: choose the animation or the flat control ---------------------
; CONTRACT hz_show
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = 0 to show the animation, 1 to show the zero-displacement
;             control
;   out:      ES_HZ_FLAT set; the next VBlank commit acts on it
;   clobbers: A, N, Z
;   assumes:  the main thread
;   tail:     rts
;
; THE ANIMATION'S POSITION IS NOT TOUCHED. Flattening the picture and then
; un-flattening it resumes where the shimmer was, rather than restarting it —
; which is what makes the toggle a CONTROL (one variable moves) instead of a
; reset.
hz_show:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "hz_show"
    and #1
    sta z:ES_HZ_FLAT
    rts

; --- hz_nmi_commit: point the channel at this frame's blob ------------------
; CONTRACT hz_nmi_commit
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   out:      the warp channel's A1T high byte set to the current phase
;   clobbers: A, X, N, Z, C
;   assumes:  VBlank, from the rail's sm_nmi_hook, in that hook's A8/I16.
;             Touches no PPU port and no other channel's slots, so where it
;             sits in the hook is free
;   tail:     rts
;
; ONE STORE. Blob n is at hz_warp_bin + (n << 8), so the high byte of the
; address is (>hz_warp_bin) + n and the low byte never moves — hz_arm wrote it
; once. This is the entire per-frame cost of the effect, control included: the
; flat table is selected the same way as any phase, so the channel stays armed
; and identically configured in both states, and exactly one variable moves
; between them.
hz_nmi_commit:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "hz_nmi_commit"
    lda z:ES_HZ_FLAT                ; A8: bit 0 is the whole flag
    beq @animating
    lda #HZ_FLAT_INDEX
    bra @select
@animating:
    .a8
    .i16
    lda z:ES_HZ_PHASE               ; the low byte is the whole range 0..63
@select:
    .a8
    .i16
    clc
    adc #>hz_warp_bin
    ldx #(ES_H_HZWARP_CH * 16)
    sta f:ES_SM_HDMA_LONG + 3, x    ; A1T high
    rts
