import sys
from pathlib import Path
sys.path.insert(0, r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
import fitz

base = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки\альфа")
for name in ["Квитанция (10).pdf", "Квитанция (13).pdf", "Квитанция (14).pdf"]:
    f = base / name
    if not f.exists():
        print("MISSING", ascii(name)); continue
    doc = fitz.open(stream=f.read_bytes(), filetype="pdf")
    txt = "".join(p.get_text() for p in doc)
    doc.close()
    print("=" * 60)
    print(ascii(name))
    for i, ln in enumerate(txt.splitlines()):
        if ln.strip():
            print(i, ascii(ln.strip()))
