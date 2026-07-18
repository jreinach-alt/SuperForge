; =============================================================================
; input_handler.asm — Input Handler (E11) for SuperForge Engine
; =============================================================================
; Provides btn() and btnp() engine functions that read controller state
; from NMI-updated WRAM shadow registers.
;
; Calling convention (direct JSR):
;   X = button_id (0-11, see button_bitmask_table)
;   Y = player (0 = P1, 1 = P2)
;   Returns: 16-bit A = 0 (not pressed) or 1 (pressed)
;   Clobbers: A. Preserves X, Y.
;
; Button ID mapping:
;   0=Left, 1=Right, 2=Up, 3=Down,
;   4=Button A (SNES A), 5=Button B (SNES B),
;   6=L Shoulder, 7=R Shoulder, 8=Start, 9=Select,
;   10=X (SNES X), 11=Y (SNES Y)
;
; Prerequisites: engine_state.inc included, .p816/.smart set, DB=$00.
; NMI handler must be active (updates joy state each frame).
;
; Cross-ref: engine_state.inc, nmi_handler.asm (Phase 6)
; =============================================================================

; --- btn(button_id, player) ---
; Returns 1 if the button is currently held, 0 otherwise.
; Reads from joy{player}_current.
engine_btn:
    rep #$20
    .a16
    phx                         ; Save original X (button_id)
    txa
    asl                         ; button_id * 2 (table entries are 16-bit)
    tax
    lda button_bitmask_table, x ; Load bitmask from ROM table
    plx                         ; Restore original X

    ; Select controller based on player index
    cpy #$0000
    bne @btn_p2
    and JOY1_CURRENT            ; P1: AND with current state
    bra @btn_result
@btn_p2:
    and JOY2_CURRENT            ; P2: AND with current state
@btn_result:
    beq @btn_zero
    lda #$0001                  ; Button is held
    rts
@btn_zero:
    lda #$0000                  ; Button is not held
    rts

; --- btnp(button_id, player) ---
; Returns 1 if the button was newly pressed this frame (rising edge), 0 otherwise.
; Reads from joy{player}_pressed.
engine_btnp:
    rep #$20
    .a16
    phx                         ; Save original X
    txa
    asl                         ; button_id * 2
    tax
    lda button_bitmask_table, x ; Load bitmask
    plx                         ; Restore original X

    ; Select controller based on player index
    ; Read from LATCH (stable snapshot set by frame lifecycle INPUT phase)
    ; instead of raw PRESSED (which NMI can overwrite mid-frame)
    cpy #$0000
    bne @btnp_p2
    and JOY1_PRESSED_LATCH      ; P1: AND with latched pressed (rising edge)
    bra @btnp_result
@btnp_p2:
    and JOY2_PRESSED_LATCH      ; P2: AND with latched pressed (rising edge)
@btnp_result:
    beq @btnp_zero
    lda #$0001                  ; Button was just pressed
    rts
@btnp_zero:
    lda #$0000                  ; Button was not just pressed
    rts

; --- Button Bitmask Lookup Table ---
; Maps engine button IDs (0-11) to SNES hardware joypad register bitmasks.
; Each entry is 16-bit, matching the format of $4218/$421A reads.
;
; SNES joypad register format ($4218 JOY1):
;   Bit 15: B ($8000)    Bit 14: Y ($4000)
;   Bit 13: Select ($2000) Bit 12: Start ($1000)
;   Bit 11: Up ($0800)   Bit 10: Down ($0400)
;   Bit 9:  Left ($0200) Bit 8:  Right ($0100)
;   Bit 7:  A ($0080)    Bit 6:  X ($0040)
;   Bit 5:  L ($0020)    Bit 4:  R ($0010)
;   Bits 3-0: unused
button_bitmask_table:
    .word $0200                 ;  0: Left
    .word $0100                 ;  1: Right
    .word $0800                 ;  2: Up
    .word $0400                 ;  3: Down
    .word $0080                 ;  4: Button A (SNES A)
    .word $8000                 ;  5: Button B (SNES B)
    .word $0020                 ;  6: L Shoulder
    .word $0010                 ;  7: R Shoulder
    .word $1000                 ;  8: Start
    .word $2000                 ;  9: Select
    .word $0040                 ; 10: X (SNES X)
    .word $4000                 ; 11: Y (SNES Y)

; Number of defined button IDs
BUTTON_ID_MAX = 11
