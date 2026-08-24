; =============================================================================
; m7_barrel.asm — the barrel-bowed per-scanline Mode-7 matrix
; =============================================================================
; Two INDIRECT HDMA channels stream ROM per-scanline COLUMNS through M7A and
; M7D. DMAP mode 2 is ONE register written TWICE — exactly [lo, hi] of a 16-bit
; write-twice matrix register — so a unit is 2 bytes and a channel drives one
; port. M7B and M7C are zero on every line (this rail's angle is constant), so
; they are CPU-written once here instead of being streamed as 2 bytes of zeroes
; per line into registers that already hold zero. That is the whole difference
; in transfer shape from `mode7_persp`, which streams A AND B.
;
; The index tables shape the band, mode7_persp's shape at this rail's seam:
;  [MB_SEAM non-repeat, ptr] one harmless unit at line 0, skip the band
;  [$80|127, ptr] floor rows 0..126
;  [$80|MB_TAIL, ptr + 127*2] floor rows 127..end
;  [0]
; The head unit fires at scanline 0, where the picture is Mode 1 and M7A/M7D
; are not read — which is why the claim declares `band = "scene"` rather than
; the more flattering [MB_SEAM, 224].
;
; THE RUNTIME AXIS IS THE BOW STEP. `mb_point` turns it into the A table's
; three pointers; the D table's are static. Per-frame cost in the frames the
; player is not driving the axis is ONE 16-bit compare — the applied step is
; kept beside the live one so the stamp is skipped, not hidden.
;
; THE CAMERA ORIGIN is a DP shadow the NMI hook commits (`mb_commit_origin`),
; not a channel. That is what makes the vertical ROLL — the rail's apparent
; rotation — one 16-bit add on the main thread and four write-twice ports in
; VBlank, with the perspective and the bow both untouched.

; --- the binding contract ---------------------------------------------------
; This feature carries NO defaults: the includer supplies the seam and each
; missing symbol is a named `.error` rather than a silent fallback. Same shape
; `split_band`, `col_map`, `rgb_gradient` and `mode7_stream` keep.
; (`mode7_persp` reaches for a bare `HUD_LINES` instead, which is the older,
; weaker form: a rail that happens to define that symbol for another reason
; binds this one by accident.)
.ifndef MB_SEAM
    .error "m7_barrel: MB_SEAM undefined -- the includer must bind the seam scanline (the first Mode 7 line; the floor is MB_SEAM..223)"
.endif
.assert MB_SEAM > 0 && MB_SEAM < 97, error, "m7_barrel: MB_SEAM must be 1..96 (a 7-bit non-repeat count, and 224-MB_SEAM must fit 127 + one tail entry)"

MB_LINES = 224 - MB_SEAM            ; the floor band, in scanlines
MB_HEAD  = 127                      ; the largest count one repeat entry covers
MB_TAIL  = MB_LINES - MB_HEAD

; --- the two column sets ----------------------------------------------------
; A column is MB_LINES scanlines x 2 bytes. The bow set is MB_BOWS of them at
;  ptr = ES_R_BOW_A_ADDR + step * MB_POSE_BYTES
; with NO bank arithmetic — 3,456 B sits inside one LoROM window many times
; over, so the DASB byte is written once at enter rather than every VBlank.
;
; The sizes are ASSERTED against the claims rather than trusted: if the
; generator's step count and the allocator's byte count ever disagree, the
; build stops here instead of streaming the neighbouring table's bytes.
MB_POSE_BYTES = MB_LINES * 2
MB_BOWS       = 9                   ; tools/gen_chamber_assets.py MB_BOWS
MB_BOW_MAX    = MB_BOWS - 1

.assert MB_BOWS * MB_POSE_BYTES = ES_R_BOW_A_SIZE, error, "m7_barrel: bow step count disagrees with the bow_a claim"
.assert MB_POSE_BYTES = ES_R_PERSP_D_SIZE, error, "m7_barrel: MB_LINES disagrees with the persp_d claim (regenerate with the same seam)"

; --- the two index tables, inside the one 32-byte wram claim ----------------
; 16 B apart so the offsets read as a table rather than as arithmetic. Each is
; 10 B; the slack is what the zero in mb_arm covers.
MB_IDX_A      = ES_MB_IDX + 0
MB_IDX_D      = ES_MB_IDX + 16
MB_IDX_A_LONG = ES_MB_IDX_LONG + 0
MB_IDX_D_LONG = ES_MB_IDX_LONG + 16

; --- the camera origin shadow, inside the 8-byte dp claim -------------------
MB_M7X  = ES_MB_ORG + 0
MB_M7Y  = ES_MB_ORG + 2
MB_HOFS = ES_MB_ORG + 4
MB_VOFS = ES_MB_ORG + 6

; --- the bow axis, inside the 6-byte dp claim -------------------------------
MB_BOW     = ES_MB_BOW + 0          ; the live step, 0..MB_BOW_MAX
MB_BOW_AP  = ES_MB_BOW + 2          ; the step the A table currently points at
MB_TMP     = ES_MB_BOW + 4          ; the pointer multiply's scratch

; The DASB byte ($43x7) of each channel in the scene_mgr shadow the NMI MVNs to
; $4300 — staged there rather than to the register file directly, so it rides
; the same commit path everything else here does.
MB_SHDW_CH = ES_SM_HDMA_SIZE / 8    ; 16 B of register file per channel

; =============================================================================
; mb_point — the live bow step -> the A table's three pointers
; =============================================================================
; In/out: A16/I16, DB=0. Clobbers A.
;
; MB_POSE_BYTES is 384 at the chamber's seam, which is not a single shift, so
; the multiply is the decomposition 384*m = (m<<8) + (m<<7). Written as shifts
; on MB_POSE_BYTES's own factors rather than as a constant, so a rail that
; binds a different seam gets the right stride instead of a silent one.
;
; WIDTH-RISK: A16/I16 on entry AND exit, and the body contains NO sep/rep, so
; it cannot leak a width into a caller on either axis. It is called from BOTH
; `mb_arm` (A16, scene enter) and `mb_tick` (which widens for it), so the
; contract has two live arrival sites.
mb_point:
    .a16
    .i16
    lda z:MB_BOW
    .repeat 7
        asl a
    .endrepeat                      ; m << 7  = m * (MB_POSE_BYTES / 3)
    sta z:MB_TMP
    asl a                           ; m << 8
    clc
    adc z:MB_TMP                    ; m * 384
    clc
    adc #ES_R_BOW_A_ADDR
    sta f:MB_IDX_A_LONG + 1         ; the head-skip unit's pointer
    sta f:MB_IDX_A_LONG + 4         ; floor rows 0..126
    clc
    adc #(MB_HEAD * 2)
    sta f:MB_IDX_A_LONG + 7         ; floor rows 127..end
    rts

; =============================================================================
; mb_arm — build both index tables + both channel shadows (scene enter)
; =============================================================================
; CONTRACT mb_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the barrel tables built and the channel shadow staged
;   clobbers: A, X, N, Z, C, V
;   assumes:  forced blank AND the NMI masked — the scene_mgr enter
;             contract. The caller ORs the enable bit into the HDMAEN
;             shadow AFTERWARDS
;   tail:     rts
;
; ORs the two enable bits into the scene_mgr HDMAEN shadow after.
mb_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mb_arm"
    ; ---- the declared init contract: zero the WHOLE claim first -----------
    ; The bytes past each table's terminator are never stamped, but the DMA
    ; controller's terminator processing still fetches indirect-address bytes
    ; after the $00 — real hardware reads them, so they must not be power-on
    ; garbage (the uninit-read contract; mode7_persp's and shp_cam's arms open
    ; the same way for the same reason). The loop follows the claim's own size.
    lda #0
    ldx #(ES_MB_IDX_SIZE - 2)
:   sta f:ES_MB_IDX_LONG, x
    dex
    dex
    bpl :-

    ; ---- index-table skeletons: counts + terminators ----------------------
    ; 128 is the HDMA repeat flag; the low 7 bits are the line count. A repeat
    ; entry transfers a NEW unit every scanline for that many lines — which is
    ; what makes the bow and the perspective per-scanline rather than one
    ; constant matrix. The head entry's count has the flag CLEAR, the opposite
    ; reading of the same byte: transfer once, then idle for the rest.
    sep #$20
    .a8
    lda #MB_SEAM
    sta f:MB_IDX_A_LONG + 0         ; head: one unit at line 0, then the band
    sta f:MB_IDX_D_LONG + 0
    lda #(128 | MB_HEAD)
    sta f:MB_IDX_A_LONG + 3         ; floor rows 0..126
    sta f:MB_IDX_D_LONG + 3
    lda #(128 | MB_TAIL)
    sta f:MB_IDX_A_LONG + 6         ; floor rows 127..end
    sta f:MB_IDX_D_LONG + 6
    lda #0
    sta f:MB_IDX_A_LONG + 9         ; terminators
    sta f:MB_IDX_D_LONG + 9

    ; ---- the D table's pointers: static, never rewritten ------------------
    ; One perspective column, indexed by nothing (fixed camera height). Only
    ; the A table's pointers move, and only when the bow step does.
    rep #$20
    .a16
    lda #ES_R_PERSP_D_ADDR
    sta f:MB_IDX_D_LONG + 1
    sta f:MB_IDX_D_LONG + 4
    clc
    adc #(MB_HEAD * 2)
    sta f:MB_IDX_D_LONG + 7

    jsr mb_point                    ; the A table's pointers, from the live step

    ; ---- channel shadow: the A column (INDIRECT) --------------------------
    ; An indirect channel needs DASB ($43x7) as well: the bank the per-line
    ; bytes are fetched from. A1B is the INDEX table's bank ($7E); DASB is the
    ; COLUMN blob's. Getting those two the wrong way round is the classic
    ; indirect-HDMA bug, which is why both come from emitted symbols.
    sep #$20
    .a8
    ldx #(ES_H_MBA_CH * MB_SHDW_CH)
    lda #ES_H_MBA_DMAP
    sta f:ES_SM_HDMA_LONG+0, x      ; DMAP: indirect, 1 register write-twice
    lda #ES_H_MBA_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: M7A
    lda #ES_MB_IDX_BANK
    sta f:ES_SM_HDMA_LONG+4, x      ; A1B: the index table's bank ($7E)
    lda #ES_R_BOW_A_BANK
    sta f:ES_SM_HDMA_LONG+7, x      ; DASB: the bow set's bank (static)
    rep #$20
    .a16
    lda #MB_IDX_A
    sta f:ES_SM_HDMA_LONG+2, x      ; A1T: the A index table

    ; ---- channel shadow: the D column (INDIRECT) --------------------------
    sep #$20
    .a8
    ldx #(ES_H_MBD_CH * MB_SHDW_CH)
    lda #ES_H_MBD_DMAP
    sta f:ES_SM_HDMA_LONG+0, x
    lda #ES_H_MBD_BBAD
    sta f:ES_SM_HDMA_LONG+1, x      ; BBAD: M7D
    lda #ES_MB_IDX_BANK
    sta f:ES_SM_HDMA_LONG+4, x
    lda #ES_R_PERSP_D_BANK
    sta f:ES_SM_HDMA_LONG+7, x      ; DASB: the perspective column's bank
    rep #$20
    .a16
    lda #MB_IDX_D
    sta f:ES_SM_HDMA_LONG+2, x

    ; ---- the two columns this rail does NOT stream ------------------------
    ; M7B and M7C are the off-diagonal terms, S(k)*sin(angle), and the angle is
    ; constant zero — so both are zero on every scanline of every frame.
    ; Written ONCE, here, under forced blank. They are write-twice 13-bit ports
    ; like the origin: low byte then high byte, and the hardware latch pairs
    ; them. Declared as `mb_offdiag` so a rail that composes this feature and
    ; then rotates finds the contention in the allocator, not in the picture.
    sep #$20
    .a8
    stz a:$211C
    stz a:$211C                     ; M7B = 0
    stz a:$211D
    stz a:$211D                     ; M7C = 0
    rep #$20
    .a16
    rts

; =============================================================================
; mb_commit_origin — the four write-twice origin ports, from the DP shadow
; =============================================================================
; CONTRACT mb_commit_origin
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   out:      the origin words committed from their DP shadows
;   clobbers: A, N, Z
;   assumes:  VBlank, from the rail's sm_nmi_hook, in that hook's A8/I16
;             convention
;   tail:     rts
;
; WIDTH-RISK: this is a CROSS-FILE contract. Entered A8/I16 from the NMI hook
; and returns A8/I16 with no toggle in the body; width-check cannot see across
; the file boundary in either direction, so this marker carries it.
;
; IN VBLANK, and not incidentally: all four are 13-bit write-twice ports, and a
; write-twice spun across active display is the ValueLatch hazard. The only
; other writer during display is HDMA, which delivers complete pairs.
;
; $211F/$2120 are M7X/M7Y — the plane's rotation/scale ORIGIN. $210D/$210E are
; BG1HOFS/BG1VOFS physically and M7HOFS/M7VOFS in Mode 7 — one port, one name,
; which is why the claim declares them under the BG names.
mb_commit_origin:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "mb_commit_origin"
    lda z:MB_M7X+0
    sta a:$211F
    lda z:MB_M7X+1
    sta a:$211F                     ; M7X (13-bit, low then high)
    lda z:MB_M7Y+0
    sta a:$2120
    lda z:MB_M7Y+1
    sta a:$2120                     ; M7Y
    lda z:MB_HOFS+0
    sta a:$210D
    lda z:MB_HOFS+1
    sta a:$210D                     ; M7HOFS
    lda z:MB_VOFS+0
    sta a:$210E
    lda z:MB_VOFS+1
    sta a:$210E                     ; M7VOFS
    rts

; =============================================================================
; mb_tick — re-point the A column when the bow step moved (VBlank)
; =============================================================================
; CONTRACT mb_tick
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   out:      the barrel's applied step advanced one frame
;   clobbers: A, N, Z, C
;   assumes:  VBlank, from the rail's sm_nmi_hook, in that hook's A8/I16
;             convention
;   tail:     rts
;
; WIDTH-RISK: CROSS-FILE, and this one widens. Entered A8 (the hook's width),
; goes A16 for the 16-bit compare and for mb_point's arithmetic, and MUST
; restore A8 before returning — the hook's next instruction is assembled A8.
; Width-check cannot see the caller, so this marker is the contract.
;
; IN VBLANK because the HDMA init fetch for the next frame reads these tables
; at line 0: a half-written pointer here would be a torn frame.
;
; THE COMPARE IS NOT AN OPTIMISATION DODGE. Mb_point costs the same every time
; it runs; the applied-step word only decides WHETHER it runs, so the rail's
; worst case (the player holding the axis) is the honest cost and the idle case
; is a compare. Both are visible in this file rather than one hiding the other.
mb_tick:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "mb_tick"
    rep #$20
    .a16
    lda z:MB_BOW
    cmp z:MB_BOW_AP
    beq @done
    sta z:MB_BOW_AP
    jsr mb_point
@done:
    .a16                            ; both arrivals (branch + fall-through) A16
    sep #$20
    .a8
    rts

; --- the pad, and which bit of a JOY word is which --------------------------
; $4218 delivers one 16-bit word: B Y Select Start Up Down Left Right in the
; HIGH byte, A X L R in the low. Written as SHIFTS rather than as $0400 and
; friends because `no_literals` cannot tell a bare $0400 from a hand-narrated
; WRAM address — it collides with a real claim — and the shift form says which
; bit position is meant, which the hex does not.
MB_JOY_DOWN = 1 << 10
MB_JOY_UP   = 1 << 11

; =============================================================================
; mb_input — one pad axis: the bow step
; =============================================================================
; CONTRACT mb_input
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the pad folded into the barrel's target
;   clobbers: A, N, Z, C, V
;   assumes:  the pads are already latched
;   tail:     rts
;
; Up steps the bow toward its maximum, Down toward FLAT, both CLAMPED — a bow
; is a segment, not a cycle, and its two ends are this rail's runtime controls.
;
; THE DOWN CLAMP IS A NON-VACUITY CONTROL, and that is why the axis exists at
; all. Step 0's column is 1.0 on every scanline (tools/gen_chamber_assets.py
; asserts it at emit time), so holding Down collapses the barrel to no barrel
; INSIDE the shipping binary: a test can watch the bow appear and disappear
; rather than photograph one frame and call the shape a barrel. An autonomous
; bow that holds one shape forever can only ever be SAMPLED, which is the
; weaker test.
;
; Up AND Down together is a deliberate no-op (+1 then -1). The hardware can
; report both on a worn pad, and cancelling is the honest answer.
;
; WIDTH-RISK: A16/I16 on entry AND exit; the body contains NO sep/rep, so it
; cannot leak a width into the caller on either axis. Every local label below
; is reached A16 by fall-through AND by branch.
mb_input:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "mb_input"
    lda z:ES_INP_CUR
    bit #MB_JOY_UP
    beq @noup
    lda z:MB_BOW
    cmp #MB_BOW_MAX
    bcs @noup                       ; already at the full bow: hold, do not wrap
    inc a
    sta z:MB_BOW
@noup:
    .a16
    lda z:ES_INP_CUR
    bit #MB_JOY_DOWN
    beq @nodown
    lda z:MB_BOW
    beq @nodown                     ; already flat: hold
    dec a
    sta z:MB_BOW
@nodown:
    .a16
    rts
