; =============================================================================
; pfs_stream.asm — 2-axis leading-edge streaming for a NORMAL-BG 64x64 ring
; =============================================================================
; The mechanism `feature.toml` describes. Read that file first: it carries the
; design rationale and the binding contract this file implements.
;
; THE ONE HARDWARE FACT EVERYTHING TURNS ON. A 64x64 BG tilemap is FOUR 32x32
; hardware WORD pages, not one rectangle:
;
;  VRAM(col,row) = base + (col>=32 ? $400: 0) <- SC1/SC3, horizontally
;  + (row>=32 ? $800: 0) <- SC2/SC3, vertically
;  + (row & 31)*32 + (col & 31)
;
; So every staged line crosses a page boundary, on both axes, always — which is
; why each line is TWO 32-word sub-transfers rather than one 64-word one, and
; why `mode7_stream`'s flat-byte-array addressing reaches none of this.
;
; ONE STAGING SHAPE FOR BOTH AXES. A line is staged into a 64-word
; WRAM slot buffer indexed by RING SLOT, then drained as two page-aligned DMAs.
; The axes differ in exactly three values, all of them carried per-slot in the
; meta table:
;
;  axis | staged as | dest A | dest B | VMAIN
;  --------|-----------------------|---------------------|---------|--------
;  column | buf[world_row & 63] | base+hpage+(sc&31) | +$800 | +32
;  row | buf[world_col & 63] | base+vpage+(sr&31)*32| +$400 | +1
;
; POSITION-WRAPPED WRITES, always. A staged world line lands at buffer index
; `world & 63` — never at a sequential buffer index. The hardware reads ring
; slot `wc & 63` for world column wc no matter where the camera is, so a
; sequentially-filled buffer looks perfect in isolation and maps to the wrong
; VRAM positions the moment the window is not slot-aligned. The Mode 7 streamer
; has exactly the same trap, for exactly the same reason.
;
; THE WRAP IS ONLY EVER TWO SPANS, ON BOTH AXES — and the cut is derivable
; rather than searched for. A staged line reads 64 consecutive world lines out
; of a 128-line world while the ring dest wraps at slot 64. Let w0 be the
; window start:
;
;  source wraps after 128 - w0 (world index passes 128)
;  dest wraps after 64 - (w0 & 63) (buffer index passes 64)
;
;  w0 < 64: source wrap >= 64 >= dest wrap, so the DEST cut comes first
;  w0 >= 64: 128 - w0 == 64 - (w0 - 64) == 64 - (w0 & 63) — they COINCIDE
;
; Either way the first span is exactly `64 - (w0 & 63)` tiles and the second is
; the remainder, and both are source-contiguous. That is what lets both
; producers be a straight MVN block move instead of a strided copy loop, and it
; is why `pfs_rom` carries the level twice in two orders.
;
; THE CLAMP IS 2 TILES/AXIS/FRAME AND THERE IS NO SNAP-TO-CAM. Worst real
; displacement is 1 tile/frame/axis (terminal fall 4 px/f, jump take-off 4.5
; px/f), so the clamp is margin and the skipped-tile case cannot arise.
; Snapping LAST to CAM when a delta exceeds the clamp is the anti-pattern: the
; skipped columns keep stale VRAM from 64 world columns ago, so the corruption
; is systematic rather than transient. The only honest way to have a clamp is
; to set it where it cannot bite.
;
; MEASURED, not estimated (CLAUDE.md rule 1): the per-line staging cost is
; measured on the emulator by `vendor/probes/probe_pfs_stream.asm`, which
; `.include`s THIS FILE rather than a copy of it, so the published figure
; always describes the shipped kernel. `tests/test_pfs_stream.py` reads the BG1
; VRAM tilemap words back and compares them to the authored level tile for
; tile, in all four directions and at rest.
;
; =============================================================================
; THE BINDING CONTRACT — five symbols, supplied by the includer, no defaults
; =============================================================================
; `schemas.py` has no vocabulary for "same feature, different blob", so the
; binding is `col_map.asm`'s / `mode7_stream.asm`'s shape: symbols the includer
; defines immediately above its `.include`, each missing one a hard
; `.error` naming it, and NO DEFAULT. `rgb_gradient` records why a default is
; refused — "a silent default is exactly how the platformer inherited a wash on
; its terrain and shipped a teal sky" — and it holds here too: a defaulted blob
; streams the wrong ROM bytes into a plausible-looking level.
;
;  PFS_COL_WIN the COLUMN-major blob's ES_R_<name>_T0_ADDR (window base)
;  PFS_COL_BANK the COLUMN-major blob's ES_R_<name>_T0_BANK
;  PFS_ROW_WIN the ROW-major blob's ES_R_<name>_T0_ADDR
;  PFS_ROW_BANK the ROW-major blob's ES_R_<name>_T0_BANK
;  PFS_MAP_BASE the ring's VRAM WORD base — pfs_bg's ES_V_<name> (the
;  `_SC_BASE` companion is the REGISTER encoding and is the
;  scene's business, not this file's)
;
; NO CONSECUTIVE-BANKS OBLIGATION HERE, and that is a property of the blobs
; rather than a hole. Each is exactly 32,768 B = ONE LoROM window = one chunk,
; so nothing in this file ever derives a bank as BASE+i and there is no
; relationship between chunks to assert. What the includer DOES owe is the
; assert that each blob really is one chunk (m7_dungeon's shape) — if one grew
; past a window the source pointer would silently walk off the end of bank
; PFS_*_BANK into whatever the linker packed next.
;
; `depends` is therefore []: this feature depends on whatever the GAME binds.
; Losing the allocator's `depends` check is not losing the check; it is
; replaced by an assembly-time one, which this repo treats as the stronger
; signal ("the undefined-symbol error is the design review").
;
; STATED LIMIT, deliberately, and it is `mode7_stream`'s: the WORLD SIZE is
; baked (128x128) rather than bound. It is not free-floating — it is forced by
; the contract's own "each blob is exactly one LoROM window" property, since
; 128 x 128 x 2 B = 32,768 B exactly, which is also what makes a column's
; 128-word run contiguous and a source pointer unable to cross a bank seam. A
; rail wanting a different world changes the blob SHAPE, not a constant, so
; generalising this would be a strictly larger change with no caller.
;
; NOTHING IN THIS FILE CAN REFUSE A WRONG-SIZED BLOB, and an earlier draft of
; this paragraph claimed otherwise ("the asserts below refuse the mismatch") —
; the asserts below check this feature's own CLAIM sizes (pfs_slots, pfs_meta,
; pfs_hot) and say nothing about the world. They could not: the binding hands
; this file an ADDR and a BANK per blob and no size, so the only place the
; 128x128 assumption is checkable is the includer, which has the blob's
; `ES_R_<name>_SIZE` in scope:
;
;  .assert ES_R_<col>_SIZE = 128 * 128 * 2, error, "..."
;
; AND THAT ONE LINE IS ALSO THE ONE-CHUNK ASSERT the paragraph above asks for
; — it is not a third obligation. The literal form ("`.assert
; ES_R_<col>_CHUNKS = 1`") CANNOT BE WRITTEN: `allocate.py::_placement_lines`
; emits `_CHUNKS` only for placements with `kind == "chunk"`, i.e. For a
; `bank_tiled` claim, and a plain `rom` claim like these two emits
; `_BANK`/`_OFF`/`_ADDR`/`_SIZE` and nothing else (`grep CHUNKS` over either
; composition's emitted .inc returns nothing). Since a chunk IS one 32 KB
; window, `SIZE = 32768` says `CHUNKS = 1` — and says it more strongly, because
; it also refuses an UNDER-sized blob. `game/platformer_stream/scenes/play.asm`
; carries the same reasoning at length for col_map's sibling case.
;
; BOTH LIVE COMPOSITIONS ALREADY DISCHARGE IT, on both blobs:
; `game/platformer_stream/scenes/play.asm:101-102` (landed in cc97d54, after
; review's tip, which is why an earlier draft of this sentence said only the
; probe did and that a rail "owes the same line" — it does not; it pays it),
; and `vendor/probes/probe_pfs_stream.asm` beside its two placement asserts. A
; rail binding DIFFERENT blobs still owes it. Both asserts are live: review §7
; broke each in turn and the build stopped. Audit trail: the audit record, the
; audit record. The baked 128 shows up at runtime as the two `xba` line-base
; multiplies (a 128-word row stride) in pfs_stage_col / pfs_stage_row.

; --- the binding, checked before anything else ------------------------------
; One `.error` per symbol, naming that symbol, so an incomplete binding says
; WHICH one is missing rather than failing on a downstream range error. The
; `.ifndef` form is col_map.asm's and rgb_gradient.asm's; no branch supplies a
; default.
.ifndef PFS_COL_WIN
    .error "pfs_stream: the includer must define PFS_COL_WIN (the COLUMN-major tilemap blob's ES_R_<name>_T0_ADDR) before including this file"
.endif
.ifndef PFS_COL_BANK
    .error "pfs_stream: the includer must define PFS_COL_BANK (the COLUMN-major tilemap blob's ES_R_<name>_T0_BANK) before including this file"
.endif
.ifndef PFS_ROW_WIN
    .error "pfs_stream: the includer must define PFS_ROW_WIN (the ROW-major tilemap blob's ES_R_<name>_T0_ADDR) before including this file"
.endif
.ifndef PFS_ROW_BANK
    .error "pfs_stream: the includer must define PFS_ROW_BANK (the ROW-major tilemap blob's ES_R_<name>_T0_BANK) before including this file"
.endif
.ifndef PFS_MAP_BASE
    .error "pfs_stream: the includer must define PFS_MAP_BASE (the ring's VRAM word base — pfs_bg's ES_V_<name>) before including this file"
.endif

; --- geometry, all folded at ASSEMBLY time ----------------------------------
; Every value >= 256 below is built out of small factors rather than written as
; a literal. That is not decoration: `no_literals` value-checks assignments and
; immediates in EVERY base, and $400 happens to land inside an emitted WRAM
; claim's 16-bit offset range in this composition. Deriving the constant states
; where it comes from and stays legal by construction.
PFS_TILES      = 128                    ; world dimension, tiles (both axes)
PFS_RING       = 64                     ; ring dimension, tiles (both axes)
PFS_HALF       = 32                     ; ONE hardware page dimension
PFS_BACK       = 16                     ; tiles of window kept BEHIND the camera
PFS_CLAMP      = 2                      ; staged lines per axis per frame
PFS_SLOTS_MAX  = 4                      ; = 2 axes x PFS_CLAMP

PFS_PAGE_W     = PFS_HALF * PFS_HALF    ; 1024 words in one 32x32 page
PFS_PAGE_H     = PFS_PAGE_W             ; horizontal page step (SC1/SC3)
PFS_PAGE_V     = PFS_PAGE_W * 2         ; vertical page step   (SC2/SC3)

PFS_LINE_B     = PFS_RING * 2           ; 128 B — one staged line, 64 words
PFS_HALF_B     = PFS_HALF * 2           ; 64 B  — one page sub-transfer
PFS_META_STRIDE = 8                     ; per-slot meta record size

; The entering-edge offset when the camera steps FORWARD: the new window's last
; element is at `new_last - BACK + RING - 1`.
PFS_LEAD       = PFS_RING - 1 - PFS_BACK

; VMAIN: bit 7 = increment after the $2119 (high) write, which is what a
; word-port mode-1 transfer needs; bits 1-0 select the step.
PFS_VMAIN_ROW  = $80                    ; +1 word   — a row walks along a page
PFS_VMAIN_COL  = $81                    ; +32 words — a column walks down one

; The declared shapes this file assumes, asserted rather than trusted.
.assert ES_PFS_SLOTS_SIZE = PFS_SLOTS_MAX * PFS_LINE_B, error, "pfs_slots is not 4 x 128 B — pfs_stream's slot indexing assumes it"
.assert ES_PFS_META_SIZE = PFS_SLOTS_MAX * PFS_META_STRIDE, error, "pfs_meta is not 4 x 8 B — pfs_stream's meta indexing assumes it"
.assert ES_PFS_HOT_SIZE = 24, error, "pfs_hot is not 24 B — the DP field aliases below would run off the claim"

; $7E0000, derived from the emitted pair rather than narrated — the same idiom
; mode7_stream uses for its STREAM_WRAM.
PFS_WRAM       = ES_PFS_SLOTS_LONG - ES_PFS_SLOTS

; The two channel register files. `$4300 + <claim>_CH * 16` is the idiom
; no_literals exempts by name; the channel index is always allocator-emitted.
PFSS_REGS      = $4300 + ES_H_PFSS_CH * 16      ; the per-frame vblank drain
PFSF_REGS      = $4300 + ES_D_PFS_FILL_CH * 16  ; the enter-time ring fill

; --- DP field aliases (ES_PFS_HOT layout, feature.toml) ---------------------
PFS_CAM_TX  = ES_PFS_HOT + 0    ; camera tile x (0..127) — the TARGET
PFS_CAM_TY  = ES_PFS_HOT + 2
PFS_LAST_TX = ES_PFS_HOT + 4    ; the tile position the RING actually holds
PFS_LAST_TY = ES_PFS_HOT + 6
PFS_COL_CNT = ES_PFS_HOT + 8    ; column slots staged this frame (u8, 0..2)
PFS_ROW_CNT = ES_PFS_HOT + 9    ; row slots staged this frame    (u8, 0..2)
PFS_K0      = ES_PFS_HOT + 10   ; the world line being staged
PFS_K1      = ES_PFS_HOT + 12   ; source line base inside the blob's window
PFS_K2      = ES_PFS_HOT + 14   ; span cursor: world index on the varying axis
PFS_K3      = ES_PFS_HOT + 16   ; span length, tiles
PFS_K4      = ES_PFS_HOT + 18   ; dest slot buffer base (WRAM 16-bit offset)
PFS_K5      = ES_PFS_HOT + 20   ; pfs_stream_arm's fill counter (stage-safe)
PFS_K6      = ES_PFS_HOT + 22   ; the MVN stub address for this line's blob

; --- ES_PFS_NMI: the two bytes that keep the tick and the drain apart -------
; The tick runs on the MAIN thread and the drain runs in the NMI, so they
; genuinely interleave — and a slot is only well-defined once its meta AND its
; buffer AND its count have all landed. An NMI that fired between the buffer
; fill and the `inc` would drain n slots, zero the counts, and then watch the
; interrupted stage's `inc` publish a count of 1 pointing at slot 0 while the
; data sat in slot n: a whole line silently lost, on a timing edge, with the
; ring left holding a stale strip.
;
; So the main thread raises PFS_BUSY across its whole staging window and the
; drain simply DEFERS — the slots stay pending and go out at the next VBlank.
; Deferring is free here because the clamp is per-axis and the counters are NOT
; reset by the tick: a deferred frame leaves COL_CNT/ROW_CNT standing, the next
; tick's clamp refuses to stage past them, LAST therefore does not advance, and
; nothing is skipped. It self-heals in one frame, which is what the
; CLAMP=2-against-a-real-max-of-1 margin is actually for.
;
; A single-byte store is indivisible against an interrupt on this CPU, so the
; flag needs no stronger protection than being one byte.
PFS_BUSY    = ES_PFS_NMI + 0    ; main thread is mid-stage; the drain defers
PFS_LEFT    = ES_PFS_NMI + 1    ; the drain's remaining-slot counter
.assert ES_PFS_NMI_SIZE = 2, error, "pfs_nmi is not 2 B — PFS_BUSY/PFS_LEFT would run off the claim"

; =============================================================================
; pfs_stream_init — the [init] zero contract, as CODE
; =============================================================================
; CONTRACT pfs_stream_init
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the whole hot block zeroed — the tracking state's
;             write-before-read establishment (rule 5)
;   clobbers: A, X, N, Z
;   assumes:  ONCE, before the first arm
;   tail:     rts
;
; `[init] zero` HAS NO GATE: the allocator emits the contract as a comment and
; nothing checks that anybody honoured it. `mosaic` shipped declaring it with
; no code behind it — a non-zero `state` byte at boot is a wipe nobody armed —
; and only Mesen's random power-on RAM caught it. So this routine exists, and
; `tests/test_pfs_stream.py` reads the declared bytes back after it runs rather
; than trusting the declaration.
;
; WIDTH-RISK: entered A16/I16 and stays there. The `bpl` loops step X by 2 and
; exit on the wrap to $FFFE, which requires I16 — an I8 caller would spin.
pfs_stream_init:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "pfs_stream_init"
    ldx #(ES_PFS_HOT_SIZE - 2)
:   stz z:ES_PFS_HOT, x
    dex
    dex
    bpl :-
    ldx #(ES_PFS_NMI_SIZE - 2)
:   stz z:ES_PFS_NMI, x
    dex
    dex
    bpl :-
    rts

; =============================================================================
; pfs_stream_set_cam — the camera, in the game's units
; =============================================================================
; CONTRACT pfs_stream_set_cam
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = the camera's world pixel X, X = its world pixel Y
;   out:      CAM_TX / CAM_TY updated. NOTHING is staged — this only moves
;             the tracker
;   clobbers: A, N, Z, C
;   assumes:  the caller stages separately, through pfs_stream_tick
;   tail:     rts
;
; A16/I16. Clobbers A. CAM_TX/CAM_TY updated; nothing is staged.
;
; The camera arrives as a PARAMETER rather than being read out of some other
; feature's claim, which is col_map's precedent and the better one: deciding
; WHICH window to show is the game's business, and a feature that reached for
; `pfs_bg`'s ES_PFS_CAM could no longer be built without it (nor measured by a
; probe that composes neither).
;
; WIDTH-RISK: entered A16/I16 — X carries a 16-bit pixel coordinate, so an I8
; caller would truncate the camera's Y to its low byte silently.
pfs_stream_set_cam:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "pfs_stream_set_cam"
    lsr
    lsr
    lsr
    and #(PFS_TILES - 1)
    sta z:PFS_CAM_TX
    txa
    lsr
    lsr
    lsr
    and #(PFS_TILES - 1)
    sta z:PFS_CAM_TY
    rts

; =============================================================================
; pfs_stream_arm — fill the WHOLE ring, through the per-frame staging path
; =============================================================================
; CONTRACT pfs_stream_arm
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      the seed window uploaded and the tracking counters seeded
;             level with it
;   clobbers: A, X, Y, N, Z, C, V
;   assumes:  forced blank, at scene enter. Tracking starts in sync with
;             the seed upload and this routine does not verify it
;   tail:     rts
;
; CALLER CONTRACT: forced blank asserted AND NMI masked. Forced blank alone is
; not enough — `$2100 = $80` blanks the display but NMI is still governed by
; `$4200` bit 7 and fires every VBlank regardless, and an NMI that ran
; `pfs_stream_nmi_dispatch` (or any other VRAM writer) mid-fill would reprogram
; VMADD under this loop and scatter the rest of the ring across VRAM. The
; scene_mgr enter contract already holds both, which is why this is a
; precondition rather than a save/restore here.
;
; Requires `pfs_stream_init` then `pfs_stream_set_cam` to have run: this sets
; LAST from CAM and fills the 64 columns of the window around it.
;
; IT REUSES THE PER-FRAME STAGING KERNEL — 64 calls to `pfs_stage_col`, each
; into slot 0, each fired immediately on the forced-blank fill channel. Not
; because a bulk upload would be hard, but because a second upload path is a
; second chance to be right: with one kernel, a bug in the addressing CANNOT
; hide behind a correct boot frame. It costs nothing — forced blank, once.
;
; WIDTH-RISK: entered A16/I16; the inner `sep #$20` blocks program 8-bit
; channel bytes and every label after one carries its own annotation. The index
; width is NEVER touched: `pfs_stage_col` and the fire block below both need
; I16 (16-bit meta indices and A-bus cursors).
pfs_stream_arm:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "pfs_stream_arm"
    lda z:PFS_CAM_TX
    sta z:PFS_LAST_TX
    lda z:PFS_CAM_TY
    sta z:PFS_LAST_TY
    ; --- program the forced-blank fill channel once -------------------------
    sep #$20
    .a8
    lda #ES_D_PFS_FILL_DMAP
    sta a:PFSF_REGS + 0             ; DMAP: mode 1, A->B (word port)
    lda #ES_D_PFS_FILL_BBAD
    sta a:PFSF_REGS + 1             ; BBAD: VMDATAL
    lda #ES_PFS_SLOTS_BANK
    sta a:PFSF_REGS + 4             ; A1B: the slot buffers' bank
    rep #$20
    .a16
    stz z:PFS_K5                    ; the fill counter, 0..63
@fill:
    .a16
    stz z:PFS_COL_CNT               ; A16 store: zeroes COL_CNT *and* ROW_CNT,
                                    ; so every column stages into slot 0
    lda z:PFS_LAST_TX
    sec
    sbc #PFS_BACK
    clc
    adc z:PFS_K5
    and #(PFS_TILES - 1)
    sta z:PFS_K0                    ; the world column to stage
    jsr pfs_stage_col
    ldx #0                          ; slot 0's meta record
    ldy #ES_PFS_SLOTS               ; slot 0's buffer
    ; ---- fire slot 0 on the FILL channel, two page sub-transfers -----------
    sep #$20
    .a8
    lda a:ES_PFS_META + 4, x
    sta a:$2115                     ; VMAIN: this line's axis stride
    rep #$20
    .a16
    lda a:ES_PFS_META + 0, x
    sta a:$2116                     ; VMADD: sub-transfer A
    tya
    sta a:PFSF_REGS + 2             ; A1T
    lda #PFS_HALF_B
    sta a:PFSF_REGS + 5             ; DAS
    sep #$20
    .a8
    lda #(1 << ES_D_PFS_FILL_CH)
    sta a:$420B
    rep #$20
    .a16
    lda a:ES_PFS_META + 2, x
    sta a:$2116                     ; VMADD: sub-transfer B (the other page)
    tya
    clc
    adc #PFS_HALF_B
    sta a:PFSF_REGS + 2             ; A1T
    lda #PFS_HALF_B
    sta a:PFSF_REGS + 5             ; DAS — RE-ARMED. It is single-shot: each
                                    ; MDMAEN write consumes it, so a second
                                    ; transfer off one arming moves ZERO bytes.
    sep #$20
    .a8
    lda #(1 << ES_D_PFS_FILL_CH)
    sta a:$420B
    rep #$20
    .a16
    ; ---- next column -------------------------------------------------------
    lda z:PFS_K5
    inc
    sta z:PFS_K5
    cmp #PFS_RING
    bcc @fill
    stz z:PFS_COL_CNT               ; A16: both counts back to zero — the ring
    rts                             ; is whole, nothing is pending

; =============================================================================
; pfs_stream_tick — camera delta -> staged slots
; =============================================================================
; CONTRACT pfs_stream_tick
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      this frame's leading-edge rows and columns staged, clamped
;             to the quota
;   clobbers: A, X, Y, N, Z, C, V
;   assumes:  once per frame, AFTER the game has moved the camera. The
;             staging is main thread; the transfer is
;             pfs_stream_nmi_dispatch's
;   tail:     rts
;
; has moved the camera and called `pfs_stream_set_cam`.
;
; Walks LAST toward CAM one tile at a time per axis, staging the entering edge
; each step, and STOPS at the clamp — it never snaps LAST to CAM.
;
; IT DOES NOT RESET THE COUNTERS; the DRAIN does, after the slots have gone
; out. So a frame whose drain deferred (see ES_PFS_NMI above) arrives here with
; COL_CNT/ROW_CNT already standing, the clamps below refuse to stage past them,
; LAST does not advance, and nothing is skipped — the deferral costs one frame
; of ring lag and self-heals. That is what makes the clamp's margin (2 against
; a real worst case of 1) load-bearing rather than decorative.
;
; A STAGED LINE SPANS THE OTHER AXIS' WINDOW, AND IT MUST BE **LAST**'s, NOT
; CAM's. A staged row covers the ring's 64 columns; the ring holds the window
; around LAST_TX, and CAM_TX may be one or two tiles ahead of it. Stage the row
; over CAM_TX's window and 1-2 ring slots receive world columns that are not in
; the window at all. The mirror argument holds for a column against LAST_TY.
;
; THE WALK ORDER IS **NOT** LOAD-BEARING, and an earlier draft of this comment
; claimed it was ("ROWS ARE WALKED FIRST, AND THE ORDER IS LOAD-BEARING"). It
; is not, and the claim mattered because it made the LAST-vs-CAM choice look
; already-covered when nothing covered it. When BOTH walks complete, they are
; mutually self-correcting: whichever runs second rewrites exactly the line the
; first got wrong. Row-first, the column walk then stages world column
; LAST_TX+48 into slot (LAST_TX-16) & 63 — the one slot where the old and new
; horizontal windows disagree. Column-first, the row walk stages world row
; LAST_TY+48 across all 64 columns, which is the line the column walk got
; wrong. Symmetric, in both orders. Review swapped the two walks and all tests
; stayed green; the swap is still green against the suite as it stands which is
; the evidence for this paragraph rather than a re-reasoned assertion.
;
; WHERE LAST REALLY EARNS ITS KEEP is the frame where the OTHER axis' walk
; performs no correction — because it is clamped, or because it is carrying a
; deferred count and refuses to stage at all. Then a line staged over CAM's
; window leaves those 1-2 slots wrong and nothing fixes them. That state is the
; reason for `LAST`, and `tests/test_pfs_stream.py`'s T11 reaches it with a
; 3-tile jump against the 2-tile clamp: with CAM_TX substituted here, exactly
; the 2 predicted ring words come back wrong.
;
; The row walk still runs first. With the order not load-bearing that is a free
; choice, kept because it reads in the same order as the axis table at the top
; of this file.
;
; WIDTH-RISK: entered A16/I16 and every branch target below is annotated .a16
; against a same-file arrival; the two `sep #$20` regions are the u8 count
; reads and each re-widens before its branch. The `beq`/`bcs` chain reads
; mod-128 differences, so I16 is required for the `and #127` masks to be 16-bit
; operations.
pfs_stream_tick:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "pfs_stream_tick"
    sep #$20
    .a8
    lda #1
    sta z:PFS_BUSY                  ; the drain defers for this window
    rep #$20
    .a16
@walk_ty:
    .a16
    lda z:PFS_CAM_TY
    sec
    sbc z:PFS_LAST_TY
    and #(PFS_TILES - 1)
    beq @ty_done
    lda z:PFS_ROW_CNT
    and #255
    cmp #PFS_CLAMP
    bcs @ty_done                    ; clamp reached — rest next frame, NO SNAP
    lda z:PFS_CAM_TY
    sec
    sbc z:PFS_LAST_TY
    and #(PFS_TILES - 1)
    cmp #(PFS_TILES / 2)
    bcs @ty_step_back               ; a mod-128 difference >= 64 is backwards
    ; step +1: the entering edge is the new window's LAST line
    lda z:PFS_LAST_TY
    inc
    and #(PFS_TILES - 1)
    sta z:PFS_LAST_TY
    clc
    adc #PFS_LEAD
    and #(PFS_TILES - 1)
    bra @ty_stage
@ty_step_back:
    .a16
    ; step -1: the entering edge is the new window's FIRST line
    lda z:PFS_LAST_TY
    dec
    and #(PFS_TILES - 1)
    sta z:PFS_LAST_TY
    sec
    sbc #PFS_BACK
    and #(PFS_TILES - 1)
@ty_stage:
    .a16
    sta z:PFS_K0
    jsr pfs_stage_row
    bra @walk_ty
@ty_done:
    .a16
@walk_tx:
    .a16
    lda z:PFS_CAM_TX
    sec
    sbc z:PFS_LAST_TX
    and #(PFS_TILES - 1)
    beq @tx_done
    lda z:PFS_COL_CNT
    and #255
    cmp #PFS_CLAMP
    bcs @tx_done
    lda z:PFS_CAM_TX
    sec
    sbc z:PFS_LAST_TX
    and #(PFS_TILES - 1)
    cmp #(PFS_TILES / 2)
    bcs @tx_step_back
    lda z:PFS_LAST_TX
    inc
    and #(PFS_TILES - 1)
    sta z:PFS_LAST_TX
    clc
    adc #PFS_LEAD
    and #(PFS_TILES - 1)
    bra @tx_stage
@tx_step_back:
    .a16
    lda z:PFS_LAST_TX
    dec
    and #(PFS_TILES - 1)
    sta z:PFS_LAST_TX
    sec
    sbc #PFS_BACK
    and #(PFS_TILES - 1)
@tx_stage:
    .a16
    sta z:PFS_K0
    jsr pfs_stage_col
    bra @walk_tx
@tx_done:
    .a16
    sep #$20
    .a8
    stz z:PFS_BUSY                  ; every staged slot is now fully published
    rep #$20
    .a16
    rts

; =============================================================================
; pfs_stage_col — K0 = world column c -> the next free slot
; =============================================================================
; CONTRACT pfs_stage_col
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      one column staged and COL_CNT bumped
;   clobbers: A, X, Y, N, Z, C, V, K1..K4 and K6
;   assumes:  the staging buffers have room — the tick's clamp is what
;             guarantees it
;   tail:     rts
;
; A column's 64 tiles are 64 consecutive world ROWS of one column, which is
; exactly what the COLUMN-major blob stores contiguously (col N's 128 words at
; N*256). The staged buffer is indexed by ring ROW slot; the two page
; sub-transfers are the ring's top 32 rows and its bottom 32, one $800 apart,
; both walked with VMAIN +32.
;
; WIDTH-RISK: entered A16/I16, exits A16/I16. The single `sep #$20` window
; writes the meta VMAIN byte and re-widens immediately; the index width is
; never touched because X holds a 16-bit meta offset throughout.
pfs_stage_col:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "pfs_stage_col"
    jsr _pfs_slot_base              ; A = slot buffer base, X = meta offset
    sta z:PFS_K4
    ; --- meta: VMADD for both pages, and the axis stride --------------------
    lda z:PFS_K0
    and #(PFS_RING - 1)             ; sc = ring column slot
    pha
    and #PFS_HALF                   ; the SC1/SC3 page bit
    asl
    asl
    asl
    asl
    asl                             ; 32 -> PFS_PAGE_H
    sta z:PFS_K1
    pla
    and #(PFS_HALF - 1)             ; sc within its page
    clc
    adc z:PFS_K1
    clc
    adc #PFS_MAP_BASE
    sta a:ES_PFS_META + 0, x        ; dest A: the ring's top 32 rows
    clc
    adc #PFS_PAGE_V
    sta a:ES_PFS_META + 2, x        ; dest B: the bottom 32 (SC2/SC3)
    sep #$20
    .a8
    lda #PFS_VMAIN_COL
    sta a:ES_PFS_META + 4, x
    rep #$20
    .a16
    ; --- source: the column's contiguous 128-word run -----------------------
    lda z:PFS_K0
    and #(PFS_TILES - 1)
    xba                             ; * 256 (the run is 128 words = 256 B)
    clc
    adc #PFS_COL_WIN
    sta z:PFS_K1
    lda #.loword(_pfs_mvn_col)
    sta z:PFS_K6
    ; --- the OTHER axis' window start: what the ring currently holds --------
    lda z:PFS_LAST_TY
    sec
    sbc #PFS_BACK
    and #(PFS_TILES - 1)
    jsr _pfs_copy_line
    sep #$20
    .a8
    inc z:PFS_COL_CNT
    rep #$20
    .a16
    rts

; =============================================================================
; pfs_stage_row — K0 = world row r -> the next free slot
; =============================================================================
; CONTRACT pfs_stage_row
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   out:      one row staged and ROW_CNT bumped
;   clobbers: A, X, Y, N, Z, C, V, K1..K4 and K6
;   assumes:  the staging buffers have room — the tick's clamp is what
;             guarantees it
;   tail:     rts
;
; The mirror of pfs_stage_col over the ROW-major blob: the two sub-transfers
; are the ring's left 32 columns and its right 32, one $400 apart, walked with
; VMAIN +1.
;
; WIDTH-RISK: identical contract to pfs_stage_col — A16/I16 in and out, one
; 8-bit window for the meta VMAIN byte, index width untouched.
pfs_stage_row:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "pfs_stage_row"
    jsr _pfs_slot_base
    sta z:PFS_K4
    ; --- meta ---------------------------------------------------------------
    lda z:PFS_K0
    and #(PFS_RING - 1)             ; sr = ring row slot
    pha
    and #PFS_HALF                   ; the SC2/SC3 page bit
    asl
    asl
    asl
    asl
    asl
    asl                             ; 32 -> PFS_PAGE_V
    sta z:PFS_K1
    pla
    and #(PFS_HALF - 1)             ; sr within its page
    asl
    asl
    asl
    asl
    asl                             ; * 32 words per page row
    clc
    adc z:PFS_K1
    clc
    adc #PFS_MAP_BASE
    sta a:ES_PFS_META + 0, x        ; dest A: the ring's left 32 columns
    clc
    adc #PFS_PAGE_H
    sta a:ES_PFS_META + 2, x        ; dest B: the right 32 (SC1/SC3)
    sep #$20
    .a8
    lda #PFS_VMAIN_ROW
    sta a:ES_PFS_META + 4, x
    rep #$20
    .a16
    ; --- source -------------------------------------------------------------
    lda z:PFS_K0
    and #(PFS_TILES - 1)
    xba
    clc
    adc #PFS_ROW_WIN
    sta z:PFS_K1
    lda #.loword(_pfs_mvn_row)
    sta z:PFS_K6
    lda z:PFS_LAST_TX
    sec
    sbc #PFS_BACK
    and #(PFS_TILES - 1)
    jsr _pfs_copy_line
    sep #$20
    .a8
    inc z:PFS_ROW_CNT
    rep #$20
    .a16
    rts

; =============================================================================
; _pfs_slot_base — where the next staged line goes
; =============================================================================
; In: A16/I16. Out: A = ES_PFS_SLOTS + n*128, X = n*8 (the meta offset),
;  where n = COL_CNT + ROW_CNT. Clobbers A, X.
;
; ONE POOL, BOTH AXES. Slots are handed out in staging order and each carries
; its own VMADD pair and VMAIN byte, so the drain walks 0..n-1 without caring
; which axis produced which. The two per-axis counters exist for the CLAMP, not
; for two pools. N <= PFS_SLOTS_MAX by construction: each axis stops at
; PFS_CLAMP and 2 x 2 = 4.
;
; WIDTH-RISK: entered A16/I16 and stays A16 — the `sep #$20` window is only the
; two u8 count reads, and `tax` is never executed in a mixed width here.
_pfs_slot_base:
    .a16
    .i16
    sep #$20
    .a8
    lda z:PFS_COL_CNT
    clc
    adc z:PFS_ROW_CNT
    rep #$20
    .a16
    and #255                        ; n, 0..PFS_SLOTS_MAX-1
    pha
    asl
    asl
    asl                             ; n * PFS_META_STRIDE
    tax
    pla
    xba
    lsr                             ; n * PFS_LINE_B
    clc
    adc #ES_PFS_SLOTS
    rts

; =============================================================================
; _pfs_copy_line — 64 world tiles -> one slot buffer, position-wrapped
; =============================================================================
; CONTRACT _pfs_copy_line
;   entry:    A16 I16 DB=0
;   exit:     A16 I16
;   in:       A = w0, the window start on the VARYING axis (0..127)
;   out:      one line copied into the staging buffer at its wrapped
;             position
;   clobbers: A, X, Y, N, Z, C, V, K2 and K3
;   assumes:  the caller has set the fixed axis and the source pointer
;   tail:     rts
;
;  K1 = source line base inside the blob's LoROM window.
;  K4 = dest slot buffer base (a 16-bit offset in bank PFS_WRAM).
;  K6 = the MVN stub for this line's blob bank.
; Out: A16/I16, DB=0. Clobbers A, X, Y, K2, K3.
;
; TWO SPANS, ALWAYS — see the header's derivation. The first is `64 - (w0 &
; 63)` tiles, which is simultaneously the dest wrap and (when w0 >= 64) the
; source wrap; the second is the remainder, and is skipped when the first
; covered all 64.
;
; WIDTH-RISK: A16/I16 throughout; no width toggle in this routine or in
; _pfs_mvn_span. MVN needs both (it moves C+1 bytes and uses 16-bit X/Y).
_pfs_copy_line:
    .a16
    .i16
    SF_ASSERT_WIDTH 16, 16, "_pfs_copy_line"
    sta z:PFS_K2                    ; the span cursor starts at w0
    and #(PFS_RING - 1)
    eor #(PFS_RING - 1)
    inc                             ; 64 - (w0 & 63), i.e. 1..64
    sta z:PFS_K3
    jsr _pfs_mvn_span               ; ...advances K2 past this span
    lda #PFS_RING
    sec
    sbc z:PFS_K3                    ; the remainder, 0..63
    beq @spans_done
    sta z:PFS_K3
    jsr _pfs_mvn_span
@spans_done:
    .a16
    rts

; _pfs_mvn_span — move K3 tiles starting at world index K2. A16/I16, DB=0 in
; and out; advances K2 by K3 (mod 128).
;
; WIDTH-RISK: MVN uses the full 16-bit C register regardless of the M flag and
; both 16-bit index registers, and it leaves DB = the DESTINATION bank ($7E).
; The phb/plb pair around the call is what returns DB to the caller's 0 — drop
; it and the caller's next absolute store lands in WRAM.
_pfs_mvn_span:
    .a16
    .i16
    lda z:PFS_K2
    asl                             ; tiles -> bytes
    clc
    adc z:PFS_K1
    tax                             ; source: the blob's contiguous run
    lda z:PFS_K2
    and #(PFS_RING - 1)             ; POSITION-WRAPPED: ring slot, not a
    asl                             ;   sequential buffer index
    clc
    adc z:PFS_K4
    tay
    lda z:PFS_K3
    asl
    dec                             ; MVN moves C+1 bytes
    phb
    jsr _pfs_do_mvn
    plb
    lda z:PFS_K2
    clc
    adc z:PFS_K3
    and #(PFS_TILES - 1)
    sta z:PFS_K2
    rts

; The indirect jump reads its pointer from ES_PFS_HOT+22 as an ABSOLUTE bank-0
; address, which is the same byte as the DP alias only because init.inc pins
; DP = $0000 for the program's life (vendor/rom/init.inc:34, the tree's one
; `tcd`). Mode7_stream's stub dispatch rests on the identical property.
;
; WIDTH-RISK: entered A16/I16 from _pfs_mvn_span with C = byte count - 1; every
; stub leaves DB = $7E and returns A16/I16.
_pfs_do_mvn:
    .a16
    .i16
    jmp (PFS_K6)

; One 3-byte MVN + rts per blob. Ca65 encodes MVN operands DST-BANK-FIRST (the
; scene_mgr quirk note), and emitting the bytes makes that explicit rather than
; depending on the mnemonic's operand order.
_pfs_mvn_col:
    .byte $54, ES_PFS_SLOTS_BANK, PFS_COL_BANK
    rts
_pfs_mvn_row:
    .byte $54, ES_PFS_SLOTS_BANK, PFS_ROW_BANK
    rts

; =============================================================================
; pfs_stream_nmi_dispatch — drain the staged slots as GP-DMA
; =============================================================================
; CONTRACT pfs_stream_nmi_dispatch
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   out:      every staged row and column transferred, and the counters
;             cleared
;   clobbers: A, X, Y, N, Z, C, V
;   assumes:  VBlank, from the rail's sm_nmi_hook, in that hook's A8/I16
;             convention. DAS is single-shot, so it is re-armed inside the
;             slot loop rather than once at entry — a single arming site
;             fires only the first transfer
;   tail:     rts
;
; PFS_LEFT. Resets both counters — the TICK never does, which is what makes a
; deferred drain self-heal (see ES_PFS_NMI above).
;
; Uses the vblank-phase channel's $43xx registers directly: the NMI core
; re-arms every channel from the scene_mgr shadow after the hook, so
; time-sharing with an active-phase channel is safe by construction.
;
; It programs its own VMAIN and VMADD, so its position in the hook is free (the
; tree's VBlank VRAM writers all do this — AGENTS.md's established pattern,
; measured twice).
;
; DAS IS RE-ARMED PER SUB-TRANSFER, and there are TWO per slot. The byte count
; is consumed by each MDMAEN write — the channel latches it, counts down, and
; stops — so a second transfer fired off one arming moves ZERO bytes. That is
; the exact shape that silently under-drains a streaming dispatcher: quota
; four, one column landing, and no error anywhere.
;
; WIDTH-RISK: entered A8/I16 and exits A8/I16. Every `rep #$20` window ends in
; a `sep #$20` + `.a8` before the next label, and the two cursor advances
; (`tya`/`tay`, `txa`/`tax`) are executed ONLY in A16 — in A8/I16 `tax` would
; move the full 16-bit C, carrying a stale high byte into the meta index.
pfs_stream_nmi_dispatch:
    .a8
    .i16
    SF_ASSERT_WIDTH 8, 16, "pfs_stream_nmi_dispatch"
    lda z:PFS_BUSY
    bne @drain_done                 ; a stage is mid-flight — defer, don't
                                    ; drain a half-published slot table
    lda z:PFS_COL_CNT
    clc
    adc z:PFS_ROW_CNT
    beq @drain_done
    sta z:PFS_LEFT                  ; slots remaining
    lda #ES_H_PFSS_DMAP
    sta a:PFSS_REGS + 0             ; DMAP: mode 1, A->B (the word port)
    lda #ES_H_PFSS_BBAD
    sta a:PFSS_REGS + 1             ; BBAD: VMDATAL
    lda #ES_PFS_SLOTS_BANK
    sta a:PFSS_REGS + 4             ; A1B
    ldx #0                          ; meta record cursor
    ldy #ES_PFS_SLOTS               ; A-bus cursor
@slot:
    .a8
    lda a:ES_PFS_META + 4, x
    sta a:$2115                     ; VMAIN: this slot's axis stride
    rep #$20
    .a16
    lda a:ES_PFS_META + 0, x
    sta a:$2116                     ; VMADD: sub-transfer A
    tya
    sta a:PFSS_REGS + 2             ; A1T
    lda #PFS_HALF_B
    sta a:PFSS_REGS + 5             ; DAS
    sep #$20
    .a8
    lda #(1 << ES_H_PFSS_CH)
    sta a:$420B                     ; fire A
    rep #$20
    .a16
    lda a:ES_PFS_META + 2, x
    sta a:$2116                     ; VMADD: sub-transfer B (the other page)
    tya
    clc
    adc #PFS_HALF_B
    sta a:PFSS_REGS + 2             ; A1T
    lda #PFS_HALF_B
    sta a:PFSS_REGS + 5             ; DAS — RE-ARMED (single-shot)
    sep #$20
    .a8
    lda #(1 << ES_H_PFSS_CH)
    sta a:$420B                     ; fire B
    rep #$20
    .a16
    tya
    clc
    adc #PFS_LINE_B
    tay
    txa
    clc
    adc #PFS_META_STRIDE
    tax
    sep #$20
    .a8
    dec z:PFS_LEFT
    bne @slot
    stz z:PFS_COL_CNT
    stz z:PFS_ROW_CNT
@drain_done:
    .a8
    rts
