import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from detector.structure import content_stream_bytes

CLUSTER_OK = {".23999999", "-.23999999", "877.91998", "809.03998", "842.88", "774", "912", "4.1722445"}

def long_dec(path):
    c = content_stream_bytes(path.read_bytes()) or b""
    nums = re.findall(r"-?\d+\.\d+", c.decode("latin1","replace"))
    bad = [n for n in nums if len(n.split(".")[-1]) >= 7 and n.lstrip("-") not in CLUSTER_OK]
    return sorted(set(bad))[:10]

for p in [
    r"C:\Users\fanis\Downloads\Telegram Desktop\ozon_950000.pdf",
    r"C:\Users\fanis\Downloads\Telegram Desktop\ozonbank_document_20260713182949.pdf",
    r"C:\Users\fanis\OneDrive\Desktop\озон чекии\ozonbank_document_20260131234526.pdf",
]:
    print(Path(p).name, long_dec(Path(p)))
