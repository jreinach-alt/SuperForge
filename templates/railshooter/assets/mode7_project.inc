; =============================================================================
; mode7_project.inc — rail-shooter pseudo-3D projection LUT (GENERATED)
; =============================================================================
; Pinhole (1/z) projection table, decoupled from the Mode 7 affine matrix.
; The Mode 7 grid is the visual backdrop only; obstacles ride this projection.
; Consumed by engine/mode7_project.asm. PURE ARITHMETIC from the pinhole
; constants — no ROM/HDMA readback. Regenerate:
;   PYTHONPATH=. python3 templates/railshooter/assets/make_project_lut.py
;
; DEPTH AXIS = z in WORLD PIXELS ahead of the camera (caller carries z
; directly; no 256x scaling). The caller buckets z by >> PROJ_Q_LOG2.
;
; pinhole params: HORIZON_Y=56 CAM_H=17 FOCAL=44 Z_NEAR=16 Z_FAR=640
; projection:
;   screen_y(z) = clamp(HORIZON_Y + CAM_H*256/z, HORIZON_Y, 223)
;   scale(z)    = FOCAL*256/z          (.8 perspective factor)
;   screen_x    = 128 + ((obj_x-cam_x) * scale) >> 8
; z range covered: 0..640 in steps of 8 world px.
; =============================================================================

PROJ_Q       = 8        ; world-px per bucket
PROJ_Q_LOG2  = 3        ; log2(PROJ_Q) — bucket = z >> this
PROJ_N       = 81       ; bucket count
PROJ_DMAX    = 640      ; max projectable depth z (world px)

; size-tier z thresholds (nearer = bigger; tier 0 largest .. 3 smallest)
PROJ_TIER_T0 = 80
PROJ_TIER_T1 = 160
PROJ_TIER_T2 = 360

; --- scanline byte per z bucket (screen_y the object's centre sits on) ---
proj_scanline:
    .byte 223, 223, 223, 211, 176, 154, 139, 128, 120, 113, 107, 103, 99, 96, 93, 91
    .byte 88, 87, 85, 83, 82, 81, 80, 79, 78, 77, 76, 75, 75, 74, 73, 73
    .byte 72, 72, 71, 71, 70, 70, 70, 69, 69, 69, 68, 68, 68, 67, 67, 67
    .byte 67, 66, 66, 66, 66, 66, 65, 65, 65, 65, 65, 65, 64, 64, 64, 64
    .byte 64, 64, 64, 64, 63, 63, 63, 63, 63, 63, 63, 63, 63, 63, 62, 62
    .byte 62

; --- scale word per z bucket (.8 perspective factor = FOCAL*256/z) ---
proj_xscale:
    .word $0B00, $03AA, $0233, $0192, $0138, $0100, $00D8, $00BB
    .word $00A5, $0094, $0086, $007A, $0070, $0068, $0061, $005A
    .word $0055, $0050, $004C, $0048, $0044, $0041, $003E, $003B
    .word $0039, $0037, $0035, $0033, $0031, $002F, $002E, $002C
    .word $002B, $002A, $0028, $0027, $0026, $0025, $0024, $0023
    .word $0022, $0021, $0021, $0020, $001F, $001E, $001E, $001D
    .word $001D, $001C, $001B, $001B, $001A, $001A, $0019, $0019
    .word $0018, $0018, $0018, $0017, $0017, $0016, $0016, $0016
    .word $0015, $0015, $0015, $0014, $0014, $0014, $0013, $0013
    .word $0013, $0013, $0012, $0012, $0012, $0012, $0011, $0011
    .word $0011
