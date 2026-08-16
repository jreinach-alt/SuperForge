; ref_palette.inc — the five CGRAM words of `split_h_2p_demo`, frozen here as
; the palette oracle. Not a build input; tools/gen_split_h_2p_assets.py parses
; it and only that. Order IS the CGRAM index order (0..4).
COLOR_BACKDROP    = $5400       ; distant dusk backdrop (behind the floor)
COLOR_COOL_DARK   = $0DA0       ; summer forest green  (R=0,  G=13, B=3)
COLOR_COOL_LIGHT  = $1340       ; summer meadow green  (R=0,  G=26, B=4)
COLOR_WARM_DARK   = $00DF       ; autumn burnt orange  (R=31, G=6,  B=0)
COLOR_WARM_LIGHT  = $023F       ; autumn amber/pumpkin (R=31, G=17, B=0)
