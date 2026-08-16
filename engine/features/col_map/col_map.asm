; =============================================================================
; col_map.asm — world-space tile collision (scene-scoped)
; =============================================================================
; One world pixel coordinate in, one collision flag byte out. It reads the
; world tilemap blob in ROM directly, by that blob's own bank tiling, so it is
; independent of the streaming ring by construction rather than by discipline:
; the blob holds the WHOLE world, so there is no window to fall off and no
; mirror to keep synchronised.
;
; Addressing is world_rom's, read off mode7_floor.asm:110-131 and
; mode7_stream.asm:350-365 rather than reinvented, and now stated in the
; general form the constants were always instances of:
;  rpc = 32768 / W rows per 32 KB window
;  bank = <blob>_T0_BANK + (ty >> log2(rpc))
;  offset = (ty & (rpc-1)) * W + tx (0..32767, one window)
; (rpc-1)*W + (W-1) = 32767 exactly for every W, so the LoROM window is
; precisely full and a single 16-bit abs,X index reaches every byte of a chunk.
; For microzero's W = 512 that reads back as the old `>> 6` / `& 63` / `* 512`.
;
; MEASURED, not estimated: the per-query cost is measured on the emulator by
; vendor/probes/probe_colmap.asm, which .includes THIS FILE rather than a copy
; of it, so the published figure always describes the shipped kernel.
;
; =============================================================================
; THE BINDING CONTRACT — six symbols, supplied by the includer, no defaults
; =============================================================================
; col_map is one of the schema's own named exemplars of `role = "feature"`
; (allocator) and is demanded by four rails, each with its own world.
; `schemas.py` has no vocabulary for "same feature, different blob" — no
; parameterised `depends`, no template instantiation — so the binding is the
; `rgb_gradient.asm` shape instead: symbols the includer defines
; immediately above its `.include`, each missing one a hard `.error` naming
; it, and NO DEFAULT. Rgb_gradient records why a default is refused — "a silent
; default is exactly how the platformer inherited a wash on its terrain and
; shipped a teal sky" — and the same argument holds harder here, where a
; defaulted world size reads the wrong ROM bytes and returns a plausible flag.
;
;  CM_WORLD_W_LOG2 log2 of world WIDTH in tiles (microzero: 9)
;  CM_WORLD_H_LOG2 log2 of world HEIGHT in tiles (microzero: 9)
;  CM_WORLD_BLOB the blob's ES_R_<NAME>_T0_ADDR (window base)
;  CM_WORLD_BLOB_BANK the blob's ES_R_<NAME>_T0_BANK
;  CM_WORLD_BLOB_CHUNKS the blob's DERIVED ES_R_<NAME>_CHUNKS
;  CM_FLAGS the tile-id -> flag table's label
;
; AND ONE OBLIGATION THAT IS NOT A SYMBOL — when the blob is more than one
; chunk, assert that its chunk banks are CONSECUTIVE. The `bank` line of the
; addressing above is `<blob>_T0_BANK + (ty >> log2(rpc))`, which is only the
; right bank if chunk i lives in bank BASE+i; `CM_WORLD_BLOB` likewise is ONE
; window base for every chunk. Neither is promised by `RomClaim.bank_tiled`,
; whose only stated meaning is "pre-chunked so every chunk fits one bank
; window" (schemas.py) — measured, not assumed: driving the real `place_rom`
; over synthetic claim sets produces NON-consecutive banks for 3 of 4 shapes,
; two ragged `bank_tiled` blobs among them, with no pin involved. A wrong bank
; here returns a PLAUSIBLE flag, which is the failure mode this whole contract
; exists to refuse. The assert cannot live in this file — the contract
; withholds the blob's name, so the per-chunk symbols cannot be spelled here,
; and a `%s` template to reach them is refused outright by no_literals'
; blanket-rom-template pass. It belongs beside the blob's `.incbin`:
;
;  .repeat ES_R_<BLOB>_CHUNKS, WI
;  .assert .ident(.sprintf("ES_R_<BLOB>_T%d_BANK", WI)) = ES_R_<BLOB>_T0_BANK +
;  WI, error, "<blob> chunk banks are not consecutive — col_map's T0_BANK +
;  index addressing would read the wrong bank"
;  .assert .ident(.sprintf("ES_R_<BLOB>_T%d_ADDR", WI)) = ES_R_<BLOB>_T0_ADDR,
;  error, "<blob> chunks are not window-aligned alike — CM_WORLD_BLOB is one
;  base for all of them"
;  .endrepeat
;
; A ONE-CHUNK blob owes neither line: `CM_WORLD_BLOB_CHUNKS = 1` takes the
; constant-bank branch below and never adds an index. Assert that it really is
; one chunk instead — `game/m7_dungeon/scenes/dungeon.asm` does, because its
; blob is a plain `rom` claim with no per-chunk symbols to become consecutive,
; so growing it past one window has to stop the build rather than silently
; reach the `adc #CM_WORLD_BLOB_BANK` path. Microzero and the cost probe both
; bind an 8-chunk blob and paste the two lines above.
;
; `depends` is therefore `[]`: col_map depends on whatever the GAME binds, and
; the game composes both the probe and its blobs. Losing the allocator's
; `depends` check is not losing the check — it is replaced by an assembly-time
; one, and this repo already treats that as the stronger signal: the friction
; log records col_map failing to assemble on an undefined ES_M7ORG as "the
; build stating plainly that the camera origin is mode7_persp's claim", and
; concludes "the undefined-symbol error is the design review." The blob's own
; `rom` claim is still gated independently by `make rom-unbacked`.
;
; EVERY folded constant below derives from CM_WORLD_W_LOG2 / _H_LOG2 at
; ASSEMBLY time. There is no runtime parameter, no branch, and no cost: the
; W = 512 binding emits byte-for-byte the instruction sequence this file
; carried when 512 was written into it.
;
; This file names only the six bound symbols plus its own scene-scoped
; ES_CM_HOT, which is what lets both race.asm (inside .scope race) and the cost
; probe (top level) include it.

; --- the binding, checked before anything else ------------------------------
; One `.error` per symbol, naming that symbol, so an incomplete binding says
; WHICH one is missing rather than failing on a downstream range error. The
; `.ifndef` form is rgb_gradient.asm's, and no branch supplies a default.
.ifndef CM_WORLD_W_LOG2
    .error "col_map: the includer must define CM_WORLD_W_LOG2 (log2 of the world width in tiles) before including this file"
.endif
.ifndef CM_WORLD_H_LOG2
    .error "col_map: the includer must define CM_WORLD_H_LOG2 (log2 of the world height in tiles) before including this file"
.endif
.ifndef CM_WORLD_BLOB
    .error "col_map: the includer must define CM_WORLD_BLOB (the world tilemap blob's ES_R_<name>_T0_ADDR) before including this file"
.endif
.ifndef CM_WORLD_BLOB_BANK
    .error "col_map: the includer must define CM_WORLD_BLOB_BANK (the world tilemap blob's ES_R_<name>_T0_BANK) before including this file"
.endif
.ifndef CM_WORLD_BLOB_CHUNKS
    .error "col_map: the includer must define CM_WORLD_BLOB_CHUNKS (the world tilemap blob's derived ES_R_<name>_CHUNKS) before including this file"
.endif
.ifndef CM_FLAGS
    .error "col_map: the includer must define CM_FLAGS (the tile-id -> flag table label) before including this file"
.endif

; --- everything folded, derived at ASSEMBLY time ----------------------------
; 32768 is the LoROM window size in bytes, not an address — the same value
; main.asm's `.incbin "world_map.bin", PI * 32768, 32768` names.
CM_W            = 1 << CM_WORLD_W_LOG2      ; world width in tiles
CM_H            = 1 << CM_WORLD_H_LOG2      ; world height in tiles
CM_ROWS_PER_CHK = 32768 / CM_W              ; whole world rows per 32 KB chunk
CM_CHUNK_SHIFT  = 15 - CM_WORLD_W_LOG2      ; ty >> this = the chunk index

; The row index that reaches `xba` is `ty & (CM_ROWS_PER_CHK-1)` where ty is
; already masked to CM_H-1, so its maximum is min(CM_H, CM_ROWS_PER_CHK) - 1.
; `xba` is a shl-8 only while that fits in a byte; state the limit rather than
; silently miscompute past it. It is a limit on the SHAPE, not on the size:
; 512x512 (microzero) and 128x128 (m7_dungeon, platformer_stream) pass, and so
; does a 64x32 world (row index maxes at 31) — what it refuses is a world tall
; and narrow enough to put more than 256 whole rows in one 32 KB chunk.
.if CM_H < CM_ROWS_PER_CHK
    CM_ROW_MAX = CM_H - 1
.else
    CM_ROW_MAX = CM_ROWS_PER_CHK - 1
.endif
.if CM_ROW_MAX > 255
    .error "col_map: min(world height, rows per 32 KB chunk) exceeds 256 rows — the xba row scale would overflow. Raise CM_WORLD_W_LOG2 (>= 7 for a square world)."
.endif

; --- DP field aliases (ES_CM_HOT layout, feature.toml) ----------------------
CM_PX   = ES_CM_HOT + 0     ; u16 world pixel x   IN  (caller writes)
CM_PY   = ES_CM_HOT + 2     ; u16 world pixel y   IN
CM_FLAG = ES_CM_HOT + 4     ; u8  flag byte       OUT (the output region)
CM_T0   = ES_CM_HOT + 6     ; u16 kernel scratch: tile y (held for the bank)
CM_T1   = ES_CM_HOT + 8     ; u16 kernel scratch: the row's byte offset

; Namespaced deliberately: `mode7_stream.asm` defines a bare WORLD_WIN and is
; included into the SAME scene scope, so a shared name is a redefinition error.
; Ca65 caught it on the first build — the collision cost one rebuild, which is
; the allocator-repo bargain working at the assembler level too.
CM_WORLD_WIN = CM_WORLD_BLOB           ; the $8000 LoROM window each chunk fills

; --- col_map_at: world pixel (CM_PX, CM_PY) -> flag byte --------------------
; In: A16/I16, DB=0. CM_PX/CM_PY are u16 world pixel coordinates; ANY u16
;  value is legal (see the totality note below).
; Out: A8 = the flag byte, and CM_FLAG holds it. X, Y clobbered. DB restored
;  to its entry value.
;
; TOTAL over the u16 input space: the two world-size masks make every input
; name a real tile, so there is no bounds check, no sentinel and no branch. The
; masks are needed to build the index anyway, so the torus is handled at zero
; cost. See feature.toml for the full contract. BOUNDS IS NOT A PARAMETER: a
; bounded world clamps in the GAME, before it asks — deciding WHICH coordinate
; to ask about is the game's business, and a probe that stayed total by mask is
; what lets it stay branchless.
;
; WIDTH-RISK: entered A16/I16, EXITS A8/I16 — the flag is a byte, and callers
; must know that. The `tax` below is reached in A16 with the tile id already
; masked to #255, so I16's transfer of the full 16-bit C register cannot carry
; a stray high byte into X (the documented tax-across-width class). Every label
; and fall-through reached after a `sep`/`rep` carries an explicit width
; annotation because ca65 tracks width sequentially, not by control flow. DB is
; pushed and pulled around the single ROM read; the `plb` is load-bearing —
; without it the caller's next write lands in a chunk bank.
col_map_at:
    .a16
    .i16
    ; ---- tile y, and the byte offset of its row inside the 32 KB window ----
    lda z:CM_PY
    lsr
    lsr
    lsr
    and #(CM_H - 1)             ; ty = (py >> 3) mod H — the world is a torus
    sta z:CM_T0
    and #(CM_ROWS_PER_CHK - 1)  ; the row's index WITHIN its 32 KB chunk
    xba                         ; * 256
.if CM_WORLD_W_LOG2 > 8
    .repeat CM_WORLD_W_LOG2 - 8
        asl                     ; ...up to * W = bytes per world row
    .endrepeat
.elseif CM_WORLD_W_LOG2 < 8
    .repeat 8 - CM_WORLD_W_LOG2
        lsr                     ; ...down to * W = bytes per world row
    .endrepeat
.endif
    sta z:CM_T1
    ; ---- + tile x -> X = offset into this chunk's LoROM window -------------
    lda z:CM_PX
    lsr
    lsr
    lsr
    and #(CM_W - 1)             ; tx = (px >> 3) mod W
    clc
    adc z:CM_T1
    tax                         ; 0..32767 — the whole chunk, one index
    ; ---- chunk bank -> DB --------------------------------------------------
    ; A one-chunk world has no chunk term to add, and the `.if` that drops it
    ; is ASSEMBLY-time on a DERIVED symbol — never a runtime branch, so the "no
    ; bounds check, no sentinel, no branch" contract is untouched by the
    ; generalisation. (Same discipline as docs/37 §5's derived _CHUNKS: the
    ; condition is the allocator's own count, not a narrated one.)
.if CM_WORLD_BLOB_CHUNKS = 1
    lda #CM_WORLD_BLOB_BANK     ; the whole world is one chunk: bank is constant
.else
    lda z:CM_T0
    .repeat CM_CHUNK_SHIFT
        lsr                     ; ty >> log2(rows per chunk) = the chunk index
    .endrepeat
    clc
    adc #CM_WORLD_BLOB_BANK
.endif
    sep #$20
    .a8
    phb
    pha
    plb                         ; DB = this row's chunk bank
    lda a:CM_WORLD_WIN, x          ; the tile id — one byte, so 0..255 always
    plb                         ; DB restored: the caller's bank is intact
    ; ---- tile id -> flag ---------------------------------------------------
    rep #$20
    .a16
    and #255                    ; WIDTH-RISK: mask BEFORE tax — I16 moves all
    tax                         ;   16 bits of C, not just A
    sep #$20
    .a8
    lda f:CM_FLAGS, x
    sta z:CM_FLAG               ; the output region the tests read
    rts

; NOTE ON SCOPE: this file is the LOOKUP and nothing else. It names only the
; six bound CM_* symbols plus its own ES_CM_HOT, which is what lets the cost
; probe include the shipped source instead of a copy — and what lets a second
; rail bind a different blob without a second backend.
;
; Deciding WHICH coordinate to ask about is the game's business, not the
; feature's — the per-frame `cm_tick` that feeds it the camera lives in
; game/microzero/scenes/race.asm, because ES_M7ORG is mode7_persp's claim and a
; feature that reached for it could no longer be built without it. The probe
; found this: including col_map.asm failed to assemble on an undefined
; ES_M7ORG, which is the build telling us the tick was on the wrong side of the
; line.
