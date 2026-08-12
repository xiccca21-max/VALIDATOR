# -*- coding: utf-8 -*-
from pathlib import Path
from detector import route, profiles
import fitz

for name in ["alfa_card.pdf", "alfa_sbp.pdf", "gpb_receipt.pdf"]:
    p = Path("/tmp/pdfbot_smoke") / name
    b = p.read_bytes()
    doc = fitz.open(stream=b, filetype="pdf")
    text = "".join(x.get_text() for x in doc)
    prod = (doc.metadata or {}).get("producer") or ""
    doc.close()
    prof, sc = profiles.identify(text, prod)
    bank, r, _ = route(b)
    d = r.get("details") or {}
    print(
        name,
        "identify=", (prof or {}).get("key"),
        "route=", bank,
        r.get("verdict"),
        r.get("score"),
        d.get("engine"),
    )
    for f in (r.get("flags") or [])[:3]:
        print(" ", str(f)[:160])
