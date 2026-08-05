"""GRIMMER test over extracted_data.csv - the SD counterpart to GRIM.

GRIM constrains the mean of integer data: the total is an integer, so the mean
must be total/n. GRIMMER extends the same argument to the standard deviation.
If every value is an integer then the sum of squares is an integer too, which
pins the SD down to a discrete set of reachable values.

Three conditions must hold together:

  1. The mean is GRIM-consistent - at least one integer total rounds to it.
  2. Some integer sum of squares falls inside the interval implied by the
     reported SD's rounding bounds.
  3. That sum of squares has the same parity as the total. For any integer x,
     x squared and x share a parity, so summing over the sample gives
     sum-of-squares congruent to total, modulo 2.

The candidate is then reconstructed and rounded back, to confirm it reproduces
the reported SD rather than merely sitting near it.

Applicability is decided by the same classifier as grim_check.py, so a row
excluded there is excluded here for the same stated reason. Two exclusions are
specific to this test:

  * no SD reported                  -> "not applicable - no standard deviation"
  * the mean already fails GRIM     -> "not applicable - mean fails GRIM"
    (grim_check.py reports that row; repeating it here would double-count)

GRIMMER is a weaker net than GRIM. An SD one unit away from the true value is
often still reachable, so a pass is weaker evidence than a GRIM pass. A failure
means the same thing a GRIM failure does: the reported value cannot have come
from integer data at the stated sample size, whatever the cause.

Usage:
    python grimmer_check.py
    python grimmer_check.py --data extracted_data.csv --out grimmer_results.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections import Counter
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP
from pathlib import Path

from grim_check import (MEDIAN_RE, REASON_MEDIAN, RESULTS_DIR,
                        classify_measure, decimals, range_verdict)

REASON_NO_N = "not applicable - no sample size"
REASON_CONTINUOUS = "not applicable - continuous measure"
REASON_UNKNOWN = "not applicable - measure type unknown"
REASON_NO_SD = "not applicable - no standard deviation"
REASON_MEAN_FAILS = "not applicable - mean fails GRIM"


def _rounds_to(value: float, target: str, d: int) -> bool:
    """Does `value` round to the reported string, under either convention?"""
    quant = Decimal(1).scaleb(-d)
    try:
        dec = Decimal(repr(value))
    except Exception:
        return False
    for mode in (ROUND_HALF_UP, ROUND_HALF_EVEN):
        if dec.quantize(quant, rounding=mode) == Decimal(target):
            return True
    return False


def grim_totals(mean: str, n: int) -> list[int]:
    """Every integer total whose quotient rounds to the reported mean."""
    d = decimals(mean)
    try:
        base = math.floor(float(mean) * n)
    except ValueError:
        return []
    return [t for t in range(base - 2, base + 3) if _rounds_to(t / n, mean, d)]


def grimmer(mean: str, sd: str, n: int) -> tuple[bool, str]:
    """Is (mean, sd) reachable from n integers? Returns (consistent, note)."""
    if n < 2:
        return True, "n < 2, SD undefined"

    totals = grim_totals(mean, n)
    if not totals:
        return False, "mean is not GRIM-consistent"

    d_sd = decimals(sd)
    half = 0.5 * 10 ** (-d_sd)
    try:
        sd_val = float(sd)
    except ValueError:
        return True, "SD not numeric"
    sd_lo = max(0.0, sd_val - half)
    sd_hi = sd_val + half

    for total in totals:
        offset = total * total / n
        ss_lo = sd_lo * sd_lo * (n - 1) + offset
        ss_hi = sd_hi * sd_hi * (n - 1) + offset

        for ss in range(math.ceil(ss_lo - 1e-9), math.floor(ss_hi + 1e-9) + 1):
            if (ss - total) % 2 != 0:            # parity condition
                continue
            var = (ss - offset) / (n - 1)
            if var < 0:
                continue
            if _rounds_to(math.sqrt(var), sd, d_sd):
                return True, f"total={total}, sum of squares={ss}"

    return False, f"no integer sum of squares reproduces SD={sd} at n={n}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path,
                        default=RESULTS_DIR / "extracted_data.csv")
    parser.add_argument("--out", type=Path,
                        default=RESULTS_DIR / "grimmer_results.csv")
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    if not args.data.exists():
        print(f"{args.data} not found", file=sys.stderr)
        return 1

    rows = list(csv.DictReader(args.data.open(encoding="utf-8")))
    if not rows:
        print(f"{args.data} has no rows", file=sys.stderr)
        return 1

    results: list[dict] = []
    cats: Counter[str] = Counter()
    reasons: Counter[str] = Counter()

    for r in rows:
        out = dict(r)
        out["measure_type"] = kind = classify_measure(r["variable"])
        out["note"] = ""

        sd = (r.get("sd") or "").strip()

        if not r["n"]:
            category, reason = "not-applicable", REASON_NO_N
        elif MEDIAN_RE.search(r["variable"]):
            category, reason = "not-applicable", REASON_MEDIAN
        elif kind == "continuous":
            category, reason = "not-applicable", REASON_CONTINUOUS
        elif kind == "unknown":
            category, reason = "not-applicable", REASON_UNKNOWN
        elif not sd:
            category, reason = "not-applicable", REASON_NO_SD
        elif range_verdict(r["variable"], r["mean"]):
            category = "not-applicable"
            reason = range_verdict(r["variable"], r["mean"])
        else:
            n = int(r["n"])
            if n < 2:
                category, reason = "not-applicable", REASON_NO_N
            elif not grim_totals(r["mean"], n):
                # grim_check.py already reports this row; do not double-count it
                category, reason = "not-applicable", REASON_MEAN_FAILS
            else:
                consistent, note = grimmer(r["mean"], sd, n)
                category = "checked-passed" if consistent else "checked-flagged"
                reason = "" if consistent else f"SD unreachable for n={n}"
                out["note"] = note

        out["category"] = category
        out["reason"] = reason
        results.append(out)
        cats[category] += 1
        if reason:
            reasons[reason] += 1

    fields = list(rows[0]) + ["measure_type", "category", "reason", "note"]
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)

    checkable = cats["checked-passed"] + cats["checked-flagged"]
    flagged = cats["checked-flagged"]

    print(f"rows in {args.data}: {len(rows)}\n")
    print(f"  checked-flagged: {flagged}")
    print(f"  checked-passed:  {cats['checked-passed']}")
    print(f"  not-applicable:  {cats['not-applicable']}")
    for reason, count in reasons.most_common():
        if reason.startswith("not applicable"):
            print(f"      {count:5d}  {reason}")
    print(f"\ncheckable rows (the denominator): {checkable}")
    if checkable:
        print(f"flagged: {flagged}/{checkable} = {flagged / checkable:.1%}")
    else:
        print("flagged: n/a - nothing was checkable")
    print(f"\nfull results -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
