import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from detector.tbank import analyze
from detector.tbank_flate_profile import enumerate_flate_streams
from detector.tbank_stream_serializer import check_mixed_flate_serializer, profiles_table

path = Path(r"C:\Users\fanis\Downloads\receipt_13.07.2026.pdf")
b = path.read_bytes()
profs = enumerate_flate_streams(b)
print("FILE:", path)
print("streams:", len(profs))
for row in profiles_table(profs):
    print(f"  {row['object']:>6}  {row['role']:14}  canonical={row['canonical_match']}  actual={row['actual_hash']}  expected={row['expected_hash']}")
sr = check_mixed_flate_serializer(b)
print("serializer stats:", sr.stats)
print("HARD:", bool(sr.hard_flags))
if sr.evidence:
    print(sr.evidence[0][:800])
r = analyze(b)
print("verdict:", r["verdict"])
print("flags:", r["flags"][:5])
