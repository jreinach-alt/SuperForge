; SuperForge — jam / multicart ROM header profile
;
; A thin wrapper over header.inc that declares a ROM-ONLY cartridge:
;   $FFD6 cartridge type = $00 (ROM only, no SRAM, no battery)
;   $FFD8 SRAM size      = $00 (none)
;
; Use this instead of header.inc when a competition or multicart build
; forbids SRAM (e.g. the SNES DEV Game Jam technical restrictions:
; LoROM, max 512 KB, no special chips, NO SRAM). Everything else —
; vectors, map mode $30 (LoROM + FastROM), the SF_IRQ_VECTOR opt-in —
; is identical to header.inc.
;
; Do NOT link a game that uses sf_save/sf_load with this header: the
; battery-save macros need the SRAM declaration (and lorom_sram.cfg /
; the *_sram link shapes). No-SRAM is the point.
;
; Usage:
;   .include "header_jam.inc"     ; instead of .include "header.inc"
;
; Set your release's 21-byte ROM title with the SF_HDR_TITLE opt-in (two
; coupled lines before the include; see header.inc) — do NOT edit header.inc:
;   .define SF_HDR_TITLE "MY GAME"
;   SF_HDR_TITLE_SET = 1
;   .include "header_jam.inc"
; Emulators, flashcarts, and the jam's multicart menu display it.

SF_HDR_CART_TYPE = $00
SF_HDR_SRAM_SIZE = $00
.include "header.inc"
