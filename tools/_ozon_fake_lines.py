import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from detector.structure import content_stream_bytes

def show(name, b):
    c = content_stream_bytes(b) or b""
    lines = c.decode("latin1","replace").splitlines()
    bt = next(i for i,l in enumerate(lines) if re.search(r"\bBT\b", l))
    pre = lines[:bt]
    post = lines[bt:bt+30]
    print("===", name, "pre", len(pre))
    print("L0:", pre[0])
    print("L1:", pre[1] if len(pre)>1 else "")
    print("L2:", pre[2] if len(pre)>2 else "")
    # trailing zero Tm in post-BT
    tz = [l for l in lines[bt:bt+200] if re.search(r"\d+\.\d{4,}\s", l)]
    print("post tz sample:", tz[:5])
    print("bt block:", post[:8])

for p in [
    r"C:\Users\fanis\Downloads\Telegram Desktop\ozon_950000.pdf",
    r"C:\Users\fanis\Downloads\Telegram Desktop\ozonbank_document_20260713182949.pdf",
    r"C:\Users\fanis\OneDrive\Desktop\озон чекии\ozonbank_document_20260131234526.pdf",
]:
    show(Path(p).name, Path(p).read_bytes())
