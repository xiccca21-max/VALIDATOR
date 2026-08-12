"""Forensic compare: SAFECHECK 24780 v2 vs 00117 corpus originals."""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

BOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BOT))

from detector.tbank_v6.engine import analyze as analyze_tbank  # noqa: E402
from detector.tbank_f1_orphan_glyph import (  # noqa: E402
    check_tbank_f1_orphan_glyph,
    parse_sfnt_tables,
    recursive_composite_closure,
    _loca_offsets,
    _glyph_slice,
    _parse_composite_components,
)
from detector.tbank_reassembly_family_v3 import (  # noqa: E402
    resolve_font_graph,
    _font_stream_metrics,
    run_tbank_reassembly_family_v3_stack,
)
from detector.tbank_sfnt_table_integrity import (  # noqa: E402
    check_tbank_sfnt_table_inventory,
    _shannon_entropy,
    parse_sfnt_directory,
    _calc_table_checksum,
)
from detector.tbank_notdef_integrity import check_tbank_notdef_integrity  # noqa: E402
from detector.tbank_reassembled_subset import check_reassembled_bank_assets  # noqa: E402
from detector.embedded_font_reassembly import check_embedded_font_reassembly  # noqa: E402
from detector.tbank_stream_integrity import check_stream_integrity  # noqa: E402
from detector.structure import content_stream_bytes, find_streams, is_content_stream  # noqa: E402
from detector.sbp_cipher import extract_sbp_opid  # noqa: E402
from detector.tbank_v6.rules import HARD_CODES, KNOWN_FAKE_CODES, SUPPORTING_GROUPS  # noqa: E402
import fitz  # noqa: E402

V2 = Path(r"C:\Users\fanis\Downloads\Telegram Desktop\ТБАНК_SAFECHECK_24780_v2.pdf")
CORPUS = Path(r"C:\Users\fanis\OneDrive\Desktop") / "чеки" / "т банк"
SBP8 = CORPUS / "сбп8.pdf"

MORE_COMPONENTS = 0x0020
ARG_1_AND_2_ARE_WORDS = 0x0001
WE_HAVE_A_SCALE = 0x0008
WE_HAVE_AN_X_AND_Y_SCALE = 0x0040
WE_HAVE_A_TWO_BY_TWO = 0x0080
WE_HAVE_INSTRUCTIONS = 0x0100


def shannon(data: bytes) -> float:
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    n = len(data)
    ent = 0.0
    for c in counts:
        if c:
            p = c / n
            ent -= p * math.log2(p)
    return round(ent, 6)


def extract_instruction_program(glyph: bytes) -> bytes:
    """Return TrueType instruction bytecode after glyph outline."""
    if len(glyph) < 10:
        return b""
    ncont = struct.unpack(">h", glyph[0:2])[0]
    if ncont < 0:
        # composite: walk components then optional instructions
        i = 10
        flags = 0
        while i + 4 <= len(glyph):
            flags, _gid = struct.unpack(">HH", glyph[i : i + 4])
            i += 4
            if flags & ARG_1_AND_2_ARE_WORDS:
                i += 4
            else:
                i += 2
            if flags & WE_HAVE_A_SCALE:
                i += 2
            elif flags & WE_HAVE_AN_X_AND_Y_SCALE:
                i += 4
            elif flags & WE_HAVE_A_TWO_BY_TWO:
                i += 8
            if not (flags & MORE_COMPONENTS):
                break
        if flags & WE_HAVE_INSTRUCTIONS and i + 2 <= len(glyph):
            n = struct.unpack(">H", glyph[i : i + 2])[0]
            i += 2
            return glyph[i : i + n]
        # leftover after components may be instruction payload in pad glyphs
        return glyph[i:]
    # simple glyph
    # skip endPts, instructionLength, instructions, flags, coords
    end = 10 + 2 * ncont
    if end + 2 > len(glyph):
        return b""
    insn_len = struct.unpack(">H", glyph[end : end + 2])[0]
    return glyph[end + 2 : end + 2 + insn_len]


def f1_orphan_breakdown(pdf: bytes) -> dict[str, Any]:
    graphs = resolve_font_graph(pdf)
    g1 = graphs.get("F1")
    if not g1 or not g1.fontfile2_decoded:
        return {"error": "no_f1"}
    tables = parse_sfnt_tables(g1.fontfile2_decoded)
    loca = _loca_offsets(tables)
    if not loca:
        return {"error": "loca"}
    offsets, num_glyphs, fmt = loca
    cmap_cids = set(g1.tounicode or {})
    direct = set(cmap_cids)
    required = recursive_composite_closure(tables, offsets, direct)
    nonempty = {
        gid
        for gid in range(num_glyphs)
        if gid + 1 < len(offsets) and offsets[gid + 1] > offsets[gid]
    }
    orphans = nonempty - required - {0}
    simple, composite, emptyish = [], [], []
    high_ent_insn = []
    for gid in sorted(orphans):
        data = _glyph_slice(tables, offsets, gid)
        if len(data) < 10:
            emptyish.append(gid)
            continue
        ncont = struct.unpack(">h", data[0:2])[0]
        insn = extract_instruction_program(data)
        ent = shannon(insn) if insn else 0.0
        entry = {
            "gid": gid,
            "ncont": ncont,
            "glen": len(data),
            "insn_len": len(insn),
            "insn_ent": ent,
            "payload_sha": hashlib.sha256(data).hexdigest()[:16],
            "insn_sha": hashlib.sha256(insn).hexdigest()[:16] if insn else "",
        }
        if ncont > 0:
            simple.append(entry)
        elif ncont < 0:
            composite.append(entry)
            if len(insn) >= 16 and ent >= 7.5:
                high_ent_insn.append(entry)
        else:
            emptyish.append(gid)
    # also scan ALL nonempty unused for high-entropy instructions
    unused = nonempty - required  # includes 0? exclude 0
    unused = unused - {0}
    unused_high = []
    for gid in sorted(unused):
        data = _glyph_slice(tables, offsets, gid)
        insn = extract_instruction_program(data)
        if len(insn) >= 24 and shannon(insn) >= 7.5:
            unused_high.append(
                {
                    "gid": gid,
                    "ncont": struct.unpack(">h", data[0:2])[0] if len(data) >= 2 else None,
                    "insn_len": len(insn),
                    "insn_ent": shannon(insn),
                    "glen": len(data),
                }
            )
    try:
        metrics = _font_stream_metrics(graphs)
    except Exception as e:
        metrics = {"error": str(e)}
    return {
        "num_glyphs": num_glyphs,
        "direct": len(direct),
        "required": len(required),
        "nonempty": len(nonempty),
        "orphan_simple": len(simple),
        "orphan_composite": len(composite),
        "orphan_composite_gids": [e["gid"] for e in composite],
        "orphan_simple_gids": [e["gid"] for e in simple],
        "composite_detail": composite[:40],
        "high_ent_composite_insn": high_ent_insn[:40],
        "unused_high_ent_insn": unused_high[:40],
        "metrics": metrics,
        "ff2_raw": len(g1.fontfile2_raw or b""),
        "ff2_dec": len(g1.fontfile2_decoded),
        "glyf_len": len(tables.get(b"glyf", b"")),
        "loca_len": len(tables.get(b"loca", b"")),
        "sfnt_tags": sorted(t.decode("latin1", "replace") for t in tables),
        "head_checksumAdj": (
            struct.unpack(">I", tables[b"head"][8:12])[0] if b"head" in tables else None
        ),
    }


def content_flate_info(pdf: bytes) -> dict[str, Any]:
    import zlib

    cs = content_stream_bytes(pdf)
    out: dict[str, Any] = {"content_decoded_len": len(cs) if cs else 0}
    sizes = []
    for m in re.finditer(
        rb"(\d+)\s+0\s+obj\s*<<(.*?)/Length\s+(\d+)(.*?)>>\s*stream\r?\n",
        pdf,
        re.S,
    ):
        dict_body = m.group(2) + m.group(4)
        if b"/FlateDecode" not in dict_body:
            continue
        length = int(m.group(3))
        start = m.end()
        payload = pdf[start : start + length]
        try:
            dec = zlib.decompress(payload)
        except Exception:
            try:
                dec = zlib.decompress(payload, -15)
            except Exception:
                dec = b""
        is_cs = bool(dec) and (
            is_content_stream(dec)
            or (b"BT" in dec and (b"Tj" in dec or b"TJ" in dec))
        )
        sizes.append(
            {
                "obj": int(m.group(1)),
                "raw_len": length,
                "dec_len": len(dec),
                "is_content": bool(is_cs),
                "sha": hashlib.sha256(payload).hexdigest()[:12],
            }
        )
    content_sizes = [x for x in sizes if x["is_content"]]
    out["flate_streams"] = sizes
    out["content_flate_raw"] = [x["raw_len"] for x in content_sizes]
    out["content_flate_objs"] = content_sizes
    out["all_flate_raw"] = sorted(x["raw_len"] for x in sizes)
    return out


def keywords_info(pdf: bytes) -> dict[str, Any]:
    doc = fitz.open(stream=pdf, filetype="pdf")
    meta = doc.metadata or {}
    text = "".join(p.get_text() for p in doc)
    doc.close()
    # raw /Keywords
    km = re.search(rb"/Keywords\s*\((?:\\.|[^\\()])*\)|/Keywords\s*<[^>]*>", pdf)
    raw_kw = km.group(0).decode("latin1", "replace") if km else None
    return {
        "meta_keywords": meta.get("keywords"),
        "raw_keywords": raw_kw,
        "has_DOCS_2035": b"DOCS-2035" in pdf or "DOCS-2035" in (meta.get("keywords") or ""),
        "has_991": b"/Keywords" in pdf and (b"991" in pdf),
        "producer": meta.get("producer"),
        "creator": meta.get("creator"),
        "modDate": meta.get("modDate"),
        "creationDate": meta.get("creationDate"),
        "opid": extract_sbp_opid(text) or "",
        "bank5": (extract_sbp_opid(text) or "")[22:27]
        if len(extract_sbp_opid(text) or "") >= 27
        else "",
        "text_len": len(text),
    }


def field_order_probe(pdf: bytes) -> dict[str, Any]:
    """Rough label order from extracted text lines."""
    doc = fitz.open(stream=pdf, filetype="pdf")
    text = "".join(p.get_text() for p in doc)
    doc.close()
    labels = [
        "Статус",
        "Дата",
        "Счет списания",
        "Сумма",
        "Комиссия",
        "Итого",
        "Отправитель",
        "Получатель",
        "Телефон",
        "Банк получателя",
        "Идентификатор",
        "Квитанция",
    ]
    positions = {}
    for lab in labels:
        i = text.find(lab)
        if i >= 0:
            positions[lab] = i
    order = sorted(positions, key=positions.get)
    return {"order": order, "positions": positions}


def f2_identity(pdf: bytes) -> dict[str, Any]:
    g = resolve_font_graph(pdf).get("F2")
    if not g or not g.fontfile2_decoded:
        return {"error": "no_f2"}
    return {
        "ff2_dec_sha": hashlib.sha256(g.fontfile2_decoded).hexdigest(),
        "ff2_raw_sha": hashlib.sha256(g.fontfile2_raw or b"").hexdigest()
        if g.fontfile2_raw
        else "",
        "ff2_dec_len": len(g.fontfile2_decoded),
        "ff2_raw_len": len(g.fontfile2_raw or b""),
        "cmap_n": len(g.tounicode or {}),
        "tu_dec_len": len(g.tounicode_decoded or b""),
    }


def run_extra_detectors(pdf: bytes) -> dict[str, Any]:
    doc = fitz.open(stream=pdf, filetype="pdf")
    text = "".join(p.get_text() for p in doc)
    meta = doc.metadata or {}
    doc.close()
    producer = meta.get("producer") or ""
    creator = meta.get("creator") or ""

    out: dict[str, Any] = {}

    orphan = check_tbank_f1_orphan_glyph(pdf, text=text, producer=producer, creator=creator)
    out["orphan"] = {
        "flags": [f.code for f in orphan.flags],
        "stats_keys": list(orphan.stats.keys()),
        "orphan_simple_count": orphan.stats.get("orphan_simple_count"),
        "skipped": orphan.stats.get("skipped"),
        "telemetry_n": len(orphan.stats.get("orphan_telemetry") or []),
    }

    sfnt = check_tbank_sfnt_table_inventory(pdf, text=text, producer=producer, creator=creator)
    out["sfnt"] = {"flags": [f.code for f in sfnt.flags], "stats": {k: sfnt.stats[k] for k in sfnt.stats if k in ("f1_sfnt_tags", "inventory_canonical", "skipped", "zzzz", "unexpected_tags")}}

    nd = check_tbank_notdef_integrity(pdf, text=text, producer=producer, creator=creator)
    out["notdef"] = {"flags": [f.code for f in nd.flags], "stats_skip": nd.stats.get("skipped")}

    v3 = run_tbank_reassembly_family_v3_stack(pdf, text=text, producer=producer, creator=creator)
    out["v3"] = {
        "flags": [(f.code, f.detail[:120]) for f in v3.flags],
        "skipped": v3.stats.get("skipped"),
        "metrics": {k: v3.stats.get(k) for k in list(v3.stats) if "f1_" in k or "f2_" in k or "lattice" in k or "signature" in k} if isinstance(v3.stats, dict) else {},
    }

    ra = check_reassembled_bank_assets(pdf, producer=producer, creator=creator)
    out["reassembled"] = {"flags": [(f.code, getattr(f, "detail", "")[:100]) for f in ra.flags]}

    reb = check_embedded_font_reassembly(pdf, bank="tbank", producer=producer, creator=creator, reassembled_stats=ra.stats)
    out["rebuild"] = {"flags": [(f.code, f.detail[:100]) for f in reb.flags]}

    si = check_stream_integrity(pdf, producer=producer, creator=creator)
    out["stream_integrity"] = {"flags": [f.code for f in si.flags]}

    # flate profile if available
    try:
        from detector.tbank_flate_profile import check_tbank_flate_profile

        fp = check_tbank_flate_profile(pdf, producer=producer, creator=creator)
        out["flate"] = {"flags": [f.code for f in fp.flags], "stats": fp.stats}
    except Exception as e:
        out["flate"] = {"error": str(e)}

    try:
        from detector.tbank_deflate_profile import check_tbank_deflate_profile

        dp = check_tbank_deflate_profile(pdf, producer=producer, creator=creator)
        out["deflate"] = {"flags": [f.code for f in dp.flags]}
    except Exception as e:
        out["deflate"] = {"error": str(e)}

    try:
        from detector.tbank_keywords_generation import check_tbank_keywords_generation

        kw = check_tbank_keywords_generation(pdf, text=text, producer=producer, creator=creator)
        out["keywords"] = {"flags": [(f.code, f.detail[:120]) for f in kw.flags], "stats": kw.stats}
    except Exception as e:
        out["keywords"] = {"error": str(e)}

    # v6 full
    v6 = analyze_tbank(pdf)
    flags = list(v6.get("flags") or [])
    details = v6.get("details") or {}
    out["v6"] = {
        "verdict": v6.get("verdict"),
        "score": v6.get("score"),
        "n_flags": len(flags),
        "flags": [
            (
                f.get("code") if isinstance(f, dict) else getattr(f, "code", None),
                f.get("tier") if isinstance(f, dict) else getattr(f, "tier", None),
                str(f.get("detail") if isinstance(f, dict) else getattr(f, "detail", ""))[:100],
            )
            for f in flags[:50]
        ],
        "hard_count": details.get("hard_count"),
        "known_fake_count": details.get("known_fake_count"),
        "supporting_count": details.get("supporting_count"),
        "ignored_n": len(details.get("ignored_observations") or []),
    }
    # supporting / non-HARD observations in stats
    return out


def main() -> None:
    pdf_v2 = V2.read_bytes()
    print("=== V2 KEYWORDS / META ===")
    print(json.dumps(keywords_info(pdf_v2), ensure_ascii=False, indent=2))
    print("\n=== V2 FIELD ORDER ===")
    print(json.dumps(field_order_probe(pdf_v2), ensure_ascii=False, indent=2))
    print("\n=== V2 CONTENT FLATE ===")
    print(json.dumps(content_flate_info(pdf_v2), ensure_ascii=False, indent=2))
    print("\n=== V2 F1 ORPHAN BREAKDOWN ===")
    br = f1_orphan_breakdown(pdf_v2)
    # trim for print
    br_print = dict(br)
    br_print["composite_detail"] = br.get("composite_detail", [])[:15]
    print(json.dumps(br_print, ensure_ascii=False, indent=2, default=str))

    print("\n=== V2 EXTRA DETECTORS ===")
    print(json.dumps(run_extra_detectors(pdf_v2), ensure_ascii=False, indent=2, default=str))

    print("\n=== F2 vs SBP8 ===")
    f2v = f2_identity(pdf_v2)
    print("v2", f2v)
    if SBP8.exists():
        f2s = f2_identity(SBP8.read_bytes())
        print("sbp8", f2s)
        print("F2_dec_identical", f2v.get("ff2_dec_sha") == f2s.get("ff2_dec_sha"))
        print("F2_raw_identical", f2v.get("ff2_raw_sha") == f2s.get("ff2_raw_sha"))

    # corpus 00117 gated
    print("\n=== CORPUS 00117 SCAN ===")
    corpus_rows = []
    for p in sorted(CORPUS.glob("*.pdf")):
        try:
            data = p.read_bytes()
        except Exception:
            continue
        kw = keywords_info(data)
        if kw.get("bank5") != "00117":
            continue
        # gate via orphan profile roughly: OpenPDF + Jasper
        prod = (kw.get("producer") or "").lower()
        if "openpdf 1.3.30" not in prod:
            continue
        try:
            brc = f1_orphan_breakdown(data)
            cfl = content_flate_info(data)
        except Exception as e:
            corpus_rows.append({"file": p.name, "error": str(e)})
            continue
        corpus_rows.append(
            {
                "file": p.name,
                "orphan_simple": brc.get("orphan_simple"),
                "orphan_composite": brc.get("orphan_composite"),
                "orphan_composite_gids": brc.get("orphan_composite_gids"),
                "high_ent_n": len(brc.get("high_ent_composite_insn") or []),
                "unused_high_n": len(brc.get("unused_high_ent_insn") or []),
                "ff2_raw": brc.get("ff2_raw"),
                "ff2_dec": brc.get("ff2_dec"),
                "glyf_len": brc.get("glyf_len"),
                "content_flate": cfl.get("content_flate_raw"),
                "content_dec": cfl.get("content_decoded_len"),
                "keywords_docs": kw.get("has_DOCS_2035"),
                "sfnt_tags": brc.get("sfnt_tags"),
            }
        )

    print(f"corpus_00117_n={len(corpus_rows)}")
    # aggregates
    oc = Counter(r.get("orphan_composite") for r in corpus_rows if "error" not in r)
    os_ = Counter(r.get("orphan_simple") for r in corpus_rows if "error" not in r)
    hen = Counter(r.get("high_ent_n") for r in corpus_rows if "error" not in r)
    print("orphan_composite hist", dict(oc))
    print("orphan_simple hist", dict(os_))
    print("high_ent_composite hist", dict(hen))
    raws = sorted(r["ff2_raw"] for r in corpus_rows if isinstance(r.get("ff2_raw"), int))
    decs = sorted(r["ff2_dec"] for r in corpus_rows if isinstance(r.get("ff2_dec"), int))
    glyfs = sorted(r["glyf_len"] for r in corpus_rows if isinstance(r.get("glyf_len"), int))
    cfls = sorted(
        x
        for r in corpus_rows
        for x in (r.get("content_flate") or [])
        if isinstance(x, int)
    )
    print("F1 ff2_raw range", (min(raws), max(raws)) if raws else None, "v2", br.get("ff2_raw"))
    print("F1 ff2_dec range", (min(decs), max(decs)) if decs else None, "v2", br.get("ff2_dec"))
    print("F1 glyf range", (min(glyfs), max(glyfs)) if glyfs else None, "v2", br.get("glyf_len"))
    print("content_flate range", (min(cfls), max(cfls)) if cfls else None, "v2", content_flate_info(pdf_v2).get("content_flate_raw"))

    # how many originals have ANY composite orphan?
    with_comp = [r for r in corpus_rows if (r.get("orphan_composite") or 0) > 0]
    print(f"originals_with_composite_orphans={len(with_comp)}/{len(corpus_rows)}")
    if with_comp[:5]:
        print("examples", with_comp[:5])

    # v2 vs corpus: is composite orphan count anomalous?
    v2_oc = br.get("orphan_composite")
    print(f"V2 orphan_composite={v2_oc} orphan_simple={br.get('orphan_simple')}")
    print(f"V2 high_ent_composite={len(br.get('high_ent_composite_insn') or [])}")
    print(f"V2 unused_high_ent={len(br.get('unused_high_ent_insn') or [])}")

    # SFNT checksum validity on F1 tables for v2
    g1 = resolve_font_graph(pdf_v2)["F1"]
    ttf = g1.fontfile2_decoded
    header, records, errors = parse_sfnt_directory(ttf)
    print("\n=== V2 SFNT CHECKSUMS ===")
    print("header", header, "errors", errors)
    for rec in records:
        payload = ttf[rec.offset : rec.offset + rec.length]
        calc = _calc_table_checksum(payload)
        # head: checksumAdjustment field zeroed for calc
        if rec.tag == b"head" and len(payload) >= 12:
            adj = bytearray(payload)
            adj[8:12] = b"\x00\x00\x00\x00"
            calc_head = _calc_table_checksum(bytes(adj))
            print(
                f"  {rec.tag!r} len={rec.length} dir={rec.checksum:#x} calc={calc:#x} "
                f"calc_head_zeroed={calc_head:#x} match_raw={calc==rec.checksum} "
                f"match_head={calc_head==rec.checksum}"
            )
        else:
            print(
                f"  {rec.tag!r} len={rec.length} dir={rec.checksum:#x} calc={calc:#x} "
                f"match={calc==rec.checksum} ent={shannon(payload)}"
            )

    # dump composite pad details for v2
    print("\n=== V2 COMPOSITE ORPHAN DETAIL ===")
    for e in br.get("composite_detail") or []:
        print(e)

    # save full JSON
    out_path = BOT / "tools" / "_safecheck_v2_forensics_out.json"
    out_path.write_text(
        json.dumps(
            {
                "v2_breakdown": br,
                "v2_detectors": run_extra_detectors(pdf_v2),
                "v2_keywords": keywords_info(pdf_v2),
                "v2_content": content_flate_info(pdf_v2),
                "v2_f2": f2v,
                "sbp8_f2": f2_identity(SBP8.read_bytes()) if SBP8.exists() else None,
                "corpus_summary": {
                    "n": len(corpus_rows),
                    "orphan_composite_hist": dict(oc),
                    "orphan_simple_hist": dict(os_),
                    "high_ent_hist": dict(hen),
                    "ff2_raw_range": [min(raws), max(raws)] if raws else None,
                    "ff2_dec_range": [min(decs), max(decs)] if decs else None,
                    "glyf_range": [min(glyfs), max(glyfs)] if glyfs else None,
                    "content_flate_range": [min(cfls), max(cfls)] if cfls else None,
                    "with_composite_orphans": len(with_comp),
                },
                "corpus_rows": corpus_rows,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print("wrote", out_path)


if __name__ == "__main__":
    main()
