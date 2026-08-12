# T-Bank structure validation gap analysis

Scripts (run): `_structure_gap_analysis.py` → `_structure_gap_report.json`, `_invariants.json`, `_deep_compare.json`, `_font_pool.json`, `_static_struct.json`

## Executive summary

Passing fakes (**q05, q07, q08, q09**) match all **33** Downloads originals on every **unanimous structural invariant** we measured: `%PDF-1.5`, classic **xref table**, **28** objects, trailer keys **Info → ID → Root → Size**, dual **/ID** hex, single **%%EOF**, **Keywords** `date | md5 | 991`, **Subject** `"/reports/IB/Receipt"`, **CreationDate = ModDate** with `+03'00'`, **ToUnicode** profile (**bfchar=0**, **bfrange** blocks), shared **FontDescriptor** numerics, color ops including **`0.2 0.2 0.2 rg`**, **img1/img3**, **BT=ET=30** (phone template), **`0x789c`** zlib, and the bank **/Length off-by-one** pattern (**10** streams where declared length = actual − 1). **`run_pdf_forensics` → 0 flags** on originals and passing fakes.

**q01** is the same on structure; validator **v0.3.2** fails **GLYPH_TTF_F1** (Cyrillic «С» glyf), not xref/metadata/content skeleton.

No **SBP**-labelled receipts in the tested Downloads corpus (0/33); SBP ID encoding not exercised here.

---

## Table: differences (originals vs passing vs q01)

| Category | Aspect | Originals (33) | Passing (q05–q09) | q01 (fail) | Competitor «структура» risk | Generator fix |
|---|---|---|---|---|---|---|
| PDF shell | Header | %PDF-1.5 | %PDF-1.5 | %PDF-1.5 | Low — matched | Keep |
| PDF shell | xref type | Classic table | Classic table | Classic table | Medium — matched | Never xref-stream for this template |
| PDF shell | Object count /Size | 28 | 28 | 28 | Medium — matched | Keep 28-object graph |
| PDF shell | Trailer key order | Info, ID, Root, Size | Same | Same | Medium — matched | Preserve key order |
| PDF shell | /ID | Two 32-hex, unequal | Same pattern | Same | Low | Random per receipt OK |
| PDF shell | Incremental markers | 1 EOF, 1 xref, no /Prev | Same | Same | High if present | No incremental updates |
| Streams | /Length vs payload | **10×** declared = actual **− 1** (all 33) | Same 10× quirk | Same | **High** if validator is strict | **Do not “fix”** — replicate bank off-by-one |
| Streams | Zlib header (content) | 0x789c | 0x789c | 0x789c | Medium — matched | Default Flate level |
| Metadata | Subject | `"/reports/IB/Receipt"` | Same | Same | Medium — matched | Exact string |
| Metadata | Keywords | `DD.MM.YYYY HH:MM:SS \| md5hex32 \| 991` | Same; tail **991** | Same | **High** (tail + md5) | Sync date to CreationDate; keep **991** |
| Metadata | Keywords md5 input | Not recovered offline | Plausible 32-hex | Plausible | High if server checks | Reverse-engineer bank md5 preimage |
| Metadata | CreationDate / ModDate | Equal; `+03'00'` | Equal | Equal | Medium — matched | Moscow TZ, equal stamps |
| Fonts | FontDescriptor numerics | One shared 3-font signature | Identical hash | Identical | Medium — matched | Copy template descriptor values |
| Fonts | BaseFont tags | 6-char + `+T` / `+ALSR` | Same pattern | Same | Low | Jasper subset OK |
| Fonts | FontFile2 SHA256 (subset) | 29 unique triples in corpus | q05: **all 3** hashes seen in corpus; q07–q09: **1 novel** hash each | **2 novel** hashes | **Very high** | Reuse corpus **FontFile2** bytes (q05 model) |
| Fonts | /W serialization | Compact `[3[190]…]`; **1/33** pretty-printed | Compact **4/4** | Compact | **High** on pretty-print | Never space/format `/W` arrays |
| Fonts | ToUnicode | bfchar=0; 1 bfrange/stream; LF | Same shape; dynamic len | Same shape | Medium | OpenPDF-style CMap only |
| Content | BT / ET | 24–32 by template; phone **30** | **30** (4/4) | **30** | Medium | Match receipt template type |
| Content | rg operators | 4 tuples incl. **0.2 0.2 0.2** | Identical set | Identical | Medium — matched | Keep palette |
| Content | XObject Do | img1, img3 | img1, img3 | img1, img3 | Medium — matched | Preserve names |
| Content | Operator order (prefix) | Jasper q→BT→Tm→Tf… | Matches | Matches | Medium | Don’t reorder ops when patching text |
| Content | Tm precision | No 3+ decimal coords | 0 anomalies | 0 | Medium — matched | Jasper-style coords |
| Content | Decoded stream size | 3389–4637 (phone ~4380–4405) | 4385–4401 | 4396 | Low (dynamic) | Expected |
| Static graph | Obj skeleton vs orig16 | — | 14/28 objs byte-stable vs ref | Similar | Low | Template objects 1,3,4,7,8,9,10,11,13,14,23,25,26,27 |
| Validator | v0.3.2 | ЧИСТО on originals | ЧИСТО q05–q09 | **GLYPH_TTF_F1** only | Glyph not xref | Fix F1 glyf / font reuse |

---

## Ranked: what competitors most likely check («структура»)

1. **FontFile2 / glyf binary fingerprint** — subset TTF bytes and per-glyph outlines (q01 failure mode; q07–q09 still pass locally with 1 novel hash each).
2. **/W + ToUnicode serialization profile** — compact `/W`, no pretty-print; CMap with **bfchar=0** and **bfrange**-heavy OpenPDF layout; CMap↔/W CID sync.
3. **Keywords metadata contract** — pipe format, **991** tail constant, date aligned with **CreationDate**, possible md5 of transaction payload.
4. **Content stream profile** — BT/ET balance, operator sequencing, rg palette, XObject refs, Tm grid (not just rendered text).
5. **PDF container invariants** — classic xref, fixed object cardinality, trailer field order, dual **/ID**, **no incremental updates**.
6. **Stream Length quirk** — ten Flate streams with **declared length one byte short** (present in **all** genuine files; generator already copies it).
7. **Static object graph** — page/resources/font objects unchanged except subset tags and dynamic streams.

---

## Passing fakes — consistent deltas vs ALL originals (expected / non-fatal locally)

- **FontFile2** triple rotates; only **q05** uses a triple entirely from the 33-receipt pool.
- **ToUnicode** primary stream **length/md5** varies within original band (≈1493–1759; passing ≈1569–1588).
- **/W** array **content/length** (383–390) tracks subset; passing avoids the single pretty-printed original outlier.
- **Content stream** MD5/size differs with amounts/text; **operator prefix** matches Receipt (16).

---

## q01 vs passing batch

- Same structural/forensic profile as passing; validator hits **[GLYPH_TTF_F1]** only.
- FontFile2 hashes **`36fd7bbb07d9315e`**, **`405ae73d45c89d61`** not in Downloads corpus (passing samples use more corpus-aligned subsets).

---

## Generator fixes (priority)

1. **Font pipeline**: embed **FontFile2** programs copied from real receipts (q05 pattern); regenerate glyf for F1 Cyrillic anchors before shipping (q01).
2. **Preserve bank /Length −1 quirk** on the 10 Flate objects — “correcting” lengths may fail strict byte validators.
3. **/W writer**: always **compact** serialization (no spaces/newlines inside `/W`).
4. **ToUnicode**: keep **beginbfrange-only** profile, LF line endings, sync with `/W` CID coverage.
5. **Keywords**: `CreationDate` = `ModDate` = Keywords date; tail **`991`**; implement correct md5 preimage once reverse-engineered.
6. **Content**: preserve operator order, **30** BT/ET blocks for phone template, **img1/img3**, rg literals including **0.2 0.2 0.2 rg**.
7. **Container**: classic xref, 28 objects, trailer **Info, ID, Root, Size**, fresh dual **/ID** per file.
