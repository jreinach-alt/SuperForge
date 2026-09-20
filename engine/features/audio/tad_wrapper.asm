; =============================================================================
; audio — TAD ca65 API compilation unit + the allocator<->linker bridge
; =============================================================================
; Assembled as a SEPARATE object: the vendored tad-audio.s defines its own
; .bss/.zeropage reservations and must not inherit main.asm's segment or width
; state. It is NOT .included anywhere.
;
; The bridge asserts are the load-bearing part. TAD's 16 B .bss + 2 B
; .zeropage are placed by the LINKER (vendor/rom/lorom_512k.cfg's TADBSS /
; TADZP windows), while the allocator arbitrates the same ranges through the
; audio feature's pinned tad_bss / tad_zp claims (feature.toml `at=`). The two
; are bridged here at link time: if the cfg window, the pin, or a TAD upgrade's
; layout ever disagree, the build REFUSES instead of silently double-booking
; lowram — the failure class a hand-managed window invites, where nothing
; connects the linker cfg to the driver's own declared layout and the two
; drift apart at the next upgrade.
.p816
.smart

.include "engine_state_globals.inc"     ; ES_TAD_* — the allocator's pins

; TAD memory-map + segment configuration (must precede the include).
LOROM = 1
.define TAD_CODE_SEGMENT "CODE"
.define TAD_PROCESS_SEGMENT "CODE"

.include "tad-audio.s"                  ; vendor/tad — unmodified upstream

; --- the allocator<->linker bridge ------------------------------------------
; Tad_flags is the FIRST .bss symbol tad-audio.s declares and Tad_sfxQueue_sfx
; the first .zeropage one, so equality against the pin means the whole block
; sits inside the claim; the cfg window SIZES bound the far end (ld65 refuses a
; segment overflow if a TAD upgrade grows them).
.assert Tad_flags = ES_TAD_BSS, lderror, "TAD .bss drifted from the allocator's tad_bss pin ($1F00): cfg TADBSS window vs engine/features/audio/feature.toml at="
.assert Tad_sfxQueue_sfx = ES_TAD_ZP, lderror, "TAD .zeropage drifted from the allocator's tad_zp pin ($F0): cfg TADZP window vs engine/features/audio/feature.toml at="

; =============================================================================
;   sf_sfx — a request queue in front of TAD's one-deep one
; =============================================================================
; DELIVERY, NOT POLICY. TAD's ca65 API keeps ONE pending effect and prefers the
; LOWER id when a second arrives in the same frame (tad-audio.s:1293), so the
; rest of that frame's requests die before the DRIVER sees them — and the
; driver is the part with the good policy (audio-driver.asm:1175-1250): it
; dedups a repeat onto the channel already playing it, fills a free channel
; first, and when both are busy evicts by `sfx_remainingTicks`, the effect with
; least left to lose. This queue exists to FEED that policy, so it preserves
; request ORDER and deliberately does not re-sort by id.
;
; The whole ring is allocator-placed (ES_SFX_QUEUE) — no address here is
; hand-written, which is what lets this file stay inside the no_literals scope.
SFXQ_N          = 4                 ; ring entries; power of two, the mask below
; TICK: ok — a PERCEPTUAL STALENESS CAP, not a rate. It bounds how late a cue
; may still be fired before it reads as input lag; it integrates nothing and
; drives no motion, so there is no quantity for a x5/6 to be wrong about. The
; consequence of leaving it unscaled is stated rather than hidden: three PAL
; frames are 60 ms where three NTSC frames are 50 ms, so a PAL cue is allowed
; to arrive marginally later before being discarded. That is docs/95 §5.2's
; class B — a rounding policy with no correct answer — and 10 ms at the tail of
; an already-late cue is not a difference a player can name.
SFXQ_MAX_AGE    = 3                 ; frames a request may wait before it is
                                    ;   discarded rather than fired stale
SFXQ_PAN_CENTRE = $FF               ; > TAD_MAX_PAN, which the driver centres

SFXQ_ID     = ES_SFX_QUEUE_LONG + 0     ; [4]
SFXQ_PAN    = ES_SFX_QUEUE_LONG + 4     ; [4]
SFXQ_AGE    = ES_SFX_QUEUE_LONG + 8     ; [4]
SFXQ_HEAD   = ES_SFX_QUEUE_LONG + 12
SFXQ_CNT    = ES_SFX_QUEUE_LONG + 13
SFXQ_DFULL  = ES_SFX_QUEUE_LONG + 14
SFXQ_DSTALE = ES_SFX_QUEUE_LONG + 15
SFXQ_DELIV  = ES_SFX_QUEUE_LONG + 16

.export sf_sfx_reset, sf_sfx_queue, sf_sfx_queue_c, sf_audio_tick

.a8
.i16
; --- sf_sfx_reset: the ring, from power-on garbage to empty ------------------
; CONTRACT sf_sfx_reset
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   out:      the ring empty, every counter zero
;   clobbers: A, X, N, Z
;   assumes:  called once from the boot block, beside Tad_Init
;   tail:     rts
;
; DB=0 in the contracts is the TAD ABI's requirement, not this code's: every
; access below is absolute-long and indifferent to DB, but the driver entry
; points these feed are not.
;
; RAM IS RANDOM AT POWER-ON (CLAUDE.md rule 5), so head/count in particular
; MUST be written before the first queue call — a garbage count would index
; outside the ring on the very first frame.
sf_sfx_reset:
    ldx #(ES_SFX_QUEUE_SIZE - 1)
    lda #0
@wipe:
    .a8
    .i16
    sta f:ES_SFX_QUEUE_LONG, x
    dex
    bpl @wipe
    rts

.a8
.i16
; --- sf_sfx_queue: enqueue one request --------------------------------------
; CONTRACT sf_sfx_queue
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   in:       A = the SFX:: id, X = pan 0..128 (or SFXQ_PAN_CENTRE for centre)
;   out:      the request held, or counted in SFXQ_DFULL if the ring was full
;   clobbers: A, N, Z, C
;   tail:     rts
;
; X AND Y SURVIVE: the pan arrives in X and leaves in X, so a call site mid
; routine keeps whatever it was holding.
;
; A FULL RING DISCARDS THE ARRIVING REQUEST, not an older one. The queue's
; contract is order preservation; evicting a held entry to make room would be
; the queue making a policy call, which is the driver's job.
;
; WIDTH-RISK: the A8->index widening below is the documented tax/tay trap
; (CLAUDE.md rule 6) — after an A8 `lda` the C-high byte is stale, so the
; value is widened and masked BEFORE the transfer, never transferred raw.
; STACK: `phx` pushes 2 bytes (I16) and `pha` 1 (A8); both exits pull exactly
; that, so the pair nets to zero across the width toggles.
sf_sfx_queue:
    phx                             ; the pan, held across the slot arithmetic
    pha                             ; ...and the id
    lda f:SFXQ_CNT
    cmp #SFXQ_N
    bcc @room
    ; ---- full: count it and discard the arrival ---------------------------
    lda f:SFXQ_DFULL
    inc a
    beq @full_saturated             ; already $FF: stay there
    sta f:SFXQ_DFULL
@full_saturated:
    .a8
    .i16
    pla                             ; drop the id
    plx                             ; ...and give the caller its X back
    rts
@room:
    .a8
    .i16
    clc
    adc f:SFXQ_HEAD                 ; slot = (head + count) & (N-1)
    and #(SFXQ_N - 1)
    rep #$20
    .a16
    and #$00FF                      ; the stale C-high byte, cleared
    tax                             ; X = the slot
    sep #$20
    .a8
    pla                             ; the id
    sta f:SFXQ_ID, x
    lda 1,s                         ; the pan's low byte, still on the stack
    sta f:SFXQ_PAN, x
    lda #0
    sta f:SFXQ_AGE, x
    lda f:SFXQ_CNT
    inc a
    sta f:SFXQ_CNT
    plx                             ; X = the pan again, i.e. the caller's X
    rts

.a8
.i16
; TICK: ok — NOT a per-frame routine despite the name shape: it retires ONE
; ring entry and is called zero or more times inside a single pump, so its unit
; is the entry, not the frame. Nothing here counts time.
; --- sfxq_advance: retire the head entry ------------------------------------
; CONTRACT sfxq_advance
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   out:      head stepped, count decremented
;   clobbers: A, N, Z, C
;   assumes:  count > 0
;   tail:     rts
sfxq_advance:
    lda f:SFXQ_HEAD
    inc a
    and #(SFXQ_N - 1)
    sta f:SFXQ_HEAD
    lda f:SFXQ_CNT
    dec a
    sta f:SFXQ_CNT
    rts

.a8
.i16
; TICK: ok — per-frame by name AND in fact, but its cadence is the TAD ABI's,
; not a rate this repo chose. Tad_sfxQueue_sfx holds ONE id, so one delivery
; per frame is the interface's limit; a PAL frame carries exactly one cue too,
; and scaling the cadence would mean inventing deliveries the API cannot
; accept. The aging above is the only quantity with a time unit and it carries
; its own note.
; --- sf_audio_tick: age, expire, deliver ONE, then run the driver -----------
; CONTRACT sf_audio_tick
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   out:      at most one request handed to TAD, then Tad_Process run
;   clobbers: A, X, N, Z, C
;   assumes:  called ONCE per frame from the MAIN LOOP, never an ISR — the TAD
;             ABI forbids Tad_Process from an interrupt handler
;   tail:     rts
;
; REPLACES a bare `jsl Tad_Process` at the rail's call site. The order is
; load-bearing: the delivery must happen BEFORE Tad_Process so the id reaches
; the driver on this frame rather than the next.
;
; ONE PER FRAME is the ABI's limit, not a choice — Tad_sfxQueue_sfx holds a
; single id. What the ring buys is that the SECOND request in a frame now
; arrives on the next one instead of being discarded unseen.
;
; WIDTH-RISK: Tad_QueuePannedSoundEffect and Tad_Process are CROSS-FILE callees
; whose widths the single-file lint cannot see; both are entered A8 here, which
; is their documented contract.
sf_audio_tick:
    ; ---- age every slot; enqueue resets the one it writes ------------------
    ldx #(SFXQ_N - 1)
@age:
    .a8
    .i16
    lda f:SFXQ_AGE, x
    cmp #$FF
    beq @age_next                   ; saturate rather than wrap back to young
    inc a
    sta f:SFXQ_AGE, x
@age_next:
    .a8
    .i16
    dex
    bpl @age
    ; ---- expire stale entries off the head, then deliver at most one -------
@head:
    .a8
    .i16
    lda f:SFXQ_CNT
    beq @process                    ; nothing held
    lda f:SFXQ_HEAD
    rep #$20
    .a16
    and #$00FF                      ; the A8 load's stale high byte
    tax                             ; X = the head slot
    sep #$20
    .a8
    lda f:SFXQ_AGE, x
    cmp #(SFXQ_MAX_AGE + 1)
    bcc @deliver
    ; too old to fire honestly: a DECLARED loss, counted where a test can see it
    lda f:SFXQ_DSTALE
    inc a
    beq @stale_saturated
    sta f:SFXQ_DSTALE
@stale_saturated:
    .a8
    .i16
    jsr sfxq_advance
    bra @head                       ; the next entry may be stale too
@deliver:
    .a8
    .i16
    lda f:SFXQ_ID, x
    pha                             ; 1 byte (A8); pulled below, same width
    lda f:SFXQ_PAN, x
    rep #$20
    .a16
    and #$00FF
    tax                             ; X = the pan the driver wants
    sep #$20
    .a8
    pla                             ; A = the id
    jsr Tad_QueuePannedSoundEffect
    lda f:SFXQ_DELIV
    inc a
    beq @deliv_saturated
    sta f:SFXQ_DELIV
@deliv_saturated:
    .a8
    .i16
    jsr sfxq_advance
@process:
    .a8
    .i16
    jsl Tad_Process
    rts

.a8
.i16
; --- sf_sfx_queue_c: the same, centred -------------------------------------
; CONTRACT sf_sfx_queue_c
;   entry:    A8 I16 DB=0
;   exit:     A8 I16
;   in:       A = the SFX:: id
;   out:      the request held with a centre pan
;   clobbers: A, N, Z, C
;   tail:     rts
;
; The centred counterpart of sf_sfx_queue, and the reason it exists rather
; than an `ldx` at each call site: X SURVIVES. room_logic's footstep call is
; marked "KEEP X/Y" by its caller, so loading a pan into X there would be a
; silent register clobber in engine code — the shape this repo keeps finding.
; Callers that already have a position use sf_sfx_queue directly.
;
; SFXQ_PAN_CENTRE is above TAD_MAX_PAN, which the driver reads as centre
; (tad-audio.s:976) — the same convention Tad_QueueSoundEffect uses internally.
sf_sfx_queue_c:
    phx
    ldx #SFXQ_PAN_CENTRE
    jsr sf_sfx_queue
    plx
    rts
