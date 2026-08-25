# probe_objview placeholder assets

First-party, generated: both blobs are emitted by
`python3 tools/gen_objview_assets.py vendor/probes/probe_objview/assets`
(deterministic — a regen is byte-identical). Eight numbered 32x32 4bpp test
frames plus a 16-word BGR555 palette; no external art, no third-party
source.

They are committed so a bare checkout builds. A build can swap in candidate
art without committing it — `PROBE_OBJVIEW_CHR=` / `PROBE_OBJVIEW_PAL=`,
documented at the Makefile's `probe-objview` rule, which also states the
layout contract a candidate blob must follow.
