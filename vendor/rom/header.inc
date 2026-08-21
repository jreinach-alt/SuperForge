; superforge — minimal LoROM header + vectors, stripped to what the toy and
; the probes need.
; Requires labels: RESET, NMI, NMI_STUB. Title override: define SF_HDR_TITLE
; (numeric guard not needed here — ca65 .ifndef on a plain symbol works when
; the default is set with = below).

.segment "HEADER"           ; $00FFC0-$00FFDF

.ifndef SF_HDR_TITLE_SET
    .define SF_HDR_TITLE "SUPERFORGE ROM"
.endif
.if .strlen(SF_HDR_TITLE) > 21
    .error "SF_HDR_TITLE must be 21 characters or fewer"
.endif
.byte SF_HDR_TITLE
.repeat 21 - .strlen(SF_HDR_TITLE)
    .byte $20
.endrepeat

.byte $30                   ; $FFD5 map mode: LoROM + FastROM
.ifndef SF_HDR_CART_TYPE
SF_HDR_CART_TYPE = $00      ; default: ROM only. The allocator emits $02
                            ; (ROM+RAM+battery) into the generated globals
                            ; inc when a game holds sram claims — included
                            ; before this file, so the .ifndef sees it.
.endif
.byte SF_HDR_CART_TYPE      ; $FFD6 cart type
.ifndef SF_HDR_ROM_SIZE
; DERIVED FROM THE LINKER CONFIG, not narrated here (docs/94 R0).
;
; The old default was `$05` — 2^5 KB = 32 KB — and TWENTY of the thirty-seven
; rails inherited it while linking 524,288 B. That is docs/94 §1's
; declaration-lies defect, and it lived here because THIS FILE CANNOT KNOW THE
; ANSWER: the image size is settled by the linker config's MEMORY areas, after
; ca65 has finished. So the config declares it — every vendor/rom/lorom_*.cfg
; exports SF_LD_ROM_SIZE beside the areas that create the image — and the byte
; is resolved at link time.
;
; `<` is required, not decorative: `.byte <import>` emits a byte-sized fixup
; ld65 resolves, while a bare `.byte <import>` is an assembly-time Range error
; (ca65 cannot prove an unresolved external fits in a byte).
;
; The escape hatch stays: a ROM linked with a config that does not export the
; symbol defines SF_HDR_ROM_SIZE itself before this include. Nothing in this
; tree does — the 17 rails that used to are the 17 that no longer need to.
.import SF_LD_ROM_SIZE
SF_HDR_ROM_SIZE = SF_LD_ROM_SIZE
.endif
.byte <SF_HDR_ROM_SIZE      ; $FFD7 ROM size (2^N KB), checked against the
                            ; image's real length by tools/fix_checksum.py
.ifndef SF_HDR_SRAM_SIZE
SF_HDR_SRAM_SIZE = $00      ; default: no SRAM. Allocator-derived from sram
                            ; demand (1024<<N bytes) — never hand-set; a
                            ; hand value here is the cart-declaration-lies
                            ; bug C2 names.
.endif
.byte SF_HDR_SRAM_SIZE      ; $FFD8 SRAM size (1024<<N bytes; $00 = none)
.ifndef SF_HDR_DEST
SF_HDR_DEST = $01           ; default: $01 = North America.
                            ;
                            ; It is a DECLARATION OF THE TARGET MARKET, not a
                            ; runtime region: the console's own region line is
                            ; $213F bit 4 and `engine/features/region` is what
                            ; reads it, so a ROM that detects and adapts keeps
                            ; this at its default and still runs correctly on
                            ; both machines. Override it (e.g. $02 = Europe)
                            ; only when a build genuinely targets one market —
                            ; a flashcart menu and a ROM-verification tool are
                            ; what read this byte, and neither is emulated
                            ; here (docs/95 §10 item 6).
.endif
.byte SF_HDR_DEST           ; $FFD9 destination
.byte $33                   ; $FFDA fixed
.byte $00                   ; $FFDB version
.word $FFFF                 ; $FFDC checksum complement (placeholder)
.word $0000                 ; $FFDE checksum (placeholder)

.segment "VECTORS"          ; $00FFE0-$00FFFF

; Native-mode IRQ vector opt-in: define SF_IRQ_VECTOR = <handler> BEFORE this
; include (a forward label reference is fine) to take the $FFEE vector. The
; default stays NMI_STUB, so a ROM that does not opt in is byte-identical —
; and safe at power-on: RESET leaves I set (SEI semantics) and NMITIMEN bits
; 4/5 clear, so nothing reaches $FFEE until a handler owner arms and unmasks.
; Emulation-mode vectors are unchanged (this engine never leaves native mode
; after the coldstart XCE).
.ifndef SF_IRQ_VECTOR
SF_IRQ_VECTOR = NMI_STUB
.endif

; native mode
.word $0000, $0000          ; $FFE0/$FFE2 reserved
.word NMI_STUB              ; $FFE4 COP
.word NMI_STUB              ; $FFE6 BRK
.word NMI_STUB              ; $FFE8 ABORT
.word NMI                   ; $FFEA NMI (VBlank)
.word $0000                 ; $FFEC reserved
.word SF_IRQ_VECTOR         ; $FFEE IRQ (opt-in; default = the stub)
; emulation mode
.word $0000, $0000          ; $FFF0/$FFF2 reserved
.word NMI_STUB              ; $FFF4 COP
.word $0000                 ; $FFF6 reserved
.word NMI_STUB              ; $FFF8 ABORT
.word NMI_STUB              ; $FFFA NMI
.word RESET                 ; $FFFC RESET (power-on entry)
.word NMI_STUB              ; $FFFE IRQ/BRK
