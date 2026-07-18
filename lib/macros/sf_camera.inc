; =============================================================================
; sf_camera.inc — camera-follow macro (macro library)
; =============================================================================
; A scrolling camera that tracks a player in a larger world, with edge clamping
; so the view never scrolls past the world bounds. Builds on the BG scroll
; primitive (sf_bg.inc) — composes the camera math the genre templates need.
;
; The screen is 256x224. The camera centres the player (player - half-screen),
; clamped to [0, world - screen]. Draw the player sprite at its SCREEN position
; (= world - camera), which sf_camera_follow leaves you the camera to compute.
;
; Requires: sf_bg.inc (scroll) + its engine link set.
; =============================================================================

.ifndef SF_CAMERA_INC
SF_CAMERA_INC = 1

.include "sf_bg.inc"

; -----------------------------------------------------------------------------
; sf_clamp0 var, hi — clamp a 16-bit memory value to [0, hi] (hi assemble-time).
; -----------------------------------------------------------------------------
; Signed-aware low bound: a value that moved below 0 (wrapping to a high 16-bit
; value, bit 15 set) clamps to 0 rather than the top. Use it to keep a player
; inside the world after moving. Clobbers A.
; WIDTH-RISK: asserts A16 entry/exit (safe-by-default).
.macro sf_clamp0 sf_var, sf_hi
    .local chk_hi, done
    rep #$20
    .a16
    lda sf_var
    bpl chk_hi                  ; bit15=0 -> non-negative, check high
    lda #$0000                  ; wrapped below 0 -> clamp to 0
    bra done
chk_hi:
    cmp #((sf_hi) + 1)
    bcc done                    ; <= hi -> keep
    lda #(sf_hi)                ; > hi -> clamp to hi
done:
    sta sf_var
.endmacro

; -----------------------------------------------------------------------------
; sf_camera_follow  pwx, pwy, world_w, world_h, cam_x, cam_y
; -----------------------------------------------------------------------------
; Compute the clamped follow-camera for a player at world position (pwx, pwy)
; in a (world_w x world_h)-pixel world, write it to (cam_x, cam_y), and scroll
; BG1 to it. world_w/world_h are assemble-time constants (>= 256 / >= 224).
; PRECONDITION: clamp the player to the world first (sf_clamp0 pwx,(world_w-8)
; etc.) so the resulting sprite screen pos (pwx-cam_x) stays on screen.
;   cam_x = clamp(pwx - 128, 0, world_w - 256)
;   cam_y = clamp(pwy - 112, 0, world_h - 224)
; pwx/pwy and cam_x/cam_y are memory operands (verbatim). After this, the
; player's SCREEN position is (pwx - cam_x, pwy - cam_y) — pass that to spr.
; Clobbers A, X, Y.
;
; WIDTH-RISK: asserts A16/I16 entry (safe-by-default); all math is A16; exits
; A16/I16 (scroll preserves the contract).
.macro sf_camera_follow sf_pwx, sf_pwy, sf_world_w, sf_world_h, sf_cam_x, sf_cam_y
    .local xkeep, xclamphi, ykeep, yclamphi
    rep #$30
    .a16
    .i16

    ; cam_x = clamp(pwx - 128, 0, world_w - 256)
    lda sf_pwx
    sec
    sbc #128
    bpl xkeep                   ; >= 0 -> keep
    lda #$0000                  ; < 0  -> clamp low to 0
xkeep:
    cmp #(((sf_world_w) - 256) + 1)
    bcc xclamphi                ; <= max -> keep
    lda #((sf_world_w) - 256)   ; > max  -> clamp high
xclamphi:
    sta sf_cam_x

    ; cam_y = clamp(pwy - 112, 0, world_h - 224)
    lda sf_pwy
    sec
    sbc #112
    bpl ykeep
    lda #$0000
ykeep:
    cmp #(((sf_world_h) - 224) + 1)
    bcc yclamphi
    lda #((sf_world_h) - 224)
yclamphi:
    sta sf_cam_y

    scroll #1, sf_cam_x, sf_cam_y
.endmacro

.endif ; SF_CAMERA_INC
