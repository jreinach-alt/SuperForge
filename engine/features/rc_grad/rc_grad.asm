; =============================================================================
; rc_grad.asm — the day-night COLDATA wash (three indirect HDMA channels)
; =============================================================================
; Structurally rgb_gradient with ONE difference, and the difference is the
; feature: rgb_gradient assembles its three indirect header tables into the
; CODE BANK pointing at one static blob, so nothing about the wash can change
; after link. Here the three tables live in a 24-byte WRAM claim and the game
; RETARGETS their data pointers at one of RC_TOD_KEYS ROM keyframes —
; `mode7_persp`'s `persp_set_pose` shape applied to COLDATA instead of to
; M7A-M7D. Six stores per step, no rebuild, no realloc.
;
; REBUILDING three 225-entry tables in place on every blend step is the
; obvious alternative, and it is a whole-frame-class cost: ~3,700 cycles per
; active channel per frame, enough that the frame has to give something else
; up on every blend step. Nothing has to give here.
;
; Table shape, per plane, at ES_RCG_IDX + plane*8:
;  +0 [128|127] +1..2 ptr lines 0..126 (repeat: one byte per line)
;  +3 [128| 97] +4..5 ptr + 127 lines 127..223
;  +6 [0] terminator +7 pad
; 127 + 97 = 224. A repeat entry's count byte is 128|n with n <= 127; 128|0 is
; "repeat, zero lines" — a degenerate entry, not "repeat 128". Rgb_gradient's
; header carries the measurement that settled that, and this file inherits the
; split rather than re-deriving it.
;
; THE BINDING CONTRACT (col_map / split_band / rgb_gradient's shape). This
; feature carries NO defaults: the includer supplies the keyframe blob and the
; colour-math layer mask, and each missing one is a named `.error`. What the
; wash LANDS ON is the scene's look, not the feature's.
;
;  RCG_KEYS_ADDR / RCG_KEYS_BANK the keyframe blob's emitted ES_R_*_ADDR/_BANK
;  RCG_MATH_LAYERS CGADSUB's layer bits (which layers are washed)
.ifndef RCG_KEYS_ADDR
    .error "rc_grad: the includer must define RCG_KEYS_ADDR (the keyframe blob's ES_R_<name>_ADDR) before including this file"
.endif
.ifndef RCG_KEYS_BANK
    .error "rc_grad: the includer must define RCG_KEYS_BANK (the keyframe blob's ES_R_<name>_BANK) before including this file"
.endif
.ifndef RCG_MATH_LAYERS
    .error "rc_grad: the includer must define RCG_MATH_LAYERS (CGADSUB's layer bits) before including this file"
.endif
.ifndef RCG_KEYS_COUNT
    .error "rc_grad: the includer must define RCG_KEYS_COUNT (how many keyframes the blob holds -- a power of two)"
.endif

RCG_LINES = 224                     ; whole frame, one byte per scanline
RCG_HEAD  = 127                     ; max lines one repeat entry can cover
RCG_TAIL  = RCG_LINES - RCG_HEAD
RCG_PLANE = RCG_LINES               ; bytes per plane inside a keyframe
RCG_KEY   = 3 * RCG_PLANE           ; bytes per keyframe (672)
RCG_SLOT  = 8                       ; bytes per plane's header table
RCG_MAX_KEY = RCG_KEYS_COUNT - 1    ; index mask (the count is a power of two)

; The keyframe pointer arithmetic is `RCG_KEYS_ADDR + k*RCG_KEY + p*RCG_PLANE`
; with ONE DASB bank, so the whole blob has to sit inside a single LoROM
; window. That is true today (the claim is 5,376 B at a window base) and it is
; the kind of truth that stops being true silently, so it is asserted.
.assert RCG_KEYS_ADDR >= $8000, error, "rc_grad: keyframe blob is not in a LoROM window"

; --- rcg_arm: build the three header tables + channel shadow (scene enter) --
; In/out: A16/I16, DB=0, forced blank (scene_mgr enter contract). Leaves the
; tables pointed at keyframe 0; the caller ORs the three ES_H_RCG*_CH bits into
; the HDMAEN shadow.
rcg_arm:
    .a16
    .i16
    ; ---- the declared init contract: zero the WHOLE claim first ----------
    ; The DMA controller fetches indirect-address bytes PAST the terminator on
    ; real hardware (mode7_persp's persp_arm carries the same measurement), so
    ; the pad bytes must not be power-on garbage.
    lda #0
    ldx #(ES_RCG_IDX_SIZE - 2)
:   sta f:ES_RCG_IDX_LONG, x
    dex
    dex
    bpl :-
    ; ---- count bytes + terminators (the pointers come from set_key) -------
    sep #$20
    .a8
    ldx #0
@skel:
    .a8
    .i16
    lda #(128 | RCG_HEAD)
    sta f:ES_RCG_IDX_LONG + 0, x
    lda #(128 | RCG_TAIL)
    sta f:ES_RCG_IDX_LONG + 3, x
    lda #0
    sta f:ES_RCG_IDX_LONG + 6, x    ; terminator
    ; X += RCG_SLOT in A16: `txa`/`tax` in A8/I16 move the FULL 16-bit C, so
    ; the A8 form would carry whatever the high byte last held (width-lint's
    ; tax-tay-cross-width check, and the bug class it is named for).
    rep #$20
    .a16
    txa
    clc
    adc #RCG_SLOT
    tax
    sep #$20
    .a8
    cpx #(3 * RCG_SLOT)
    bcc @skel
    ; ---- channel shadows: one per plane ----------------------------------
    ; Each channel's A1T points at THIS PLANE's header table inside the WRAM
    ; claim; DASB is the keyframe blob's bank and never changes (unlike
    ; mode7_persp's pose slices, the whole keyframe set is one window).
    ldx #(ES_H_RCGR_CH * 16)
    ldy #(ES_RCG_IDX + 0 * RCG_SLOT)
    jsr @chan
    ldx #(ES_H_RCGG_CH * 16)
    ldy #(ES_RCG_IDX + 1 * RCG_SLOT)
    jsr @chan
    ldx #(ES_H_RCGB_CH * 16)
    ldy #(ES_RCG_IDX + 2 * RCG_SLOT)
    jsr @chan
    ; ---- colour math: ADD the per-line fixed colour to the bound layers ---
    lda #$02                        ; CGWSEL: add subscreen off -> fixed colour
    sta a:$2130
    lda #(RCG_MATH_LAYERS)          ; CGADSUB: add (bit 7 clear), bound layers
    sta a:$2131
    rep #$20
    .a16
    lda #0
    jsr rcg_set_key                 ; point everything at keyframe 0 (day)
    rts

; ---- @chan: stamp one channel's shadow slot -------------------------------
; In: X = channel slot * 16, Y = this plane's header table address. A8/I16.
; WIDTH-RISK: entry and exit are both A8/I16 — it toggles A16 for the A1T word
; store and toggles back. All three call sites above are A8.
@chan:
    .a8
    .i16
    lda #ES_H_RCGR_DMAP             ; all three planes: indirect, mode 0
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_RCGR_BBAD             ; all three: COLDATA ($2132) — one port,
    sta f:ES_SM_HDMA_LONG+1, x      ;   the plane-select bits ride the DATA
    lda #ES_RCG_IDX_BANK
    sta f:ES_SM_HDMA_LONG+4, x      ; A1B: the header tables' bank ($7E)
    lda #RCG_KEYS_BANK
    sta f:ES_SM_HDMA_LONG+7, x      ; DASB: the keyframe blob's bank
    rep #$20
    .a16
    tya                             ; I16 -> A16: an exact 16-bit transfer
    sta f:ES_SM_HDMA_LONG+2, x      ; A1T: THIS PLANE's header table
    sep #$20
    .a8
    rts

; --- rcg_set_key: point all three planes at keyframe A (0..RC_TOD_KEYS-1) ---
; In: A16 = keyframe index. Out: A16/I16. VBlank- or forced-blank-safe: it
; writes only the WRAM header tables, which HDMA re-reads next frame. The plane
; tables are RCG_PLANE apart inside the keyframe, so one multiply and three
; adds cover all six pointers.
rcg_set_key:
    .a16
    .i16
    ; k -> the keyframe's byte offset. A TABLE rather than a shift chain: the
    ; multiply would need DP scratch, and the only scratch in this scene
    ; belongs to rc_logic — reaching across a feature boundary for a spare word
    ; is exactly the undeclared coupling the allocator exists to stop
    ; (mode7_stream still carries one surviving instance of it).
    and #(RCG_MAX_KEY)
    asl
    tax
    lda f:rcg_key_off, x
    clc
    adc #RCG_KEYS_ADDR              ; -> the R plane's base
    ldx #0
@plane:
    .a16
    .i16
    sta f:ES_RCG_IDX_LONG + 1, x    ; span 1 pointer: lines 0..126
    pha
    clc
    adc #RCG_HEAD
    sta f:ES_RCG_IDX_LONG + 4, x    ; span 2 pointer: lines 127..223
    pla
    clc
    adc #RCG_PLANE                  ; next plane's table inside the keyframe
    inx
    inx
    inx
    inx
    inx
    inx
    inx
    inx                             ; X += RCG_SLOT
    cpx #(3 * RCG_SLOT)
    bcc @plane
    rts

; --- rcg_disarm: colour math back to the boot state (scene exit) ------------
; In/out: A16/I16, DB=0. CGWSEL/CGADSUB are GLOBAL registers: a scene that
; leaves them set washes the next scene through registers it never wrote.
rcg_disarm:
    .a16
    .i16
    sep #$20
    .a8
    stz a:$2130                     ; CGWSEL: boot state
    stz a:$2131                     ; CGADSUB: no colour math
    rep #$20
    .a16
    rts

; --- the keyframe byte offsets, k * RCG_KEY -------------------------------
; Assembled from RCG_KEYS_COUNT so a blob with more keyframes needs no edit
; here, and a `.repeat` count is derived rather than narrated.
rcg_key_off:
.repeat RCG_KEYS_COUNT, KI
    .word KI * RCG_KEY
.endrepeat
