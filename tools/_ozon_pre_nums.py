import re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from detector.structure import content_stream_bytes

def pre_nums(path):
    c = content_stream_bytes(path.read_bytes()) or b""
    lines = c.decode("latin1","replace").splitlines()
    bt = next(i for i,l in enumerate(lines) if re.search(r"\bBT\b", l))
    pre = "\n".join(lines[:bt])
    return sorted(set(re.findall(r"-?\d+\.\d+", pre)))

fake = Path(r"C:\Users\fanis\Downloads\Telegram Desktop\ozon_950000.pdf")
orig = Path(r"C:\Users\fanis\OneDrive\Desktop\озон чекии\ozonbank_document_20260131234526.pdf")
fn, on = pre_nums(fake), pre_nums(orig)
print("only fake", set(fn)-set(on))
print("only orig", set(on)-set(fn))
