; ref_palette.inc — the five CGRAM words of `split_h_persp_demo`, frozen here
; as the palette oracle. Not a build input; tools/gen_split_h_persp_assets.py
; parses it and only that. Order IS the CGRAM index order (0..4).
COLOR_BACKDROP  = $5400
COLOR_DARK      = $0140         ; idx1 cool dark  (green,      R=0)
COLOR_LIGHT     = $7FE0         ; idx2 cool light (cyan-white, R=0)
COLOR_WARM_DARK = $014A         ; idx3 warm dark  (= dark + red,  R~80)
COLOR_WARM_LIGHT= $7FFF         ; idx4 warm light (= light + red, R~248 / white)
