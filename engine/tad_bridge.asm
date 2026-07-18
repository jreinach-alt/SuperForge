; =============================================================================
; tad_bridge.asm — Terrific Audio Driver Bridge for SuperForge Engine
; =============================================================================
; Wraps TAD's ca65 API for SuperForge's audio engine. This file provides the
; high-level audio functions (tad_music, tad_sfx, tad_music_vol, etc.) that
; are called by the sf_audio macro layer via direct JSR.
;
; TAD's ca65 API handles all SPC700 communication — this bridge NEVER writes
; to APU ports $2140-$2143 directly. All commands go through Tad_QueueCommand,
; Tad_QueuePannedSoundEffect, etc.
;
; Must NOT have .p816/.smart (included into parent).
; Prerequisites: engine_state.inc included, .p816/.smart set.
;
; Cross-ref: tad-audio.inc, engine_state.inc, handlers_engine.asm, frame_lifecycle.asm
; =============================================================================

; TAD ca65 API is imported via tad-audio.inc (included by the ROM that uses us).
; We use: Tad_Init, Tad_Process, Tad_QueueCommand, Tad_QueueCommandOverride,
;         Tad_QueuePannedSoundEffect, Tad_LoadSong, Tad_IsSongLoaded,
;         Tad_IsSongPlaying, Tad_SetTransferSize

; =============================================================================
; tad_bridge_init — Initialize TAD driver at boot
; =============================================================================
; Must be called ONCE at boot, with interrupts disabled, while the S-SMP
; is running the IPL ROM. This uploads the loader and audio driver to SPC700.
;
; Requires: A8, I16, interrupts disabled, S-SMP in IPL state
; Clobbers: A, X, Y
; =============================================================================
tad_bridge_init:
    .a8
    .i16
    ; TAD's Tad_Init handles everything: uploads loader, uploads driver,
    ; sets song to 0 (silence), resets variables, queues common audio data.
    jsl Tad_Init

    ; Mark TAD as ready in engine state
    lda #$01
    sta TAD_READY
    stz TAD_STATUS
    stz TAD_PAUSED
    lda #$FF
    sta TAD_SONG_ID                     ; no song playing yet

    ; Set default volume (max)
    lda #$7F
    sta TAD_VOLUME

    ; Clear fade state (inactive)
    stz FADE_TARGET
    stz FADE_SPEED
    stz FADE_DIRECTION

    rts


; =============================================================================
; tad_bridge_process — Process TAD state (called once per frame)
; =============================================================================
; Replaces the old tad_poll. Called from frame_lifecycle.asm in SIGNAL phase.
; Processes TAD's transfer queue, sends pending commands and SFX.
;
; Requires: A8, I16, DB access lowram
; Clobbers: A, X, Y
; =============================================================================
tad_bridge_process:
    .a8
    .i16
    jsl Tad_Process

    ; Update engine state from TAD's state
    jsr Tad_IsSongPlaying
    bcc @not_playing
    lda #$01                            ; playing
    bra @store_status
@not_playing:
    jsr Tad_IsSongLoaded
    bcc @not_loaded
    lda #$00                            ; loaded but paused (ready)
    bra @store_status
@not_loaded:
    lda #$02                            ; loading
@store_status:
    sta TAD_STATUS
    rts


; =============================================================================
; tad_music — Play or stop music
; =============================================================================
; Input: A = song ID (16-bit, -1 to stop, 0-255 to play)
; Returns: nothing
; =============================================================================
tad_music:
    .a16
    .i16
    ; Check if stopping (A == $FFFF = -1)
    cmp #$FFFF
    beq @stop_music

    ; Play song
    sep #$20
    .a8
    ; A = song ID low byte
    sta TAD_SONG_ID
    stz TAD_PAUSED
    ; Tad_LoadSong: A = song number (0 = silence, >=1 = song)
    jsr Tad_LoadSong
    rep #$20
    .a16
    rts

@stop_music:
    .a16
    sep #$20
    .a8
    lda #$FF
    sta TAD_SONG_ID
    stz TAD_PAUSED
    ; Load song 0 (blank/silent song)
    lda #$00
    jsr Tad_LoadSong
    rep #$20
    .a16
    rts


; =============================================================================
; tad_sfx — Play or stop a sound effect
; =============================================================================
; Input: A = SFX ID (16-bit, -1 to stop all), X = pan (0=left, 64=center, 128=right)
;        NOTE: Changed from channel to pan. TAD auto-assigns channels.
; Returns: nothing
; =============================================================================
tad_sfx:
    .a16
    .i16
    cmp #$FFFF
    beq @stop_sfx

    ; Play SFX with panning
    sep #$20
    .a8
    ; A = SFX ID, X = pan (16-bit but only low byte used by TAD)
    jsr Tad_QueuePannedSoundEffect
    rep #$20
    .a16
    rts

@stop_sfx:
    .a16
    sep #$20
    .a8
    ; Stop all sound effects
    lda #TadCommand::STOP_SOUND_EFFECTS
    ldx #$0000
    ldy #$0000
    jsr Tad_QueueCommandOverride
    rep #$20
    .a16
    rts


; =============================================================================
; tad_music_vol — Set music volume
; =============================================================================
; Input: A = volume (16-bit, 0-127)
; Returns: nothing
; =============================================================================
tad_music_vol:
    .a16
    .i16
    sep #$20
    .a8
    ; Clamp to 0-127
    cmp #128
    bcc @vol_ok
    lda #127
@vol_ok:
    .a8
    sta TAD_VOLUME
    ; Use SET_MAIN_VOLUME command (signed i8 volume)
    tax                                 ; X = volume as parameter0
    lda #TadCommand::SET_MAIN_VOLUME
    ldy #$0000
    jsr Tad_QueueCommandOverride
    rep #$20
    .a16
    rts


; =============================================================================
; tad_music_pause — Pause current music
; =============================================================================
tad_music_pause:
    .a16
    .i16
    sep #$20
    .a8
    lda #$01
    sta TAD_PAUSED
    lda #TadCommand::PAUSE
    ldx #$0000
    ldy #$0000
    jsr Tad_QueueCommandOverride
    rep #$20
    .a16
    rts


; =============================================================================
; tad_music_resume — Resume paused music
; =============================================================================
tad_music_resume:
    .a16
    .i16
    sep #$20
    .a8
    stz TAD_PAUSED
    lda #TadCommand::UNPAUSE
    ldx #$0000
    ldy #$0000
    jsr Tad_QueueCommandOverride
    rep #$20
    .a16
    rts


; =============================================================================
; tad_sfx_vol — Set global SFX volume (Engine ID 47)
; =============================================================================
; Input: A = volume (16-bit, 0-255)
; Returns: nothing
; =============================================================================
tad_sfx_vol:
    .a16
    .i16
    sep #$20
    .a8
    ; SET_GLOBAL_SFX_VOLUME: parameter0 = volume (255 = no modification)
    tax                                 ; X = volume
    lda #TadCommand::SET_GLOBAL_SFX_VOLUME
    ldy #$0000
    jsr Tad_QueueCommandOverride
    rep #$20
    .a16
    rts


; =============================================================================
; tad_load_song — Load a song asynchronously via TAD
; =============================================================================
; Alias for tad_music that makes the async loading intent explicit.
; TAD handles the async transfer internally: Tad_LoadSong triggers the loader,
; and subsequent Tad_Process calls (driven by tad_bridge_process each frame)
; transfer data to SPC700 in chunks of TransferSize bytes per frame.
;
; During loading, TAD_STATUS = $02 (loading). When complete, TAD_STATUS
; transitions to $01 (playing) or $00 (ready/paused).
;
; Input: A = song ID (16-bit, 0 = blank/silent, >= 1 = song number)
; Returns: nothing
; =============================================================================
tad_load_song:
    .a16
    .i16
    ; Mark status as loading immediately for stat(3) responsiveness
    pha
    sep #$20
    .a8
    lda #$02
    sta TAD_STATUS
    rep #$20
    .a16
    pla
    ; Delegate to tad_music which calls Tad_LoadSong
    jmp tad_music                       ; tail call (A = song_id)


; =============================================================================
; tad_bridge_load_scene_audio — Load scene-scoped audio data asynchronously
; =============================================================================
; Called by the scene manager during scene transitions to load a new scene's
; audio data (instruments, song, SFX) into SPC700 via TAD's async loader.
;
; The LoadAudioData callback (generated by tad-compiler in
; assets/audio/tad_audio_data.asm) handles the actual ROM data access.
; TAD internally manages the multi-frame transfer via Tad_Process calls.
;
; Input: A = song ID to load for the new scene (16-bit)
;        0 = blank/silent, >= 1 = song number
; Returns: nothing
;
; After calling this, poll TAD_STATUS each frame:
;   $02 = still loading
;   $01 = playing (load complete, song started)
;   $00 = ready (load complete, paused)
; =============================================================================
tad_bridge_load_scene_audio:
    .a16
    .i16
    ; Set loading state immediately for stat(3)
    pha
    sep #$20
    .a8
    lda #$02
    sta TAD_STATUS
    stz TAD_PAUSED
    rep #$20
    .a16
    pla

    ; Store new song ID
    sep #$20
    .a8
    sta TAD_SONG_ID
    ; Trigger TAD async load — Tad_LoadSong will call LoadAudioData
    ; on the next Tad_Process, then transfer data across multiple frames
    jsr Tad_LoadSong
    rep #$20
    .a16
    rts


; =============================================================================
; tad_get_status — Get TAD loading/playback state for stat(3)
; =============================================================================
; Returns the current TAD audio state for status queries from game code.
; The value is updated each frame by tad_bridge_process.
;
; Returns: A = TAD_STATUS (16-bit, zero-extended)
;   0 = ready (song loaded, paused or idle)
;   1 = playing
;   2 = loading (async transfer in progress)
; =============================================================================
tad_get_status:
    .a16
    .i16
    sep #$20
    .a8
    lda TAD_STATUS
    rep #$20
    .a16
    and #$00FF                          ; zero-extend to 16-bit
    rts


; =============================================================================
; tad_poll — Legacy compatibility wrapper (called from frame_lifecycle.asm)
; =============================================================================
; Wraps tad_bridge_process for the frame lifecycle. The lifecycle calls with
; A16/I16 but we need A8 for TAD's API.
; =============================================================================
tad_poll:
    .a16
    .i16
    sep #$20
    .a8
    jsr tad_bridge_process
    rep #$20
    .a16
    rts


; =============================================================================
; tad_set_tempo — Set SPC700 Timer 0 tick rate (song playback speed)
; =============================================================================
; Input: A = timer value (16-bit, low byte used: 64-255, 0=256)
;        Lower values = slower tempo, higher = faster.
;        Default tempo is set by MML file.
; Returns: nothing
; =============================================================================
tad_set_tempo:
    .a16
    .i16
    sep #$20
    .a8
    tax                                 ; X = timer value as Param0
    lda #TadCommand::SET_SONG_TIMER
    ldy #$0000
    jsr Tad_QueueCommandOverride
    rep #$20
    .a16
    rts


; =============================================================================
; tad_set_channels — Enable/disable individual music channels
; =============================================================================
; Input: A = channel bitmask (16-bit, low byte used: bits 0-7)
;        bit 0 = channel A, bit 1 = channel B, ..., bit 7 = channel H
;        1 = enabled (playing), 0 = muted
;        $FF = all channels enabled (default)
; Returns: nothing
; =============================================================================
tad_set_channels:
    .a16
    .i16
    sep #$20
    .a8
    tax                                 ; X = bitmask as Param0
    lda #TadCommand::SET_MUSIC_CHANNELS
    ldy #$0000
    jsr Tad_QueueCommandOverride
    rep #$20
    .a16
    rts


; =============================================================================
; tad_start_fade — Begin smooth volume fade toward target
; =============================================================================
; Input: A = target volume (16-bit, low byte: 0-127)
;        X = speed (16-bit, low byte: volume change per frame, 1-127)
;        If speed=0, sets volume instantly (no fade).
; Returns: nothing
; =============================================================================
tad_start_fade:
    .a16
    .i16
    ; A = target_vol (16-bit), X = speed (16-bit)
    ; Save both params to engine state first (avoids stack size issues)
    sep #$20
    .a8
    sta FADE_TARGET                     ; target_vol low byte
    txa
    sta FADE_SPEED                      ; speed low byte
    ; Check for instant set (speed == 0)
    beq @instant

    ; --- Fade mode ---
    ; Determine direction by comparing current volume to target
    lda TAD_VOLUME
    cmp FADE_TARGET
    bcc @fade_up
    beq @fade_done                      ; already at target
    ; Fading down (current > target)
    stz FADE_DIRECTION                  ; 0 = down
    rep #$20
    .a16
    rts
@fade_up:
    .a8                                     ; arrived via bcc, still A8
    lda #$01
    sta FADE_DIRECTION                  ; 1 = up
    rep #$20
    .a16
    rts
@fade_done:
    .a8                                     ; arrived via beq, still A8
    stz FADE_SPEED                      ; no fade needed
    rep #$20
    .a16
    rts

@instant:
    ; Speed=0: set volume directly (already A8)
    lda FADE_TARGET
    sta TAD_VOLUME
    tax                                 ; X = volume as Param0
    lda #TadCommand::SET_MAIN_VOLUME
    ldy #$0000
    jsr Tad_QueueCommandOverride
    stz FADE_SPEED                      ; ensure fade inactive
    rep #$20
    .a16
    rts


; =============================================================================
; tad_fade_step — Advance volume fade by one frame
; =============================================================================
; Called from SIGNAL phase of frame_lifecycle.asm.
; If FADE_SPEED == 0, returns immediately (~15 cycles).
; Otherwise adjusts TAD_VOLUME toward FADE_TARGET by FADE_SPEED units.
;
; Requires: A8, I16
; Clobbers: A, X, Y
; =============================================================================
tad_fade_step:
    .a8
    .i16
    lda FADE_SPEED
    beq @done                           ; no active fade — fast exit

    lda FADE_DIRECTION
    bne @step_up

@step_down:
    ; current_vol -= speed, clamp to target
    lda TAD_VOLUME
    sec
    sbc FADE_SPEED
    bcc @clamp_down                     ; underflow — clamp
    cmp FADE_TARGET
    bcs @apply                          ; still above target — keep going
    ; Fell below target — clamp
@clamp_down:
    lda FADE_TARGET
    stz FADE_SPEED                      ; fade complete
    bra @apply

@step_up:
    ; current_vol += speed, clamp to target
    lda TAD_VOLUME
    clc
    adc FADE_SPEED
    bcs @clamp_up                       ; overflow — clamp
    cmp FADE_TARGET
    bcc @apply                          ; still below target — keep going
    beq @apply_done                     ; exactly at target
    ; Exceeded target — clamp
@clamp_up:
    lda FADE_TARGET
@apply_done:
    stz FADE_SPEED                      ; fade complete

@apply:
    ; Apply new volume via TAD command
    sta TAD_VOLUME
    tax                                 ; X = volume as Param0
    lda #TadCommand::SET_MAIN_VOLUME
    ldy #$0000
    jsr Tad_QueueCommandOverride
@done:
    rts
