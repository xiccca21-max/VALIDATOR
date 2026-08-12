from pathlib import Path
import sys
from collections import Counter

sys.stdout.reconfigure(line_buffering=True)
from detector import route

ROOT = Path(r"C:\Users\fanis\OneDrive\Desktop\чеки")
pdfs = sorted(ROOT.rglob("*.pdf"))
print(f"TOTAL {len(pdfs)}", flush=True)

verdicts = Counter()
banks = Counter()
fps = []
errors = []

for i, p in enumerate(pdfs, 1):
    try:
        data = p.read_bytes()
        bank, r, _ = route(data)
    except Exception as e:
        errors.append((str(p.relative_to(ROOT)), repr(e)))
        print(f"ERR {p.relative_to(ROOT)} {e!r}", flush=True)
        continue
    v = r.get("verdict") or "?"
    verdicts[v] += 1
    banks[bank or "?"] += 1
    if v not in ("ЧИСТО", "ОРИГИНАЛ") and "чист" not in (v or "").lower():
        # anything that is not clean
        flags = r.get("flags") or []
        hard = []
        details = r.get("details") or {}
        # collect hard codes
        if isinstance(flags, list):
            for f in flags:
                if isinstance(f, dict):
                    hard.append(f.get("code") or f.get("rule_id") or str(f)[:80])
                else:
                    hard.append(str(f)[:80])
        # also from details
        for key in ("hard_flags", "hard", "signals"):
            pass
        um = (r.get("user_message") or "")[:120]
        fps.append({
            "path": str(p.relative_to(ROOT)),
            "bank": bank,
            "verdict": v,
            "score": r.get("score"),
            "emoji": r.get("emoji"),
            "flags": hard[:12],
            "user_message": um,
            "hard_count": details.get("hard_count"),
        })
        print(f"FP {bank} {v} {p.relative_to(ROOT)} flags={hard[:6]}", flush=True)
    if i % 50 == 0:
        print(f"scanned {i}/{len(pdfs)} fps={len(fps)}", flush=True)

print("DONE", flush=True)
print("verdicts", dict(verdicts), flush=True)
print("banks", dict(banks), flush=True)
print("FP_COUNT", len(fps), flush=True)
print("ERR_COUNT", len(errors), flush=True)
for row in fps:
    print("---", flush=True)
    print(row["path"], flush=True)
    print(" ", row["bank"], row["verdict"], "hard_count=", row["hard_count"], flush=True)
    print(" ", row["flags"], flush=True)
    print(" ", row["user_message"], flush=True)
