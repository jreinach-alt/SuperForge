; =============================================================================
; split_v_demo.inc — the rail's controls and its two tuning constants
; =============================================================================
; Sizes, speeds and button masks. Never an address: every address on this rail
; comes from the allocator's emitted map.

; $4218's JOY1 word: B=$8000 Y=$4000 Select=$2000 Start=$1000 Up=$0800
; Down=$0400 Left=$0200 Right=$0100 A=$0080 X=$0040 L=$0020 R=$0010.
; BIT POSITIONS, written as shifts so the layout is legible rather than
; transcribed as a mask.
JOY_B     = 1 << 15
JOY_LEFT  = 1 << 9
JOY_RIGHT = 1 << 8
JOY_A     = 1 << 7
JOY_L     = 1 << 5
JOY_R     = 1 << 4

SVD_CAM_SPD = 2                 ; camera px per frame
SVD_SEAM_LO = 64                ; the seam's clamp...
SVD_SEAM_HI = 192               ; ...so neither half can be squeezed to nothing

; BGMODE 1 (BG1 + BG2 4bpp, BG3 2bpp) and TM = BG1|BG2|OBJ. BG3 is NOT on the
; main screen: this rail's divider is the BACKDROP through a window band, so
; BG3 carries nothing and enabling it would only put an uninitialised layer on
; screen (rule 5).
SVD_BGMODE = 1
SVD_TM     = 1 | 2 | 16
