import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fitz
from detector.ozon_serializer_mix import check_ozon_serializer_mix
from detector.ozon_m105_profile import claims_ozon_m105_cluster
from detector.tbank_sbp_content import validate_tbank_sbp_id
from detector.sbp_cipher import extract_sbp_opid
from detector.tbank_text_layout_fingerprint import check_tbank_layout_fingerprint
from detector.structure import content_stream_bytes

paths = [
    Path(r"C:\Users\fanis\Downloads\Telegram Desktop\ozonbank_document_20260713182949.pdf"),
    Path(r"C:\Users\fanis\Downloads\Telegram Desktop\receipt (2).pdf"),
]
lines = []
for p in paths:
    lines.append("="*60)
    lines.append(str(p))
    b = p.read_bytes()
    d = fitz.open(stream=b, filetype="pdf")
    text = d[0].get_text()
    meta = d.metadata or {}
    d.close()
    pr, cr = meta.get("producer",""), meta.get("creator","")
    if "ozon" in p.name.lower() or "ozonbank" in p.name.lower():
        gate = claims_ozon_m105_cluster(b, producer=pr, creator=cr)
        mix = check_ozon_serializer_mix(b, producer=pr, creator=cr)
        raw = content_stream_bytes(b) or b""
        pre_lines = raw.decode("latin1","replace").splitlines()
        bt = next((i for i,l in enumerate(pre_lines) if " BT" in f" {l} " or l.strip()=="BT"), -1)
        lines += [f"gate matched={gate.matched} reason={gate.reason}", f"gate stats={gate.stats}"]
        lines += [f"mix flags={[(f.code,f.detail[:120]) for f in mix.flags]}", f"mix stats={mix.stats}"]
        if bt>=0:
            lines += [f"pre_bt={len(pre_lines[:bt])} first_pre={pre_lines[0][:120]}", f"post_head={pre_lines[bt:bt+6]}"]
    else:
        opid = extract_sbp_opid(text) or ""
        lines += [f"opid={opid}", f"ID[15]={opid[15] if len(opid)>15 else ''} ID[16]={opid[16] if len(opid)>16 else ''} ID[17]={opid[17] if len(opid)>17 else ''} class={opid[17:19] if len(opid)>18 else ''}"]
        sbp = validate_tbank_sbp_id(opid, text, b, producer=pr, creator=cr)
        lines += [f"sbp flags={[(f.code,f.detail[:100]) for f in sbp.flags]}"]
        layout = check_tbank_layout_fingerprint(b, text, shadow=False, regression_passed=True)
        lines += [f"layout hard={layout.hard_flags}", f"layout stats={layout.stats}"]
        for ln in layout.lines:
            if "000" in ln.text or ln.deviation > 1:
                lines.append(f"  {ln.text[:30]!r} font={ln.font} end={ln.end_x} dev={ln.deviation}")

out = Path(__file__).resolve().parents[1] / "_rules_probe.txt"
out.write_text("\n".join(lines), encoding="utf-8")
print("ok")
