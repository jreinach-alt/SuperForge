; =============================================================================
; seamtrial.inc — the split_v_seamtrial rail's geometry and tuning
; =============================================================================
; Every value here is a constant of the STAGE or of the SWEEP, never an
; address: addresses are the allocator's and arrive through the emitted map.
;
; All four are load-bearing on the TESTS as well as on the picture -- the
; trial's timing IS its subject, so retuning any of them changes what the proof
; frames prove.

.ifndef SEAMTRIAL_INC
SEAMTRIAL_INC = 1

; The shared viewpoint both cameras straddle. The stage map is 256 px periodic
; (32 tiles x 8 px), which is what makes split_v_bg's mod-256 camera arithmetic
; correct rather than merely tolerable.
SVS_MID_CAM = 96

; Full divergence: cam A settles at 48, cam B at 144. Also fixes the widest the
; divider ever gets, because split_v_bg derives hw = spread >> 4 -- so 48 gives
; hw = 3, a 7 px bar.
SVS_SPREAD_MAX = 48

; 0.75 px/frame in 8.8 -> 64 frames to open and 64 to close, a 128-frame
; triangle. The fraction is the reason the accumulator exists: an integer step
; would move the cameras in 1 px jumps and the "continuous divergence" the rail
; is named for would be a stair.
SVS_SPR_STEP = $00C0

; The scene's base display: BGMODE 1 (BG1/BG2 4bpp, BG3 2bpp) and a main screen
; of BG1|BG2|BG3 with OBJ OFF. OBJ-off is not a default -- it is the rail's
; zero-sprite claim made in the one register that can enforce it, so power-on
; random OAM (rule 5) cannot reach the picture.
SVS_BGMODE = $01
SVS_TM     = $07

.endif ; SEAMTRIAL_INC
