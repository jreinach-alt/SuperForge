; =============================================================================
; rpg_floor.asm — the rpg overworld's Mode 7 ground plane (scene-scoped)
; =============================================================================
; One routine: upload the interleaved 32 KB region, the 32-word palette, and
; M7SEL. Everything else about the picture belongs to someone else — the matrix
; to mode7_persp, the band split to split_band, the camera origin to the scene.
;
; THE UPLOAD IS ONE DMA, and the blob's layout is why. Mode 7's VRAM
; interleaves the tilemap and the CHR at alternate BYTES, which is exactly what
; a mode-1 (2-register write-once) transfer through $2118/$2119 produces: byte
; 0 -> the map port, byte 1 -> the CHR port, address++. Tools/gen_rpg_assets.py
; emits the blob in that order, so no second transfer and no interleaver runs
; here.
;
; A DMA source may not cross a bank. The m7_world claim is 32,768 B, which
; fills ONE LoROM window exactly ($8000..$FFFF), so the transfer ends on the
; boundary rather than carrying past it.
;
; Called from scene enter, under FORCED BLANK with NMI masked (the scene_mgr
; enter contract). Nothing here runs while the screen is live.
RPGF_REGS = $4300 + ES_D_RPGF_UP_CH * 16
; The 24-bit constants the CPU-side palette read needs. Derived from the
; emitted claim symbols, never spelled (sh2_cam.asm:117's form).
RPGF_PAL_LONG = (ES_R_M7_PAL_BANK << 16) | ES_R_M7_PAL_ADDR

; --- rpgf_arm: the whole ground plane ---------------------------------------
; In/out: A16/I16, DB=0. Clobbers A, X, Y. WIDTH-RISK: exported. Entry A16/I16,
; exit A16/I16; A8 windows are balanced.
.a16
.i16
rpgf_arm:
    sep #$20
    .a8
    lda #$80
    sta a:$2115                     ; VMAIN: word step after the $2119 write
    lda #ES_R_M7_WORLD_BANK
    sta a:RPGF_REGS + 4             ; A1B
    rep #$20
    .a16
    stz a:$2116                     ; VMADD = 0 — Mode 7 ignores BGxSC/BGxxNBA,
                                    ;  its region is pinned at word 0
    lda #ES_R_M7_WORLD_ADDR
    sta a:RPGF_REGS + 2             ; A1T
    lda #ES_R_M7_WORLD_SIZE
    sta a:RPGF_REGS + 5             ; DAS — armed here, one transfer
    sep #$20
    .a8
    lda #ES_D_RPGF_UP_DMAP
    sta a:RPGF_REGS + 0
    lda #ES_D_RPGF_UP_BBAD
    sta a:RPGF_REGS + 1             ; -> VMDATAL
    lda #(1 << ES_D_RPGF_UP_CH)
    sta a:$420B                     ; fire
    ; ---- the 32 floor colours, CPU-side ----------------------------------
    lda #ES_C_FLOOR_PAL
    sta a:$2121                     ; CGADD = this feature's claim base
    ldx #0
@pal:
    lda f:RPGF_PAL_LONG, x
    sta a:$2122
    inx
    cpx #ES_R_M7_PAL_SIZE
    bcc @pal
    ; ---- M7SEL: Screen Over = WRAP. The world IS a 1024-px torus, which is
    ;  the same statement col_map's `and #(CM_W-1)` makes on the collision
    ;  side, so the two agree by construction rather than by comment.
    stz a:$211A
    rep #$20
    .a16
    rts
