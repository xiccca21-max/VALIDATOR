import sys
from pathlib import Path
sys.path.insert(0, r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
import fitz

base = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки")


def txt(f):
    doc = fitz.open(stream=f.read_bytes(), filetype="pdf")
    t = "".join(p.get_text() for p in doc)
    prod = doc.metadata.get("producer", "") or ""
    doc.close()
    return t.lower(), prod


print("### GAZPROM originals: issuer anchors ###")
gz = base / "газпромбанк"
for f in sorted(gz.glob("*.pdf")):
    t, prod = txt(f)
    print(ascii(f.name[:30]), "prod=", ascii(prod[:22]),
          "| gazprombank.ru=", "gazprombank.ru" in t,
          "| банк гпб=", "банк гпб" in t,
          "| ао <газпромбанк>=", ("акционерное" in t and "газпромбанк" in t))

print()
print("### ALFA folder: does any contain gazprombank.ru or 'банк гпб'? ###")
al = base / "альфа"
hits = 0
for f in sorted(al.glob("*.pdf")):
    t, prod = txt(f)
    if "gazprombank.ru" in t or "банк гпб" in t:
        hits += 1
        print("  HIT", ascii(f.name))
print("alfa files with gazprom issuer anchor:", hits)

print()
print("### ALFA iOS recognition anchor test ###")
# candidate anchor: quartz producer + 'сформирована' + 'квитанция о переводе'
for f in sorted(al.glob("*.pdf")):
    t, prod = txt(f)
    is_ios = "quartz" in prod.lower()
    anchor = ("сформирована" in t and "квитанция о переводе" in t)
    op_c = "номер операции" in t
    if is_ios:
        print(ascii(f.name[:28]), "anchor=", anchor, "op#=", op_c,
              "| has 'альфа'=", "альфа" in t)
