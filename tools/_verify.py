import sys
from pathlib import Path
sys.path.insert(0, r"C:\Users\fanis\OneDrive\Desktop\pdf-checker-bot")
from detector.profiles import reload_profiles, analyze
reload_profiles()
base = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки")

print("### ALFA folder ###")
bad = 0
for f in sorted((base / "альфа").glob("*.pdf")):
    r = analyze(f.read_bytes(), f.stem)
    d = r.get("details", {})
    if r["verdict"] != "ЧИСТО":
        bad += 1
        print("  NONCLEAN", ascii(f.name), r["verdict"], r["score"], d.get("bank_key"), ascii(str(r.get("flags", [])[:3])))
print("alfa non-clean:", bad)

print("### GAZPROM folder ###")
for f in sorted((base / "газпромбанк").glob("*.pdf")):
    r = analyze(f.read_bytes(), f.stem)
    d = r.get("details", {})
    print("  ", ascii(f.name[:34]), r["verdict"], r["score"], d.get("bank_key"))
