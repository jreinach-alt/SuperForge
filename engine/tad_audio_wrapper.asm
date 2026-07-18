; =============================================================================
; tad_audio_wrapper.asm — TAD ca65 API Wrapper for SuperForge
; =============================================================================
; This file defines the memory map and segment configuration for TAD's ca65
; API, then includes the TAD source file (tad-audio.s).
;
; TAD requires either LOROM or HIROM to be defined before inclusion.
; TAD_CODE_SEGMENT and TAD_PROCESS_SEGMENT control placement.
;
; This file is assembled as a SEPARATE object file and linked alongside
; the game's main code. It is NOT .included into other .asm files.
;
; Cross-ref: lib/tad/audio-driver/ca65-api/tad-audio.s, tad_bridge.asm
; =============================================================================

; Define LOROM as a symbol (not text substitution) for TAD's .defined() check
LOROM = 1

.define TAD_CODE_SEGMENT "CODE"
.define TAD_PROCESS_SEGMENT "CODE"

.include "tad-audio.s"
