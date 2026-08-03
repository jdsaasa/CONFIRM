import csv, math
from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_EVEN

def reachable(mean, n, mode):
    d = len(mean.partition(".")[2])
    q = Decimal(1).scaleb(-d)
    base = math.floor(float(mean) * n)
    for t in range(base - 2, base + 3):
        if (Decimal(t) / Decimal(n)).quantize(q, rounding=mode) == Decimal(mean):
            return True
    return False

hidden = []
for r in csv.DictReader(open("results/grim_results_v11.csv", encoding="utf-8")):
    if r["category"] != "checked-passed":
        continue
    try:
        n = int(r["n"]); m = r["mean"]; float(m)
    except (ValueError, TypeError):
        continue
    if not reachable(m, n, ROUND_HALF_UP) and reachable(m, n, ROUND_HALF_EVEN):
        hidden.append((r["pmcid"], n, m, r["variable"]))

print(f"passed rows reachable ONLY under banker's rounding: {len(hidden)}")
for h in hidden[:20]:
    print("  ", h)