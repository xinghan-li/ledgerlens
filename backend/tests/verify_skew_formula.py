"""Verify skew formula: which direction aligns PEAR with FP $7.72?"""
# Raw data from 20260209_154003_1.json
date = {"cx": 0.19398, "cy": 0.47747}
d0 = {"cx": 0.75139, "cy": 0.50234}
pear = {"cx": 0.21204, "cy": 0.55052}
fp = {"cx": 0.73333, "cy": 0.55260}

x_left, x_right = date["cx"], d0["cx"]
x_span = x_right - x_left
offset = d0["cy"] - date["cy"]  # y_right - y_left = +0.025

print("Raw: date cy=%.4f, $0.00 cy=%.4f, offset=%.4f" % (date["cy"], d0["cy"], offset))
print("Raw: PEAR cy=%.4f, FP cy=%.4f, diff=%.4f" % (pear["cy"], fp["cy"], fp["cy"] - pear["cy"]))

# Formula A: right ref, add to left: correction = offset * (x_right - x) / x_span
def formula_A(x, y):
    correction = offset * (x_right - x) / x_span
    return y + correction

# Formula B: left ref, sub from right: correction = -offset * (x - x_left) / x_span
def formula_B(x, y):
    correction = -offset * (x - x_left) / x_span
    return y + correction

pear_A = formula_A(pear["cx"], pear["cy"])
fp_A = formula_A(fp["cx"], fp["cy"])
pear_B = formula_B(pear["cx"], pear["cy"])
fp_B = formula_B(fp["cx"], fp["cy"])

print("\nFormula A (right ref, add left): PEAR=%.4f, FP=%.4f, diff=%.4f" % (pear_A, fp_A, abs(pear_A - fp_A)))
print("Formula B (left ref, sub right): PEAR=%.4f, FP=%.4f, diff=%.4f" % (pear_B, fp_B, abs(pear_B - fp_B)))

# User said: 0.5505 + offset -> 0.5730 would align with 0.5526
# 0.5505 + 0.0225 = 0.5730. So user expects PEAR to get +0.0225
# With formula A: PEAR correction = offset * (0.751 - 0.212) / 0.557 = 0.0249 * 0.97 = 0.0242
print("\nUser: PEAR 0.5505 -> 0.5730 (add ~0.0225)")
print("Formula A gives PEAR correction: %.4f -> %.4f" % (offset * (x_right - pear["cx"]) / x_span, pear_A))
print("0.5505 + 0.025 = %.4f (full offset on left)" % (pear["cy"] + offset))
