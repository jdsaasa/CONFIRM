"""Check one reported mean/SD/n by hand, showing every step.

Nothing here needs the published table. Once the three numbers are known the
question is pure arithmetic: could n whole numbers produce this mean and this
SD? The table only confirms the three numbers were read correctly.

Usage:
    python sd_check.py 25.00 1.75 28
"""

import math
import sys
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP


def rounds_to(value, target, d):
    q = Decimal(1).scaleb(-d)
    dv = Decimal(repr(value))
    return any(dv.quantize(q, rounding=m) == Decimal(target)
               for m in (ROUND_HALF_UP, ROUND_HALF_EVEN))


def check(mean, sd, n):
    d_m = len(mean.partition(".")[2])
    d_s = len(sd.partition(".")[2])

    print(f"\nmean {mean}, SD {sd}, n = {n}\n")

    base = math.floor(float(mean) * n)
    totals = [t for t in range(base - 3, base + 4) if rounds_to(t / n, mean, d_m)]
    print("1. Totals whose quotient rounds to the reported mean:")
    for t in totals:
        print(f"     {t} / {n} = {t/n:.6f}")
    if not totals:
        print("     none - the MEAN itself is impossible (GRIM failure)")
        return

    half = 0.5 * 10 ** (-d_s)
    lo_sd, hi_sd = float(sd) - half, float(sd) + half
    print(f"\n2. Reported SD {sd} means the true SD is between "
          f"{lo_sd:.6g} and {hi_sd:.6g}\n")

    for denom, label in ((n - 1, "sample SD (divide by n-1, the usual convention)"),
                         (n, "population SD (divide by n)")):
        print(f"3. Assuming {label}:")
        found = False
        for total in totals:
            offset = total * total / n
            lo = lo_sd * lo_sd * denom + offset
            hi = hi_sd * hi_sd * denom + offset
            cands = list(range(math.ceil(lo - 1e-9), math.floor(hi + 1e-9) + 1))
            print(f"     total {total}: sum of squares must lie in "
                  f"[{lo:.2f}, {hi:.2f}] -> whole numbers {cands or 'none'}")
            for ss in cands:
                parity = "even" if (ss - total) % 2 == 0 else "ODD - impossible"
                var = (ss - offset) / denom
                back = math.sqrt(var) if var >= 0 else float("nan")
                mark = ""
                if (ss - total) % 2 == 0 and rounds_to(back, sd, d_s):
                    mark = "  <-- WORKS"
                    found = True
                print(f"       {ss}: parity vs total {total} is {parity}; "
                      f"gives SD {back:.4f}{mark}")
        print(f"     => {'REACHABLE' if found else 'NOT REACHABLE'}\n")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("usage: python sd_check.py <mean> <sd> <n>")
        sys.exit(1)
    check(sys.argv[1], sys.argv[2], int(sys.argv[3]))
