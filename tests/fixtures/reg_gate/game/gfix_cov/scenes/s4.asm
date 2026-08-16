; reg-gate fixture (FIRES, item 5 / M4b): the `covered` arm.
;
; $211B M7A is in this scene's closure ONLY because an hdma claim NAMES it —
; nothing declares it on a [[claims.reg]] at all. Before M4b that made it
; freely writable from scene code, and narrowing only the `declared` arm would
; have left it that way: measured on the real tree, that leaves M7A-M7D and
; COLDATA writable from race.asm and WH0/WH1 from room.asm with ZERO findings.
;
; This is plant D's committed shape.
.p816
s4_enter:
    sep #$20
    .a8
    lda #$01
    sta a:$211B                 ; M7A — covered by an hdma claim only: FINDING
    rts
