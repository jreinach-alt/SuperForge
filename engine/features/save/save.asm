; =============================================================================
; save.asm — battery-backed SRAM save/load with CRC-16 integrity (global)
; =============================================================================
; The sram class's first occupant: 2 slots x 32 B over the save_slots claim.
; Format + rejection semantics under allocator symbols: every SRAM byte goes
; through ES_S_SAVE_SLOTS_LONG, the CRC table through the crc16_lut_rom
; claim's blob label, the DP scratch through the sv_args claim. Slot layout:
; feature.toml documents the 8-B header + 24-B payload; SV_FORMAT_VER is
; bumped when the payload layout changes, which makes old saves
; detected-invalid rather than silently mis-read.
;
; API — all four entries: In/out A16/I16, DP = 0. DB-independent (every SRAM /
; WRAM / ROM access is 24-bit long addressing). Clobber A, X, Y.
;
;  sv_save SV_SLOT, SV_PTR (payload src), SV_LEN (0..24), SV_VER
;  -> A = 0. Writes header + payload + CRC.
;  sv_load SV_SLOT, SV_PTR (payload dest), SV_CAP (dest capacity, bytes)
;  -> A = stored length (success, payload copied)
;  A = $FFFF no save (magic missing) — dest untouched
;  A = $FFFE corrupt (version / length / CRC, or stored
;  length > SV_CAP) — dest untouched
;  sv_exists SV_SLOT -> A = 1 (valid save) / 0. No copy.
;  sv_clear SV_SLOT -> A = 0. Invalidates the magic; payload not wiped.
;
; Magic + version + length + CRC are verified BEFORE any copy, and sv_load
; additionally refuses a stored length above the caller's SV_CAP before its
; copy. Always gate on the return codes — never branch on raw SRAM bytes:
; virgin SRAM is power-on garbage and this gate is what makes it detectable.
;
; SRAM is in the always-slow region (8 mc/access); a full-slot save is ~70 long
; accesses — enter-phase noise, never per-frame work.

; --- format constants (this game generation's convention, not format law) ---
SV_SLOT_SIZE  = 32
SV_SLOT_COUNT = 2
SV_HDR_SIZE   = 8
SV_MAX_DATA   = SV_SLOT_SIZE - SV_HDR_SIZE      ; 24
SV_FORMAT_VER = 1

; --- DP argument block (the sv_args claim; layout per feature.toml) ---------
SV_SLOT = ES_SV_ARGS + 0        ; 2 B: slot BASE byte offset (0 / SV_SLOT_SIZE)
SV_LEN  = ES_SV_ARGS + 2        ; 2 B: payload length
SV_VER  = ES_SV_ARGS + 4        ; 2 B: version (low byte stored)
SV_CRC  = ES_SV_ARGS + 6        ; 2 B: CRC accumulator (sv_crc16 internal)
SV_TMP  = ES_SV_ARGS + 8        ; 2 B: scratch
SV_CLEN = ES_SV_ARGS + 10       ; 2 B: CRC region length (header + payload)
SV_PTR  = ES_SV_ARGS + 12       ; 3 B: payload src/dest, 24-bit WRAM pointer
SV_CAP  = ES_SV_ARGS + 15       ; 2 B: sv_load only — dest capacity in bytes

; --- sv_save: write header + payload + CRC into a slot ----------------------
; CONTRACT sv_save
;   entry:    A16 I16
;   exit:     A16 I16
;   in:       SV_SLOT, SV_PTR, SV_LEN (the caller keeps it inside
;             SV_MAX_DATA) and SV_VER
;   out:      the slot written — header, payload and CRC — and A = 0
;   clobbers: A, X, Y, N, Z, C, V
;   assumes:  the SRAM window is mapped and the slot index is in range;
;             the length bound is the caller's to hold
;   tail:     rts
sv_save:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "sv_save"
    ldx z:SV_SLOT
    sep #$20
    .a8
    lda #'S'                        ; magic "SF"
    sta f:ES_S_SAVE_SLOTS_LONG, x
    lda #'F'
    sta f:ES_S_SAVE_SLOTS_LONG + 1, x
    lda z:SV_VER
    sta f:ES_S_SAVE_SLOTS_LONG + 2, x
    lda #0
    sta f:ES_S_SAVE_SLOTS_LONG + 3, x   ; reserved
    rep #$20
    .a16
    lda z:SV_LEN
    sta f:ES_S_SAVE_SLOTS_LONG + 4, x
    lda #0
    sta f:ES_S_SAVE_SLOTS_LONG + 6, x   ; CRC field = 0 for the compute
    lda z:SV_LEN
    beq @crc                        ; header-only save: nothing to copy
    txa                             ; X = slot base + header -> payload dest
    clc
    adc #SV_HDR_SIZE
    tax
    ldy #0
    sep #$20
    .a8
; WIDTH-RISK: the copy loop runs A8/I16 — entered A8 (the sep above), X/Y stay
; 16-bit indexes; cpy compares 16-bit (index width). Exits via the
; rep below. No pushes/pulls inside, so no stack-balance arm to count.
@save_copy:
    .a8
    lda [<SV_PTR], y                ; WRAM payload byte (bank from the pointer)
    sta f:ES_S_SAVE_SLOTS_LONG, x
    inx
    iny
    cpy z:SV_LEN
    bcc @save_copy
    rep #$20
    .a16
@crc:                               ; fallthrough (A16) and beq from A16
    .a16
    lda z:SV_LEN
    clc
    adc #SV_HDR_SIZE
    sta z:SV_CLEN
    jsr sv_crc16                    ; A = CRC over [slot .. slot+CLEN)
    ldx z:SV_SLOT
    sta f:ES_S_SAVE_SLOTS_LONG + 6, x
    lda #0
    rts

; --- sv_check: the shared integrity gate (internal) -------------------------
; In: SV_SLOT. Out: A = 0 valid (SV_LEN holds the stored length) / $FFFF no
; save / $FFFE corrupt. In/out A16/I16. Clobbers A, X, Y, SV_TMP, SV_CLEN.
; Never copies; never writes SRAM except the CRC field's zero-for-compute +
; restore (net unchanged).
sv_check:
    .a16
    .i16
    ldx z:SV_SLOT
    sep #$20
    .a8
    lda f:ES_S_SAVE_SLOTS_LONG, x
    cmp #'S'
    bne @no_save
    lda f:ES_S_SAVE_SLOTS_LONG + 1, x
    cmp #'F'
    bne @no_save
    lda f:ES_S_SAVE_SLOTS_LONG + 2, x
    cmp #SV_FORMAT_VER              ; wrong version = detected-invalid, not
    bne @corrupt8                   ; a migration hook
    rep #$20
    .a16
    lda f:ES_S_SAVE_SLOTS_LONG + 4, x
    sta z:SV_LEN
    cmp #(SV_MAX_DATA + 1)          ; an impossible length cannot be a real
    bcs @corrupt16                  ; save AND would over-run the slot copy
    lda f:ES_S_SAVE_SLOTS_LONG + 6, x
    pha                             ; stored CRC; matched by exactly one pla
                                    ; on the fall-through path below (both
                                    ; @corrupt16 entries are outside the
                                    ; push/pull window or after it)
    lda #0
    sta f:ES_S_SAVE_SLOTS_LONG + 6, x
    lda z:SV_LEN
    clc
    adc #SV_HDR_SIZE
    sta z:SV_CLEN
    jsr sv_crc16                    ; A = computed CRC; clobbers X, Y
    sta z:SV_TMP
    ldx z:SV_SLOT
    pla                             ; stored CRC back
    sta f:ES_S_SAVE_SLOTS_LONG + 6, x   ; restore the slot byte-identical
    cmp z:SV_TMP
    bne @corrupt16
    lda #0
    rts
@no_save:                           ; reached via bne in A8
    .a8
    rep #$20
    .a16
    lda #$FFFF
    rts
@corrupt8:                          ; reached via bne in A8 (version)
    .a8
    rep #$20
    .a16
@corrupt16:                         ; reached in A16 (length pre-push, CRC
    .a16                            ; post-pull — stack balanced on both)
    lda #$FFFE
    rts

; --- sv_load: verify, then copy the payload out -----------------------------
; CONTRACT sv_load
;   entry:    A16 I16
;   exit:     A16 I16
;   in:       SV_SLOT, SV_PTR (the destination) and SV_CAP (that buffer's
;             capacity in bytes)
;   out:      A = the payload length on success, or $FFFF / $FFFE on the
;             two reject classes. The destination is UNTOUCHED on every
;             reject, which is what makes a failed load safe to ignore
;   clobbers: A, X, Y, N, Z, C, V
;   assumes:  the SRAM window is mapped. Verification runs before any
;             copy: magic, version, length and CRC
;   tail:     rts
sv_load:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "sv_load"
    jsr sv_check
    bne @reject                     ; the rejection code IS the return value
    lda z:SV_CAP
    cmp z:SV_LEN                    ; C = (cap >= stored length): it fits
    bcc @too_long                   ; stored length > dest capacity: reject
    lda z:SV_LEN
    beq @done                       ; a valid zero-length save copies nothing
    lda z:SV_SLOT
    clc
    adc #SV_HDR_SIZE
    tax
    ldy #0
    sep #$20
    .a8
; WIDTH-RISK: A8/I16 copy loop, same contract as @save_copy above.
@load_copy:
    .a8
    lda f:ES_S_SAVE_SLOTS_LONG, x
    sta [<SV_PTR], y                ; payload byte out (bank from the pointer)
    inx
    iny
    cpy z:SV_LEN
    bcc @load_copy
    rep #$20
    .a16
@done:                              ; fallthrough (A16) and beq from A16
    .a16
    lda z:SV_LEN
    rts
@reject:                            ; reached via bne in A16
    .a16
    rts
@too_long:                          ; reached via bcc in A16
    .a16
    ; hardening. Sv_check bounds the stored length against the SLOT's capacity
    ; (24), but a CRC-valid slot whose length exceeds the CALLER's dest used to
    ; copy right past it. REJECT with $FFFE — the corrupt-shaped code, like a
    ; wrong version: bytes that are internally consistent yet cannot be THIS
    ; caller's save ($FFFF stays reserved for "no magic at all"). Reject WHOLE,
    ; never clamp-and-copy: a silently truncated payload passing as valid is
    ; exactly the corruption class the gate exists to stop. Check precedes the
    ; copy — dest untouched.
    lda #$FFFE
    rts

; --- sv_exists: is there a VALID save? (magic + version + length + CRC) -----
; CONTRACT sv_exists
;   entry:    A16 I16
;   exit:     A16 I16
;   in:       SV_SLOT
;   out:      A = 1 if the slot holds a VALID save (magic, version, length
;             and CRC all agree), 0 otherwise. Nothing is copied
;   clobbers: A, X, Y, N, Z, C, V
;   assumes:  the SRAM window is mapped
;   tail:     rts
sv_exists:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "sv_exists"
    jsr sv_check
    bne @invalid
    lda #1
    rts
@invalid:                           ; reached via bne in A16
    .a16
    lda #0
    rts

; --- sv_clear: invalidate a slot (zero the magic; payload not wiped) --------
; In: SV_SLOT. Out: A = 0. In/out A16/I16. Clobbers A, X. After this, sv_exists
; answers 0 and sv_load answers $FFFF.
sv_clear:
    .a16
    .i16
    ldx z:SV_SLOT
    sep #$20
    .a8
    lda #0
    sta f:ES_S_SAVE_SLOTS_LONG, x
    sta f:ES_S_SAVE_SLOTS_LONG + 1, x
    rep #$20
    .a16
    lda #0
    rts

; --- sv_crc16: CRC-16/CCITT over SRAM [SV_SLOT .. SV_SLOT + SV_CLEN) --------
; In: SV_SLOT, SV_CLEN. Out: A = CRC. In/out A16/I16. Clobbers A, X, Y, SV_CRC,
; SV_TMP. Init = $FFFF, poly = $1021 via the 256-entry ROM LUT (crc16_lut_bin —
; the crc16_lut_rom claim's blob):
;
;  index = (CRC >> 8) ^ byte; CRC = (CRC << 8) ^ tab[index]
;
; The whole kernel runs A16 — zero width transitions. The byte fetch is a
; 16-bit read masked to its low byte; on the region's LAST byte that reads one
; byte past it, which is harmless by construction: read-only, masked off, and
; still inside the cart's DECLARED 2 KiB SRAM window (the claim's 64 B sit at
; its base — worst case is slot 1's final read touching offset 64 of 2048).
; Cheaper and width-safer than toggling A8/A16 around every byte.
sv_crc16:
    .a16
    .i16
    lda #$FFFF
    sta z:SV_CRC
    ldy #0
@loop:
    .a16
    cpy z:SV_CLEN
    beq @done
    tya
    clc
    adc z:SV_SLOT
    tax
    lda f:ES_S_SAVE_SLOTS_LONG, x   ; 16-bit read; low byte is the data
    and #$00FF
    sta z:SV_TMP
    lda z:SV_CRC
    xba
    and #$00FF                      ; (CRC >> 8)
    eor z:SV_TMP
    asl                             ; word index into the LUT
    tax
    lda f:crc16_lut_bin, x
    sta z:SV_TMP
    lda z:SV_CRC
    xba
    and #$FF00                      ; (CRC << 8)
    eor z:SV_TMP
    sta z:SV_CRC
    iny
    bra @loop
@done:
    .a16
    lda z:SV_CRC
    rts
