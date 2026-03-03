"""
Reproduce address match score: why does 13109 vs 18109 give ~0.87?
Run from repo root: python temp/reproduce_address_score.py
"""
import sys
sys.path.insert(0, "backend")

from rapidfuzz import fuzz

def normalize(s):
    if not s:
        return ""
    return " ".join(s.lower().replace("\n", " ").replace("\r", " ").split())

# Receipt (OCR might give this - user said 18109 was scanned as 13109)
receipt_addr = "13109 33rd Ave W\nLynnwood, WA 98037"
# DB Costco Lynnwood (from store_locations: address_line1 + city, state zip)
db_addr_canonical = "18109 33rd Ave W\nLynnwood, WA 98037"

# Normalized (what address_matcher uses)
addr_norm = normalize(receipt_addr)
db_norm = normalize(db_addr_canonical)

print("=== Normalized strings ===")
print("addr_norm (receipt):", repr(addr_norm))
print("db_norm (DB):       ", repr(db_norm))
print("len(addr_norm):", len(addr_norm))
print("len(db_norm):", len(db_norm))
print()

# token_sort_ratio: sort tokens, then ratio on the joined string
score_ts = fuzz.token_sort_ratio(addr_norm, db_norm)
print("token_sort_ratio (raw 0-100):", score_ts)
print("token_sort_ratio (as float):  ", score_ts / 100.0)
print()

# Also try plain ratio to see difference
score_ratio = fuzz.ratio(addr_norm, db_norm)
print("ratio (raw 0-100):", score_ratio)
print("ratio (as float): ", score_ratio / 100.0)
print()

# If receipt had extra tokens (e.g. "#1190" or "1_109") that could lower score
variants = [
    ("13109 33rd ave w lynnwood wa 98037", "18109 33rd ave w lynnwood wa 98037"),
    ("13109 33rd ave w lynnwood #1190 wa 98037", "18109 33rd ave w lynnwood wa 98037"),
    ("13109 33rd ave w lynnwood, #1190 wa 98037", "18109 33rd ave w lynnwood wa 98037"),
    ("1_109 33rd ave w lynnwood wa 98037", "18109 33rd ave w lynnwood wa 98037"),
    ("13109 33rd ave w ly nnwood wa 98037", "18109 33rd ave w lynnwood wa 98037"),
    # DB might have different format (e.g. with comma in "lynnwood, wa")
    ("13109 33rd ave w lynnwood, wa 98037", "18109 33rd ave w lynnwood, wa 98037"),
]
print("=== Score variants (token_sort_ratio) ===")
for a, b in variants:
    s = fuzz.token_sort_ratio(a, b) / 100.0
    print(f"  {s:.2f}  | receipt: {a[:50]}... | db: {b[:50]}...")
print()

# Conclusion: 1 char diff (13109 vs 18109) in same token list -> ~0.97, NOT 0.87.
# So 0.87 in production likely = receipt has EXTRA token(s), e.g. "Lynnwood #1190" -> "lynnwood #1190 wa"
# (extra token "#1190" or "1190") which makes token_sort_ratio drop to ~0.87-0.89.
print("CONCLUSION: Pure 13109 vs 18109 -> 0.97. Score 0.87 likely from receipt having extra token (e.g. #1190).")
