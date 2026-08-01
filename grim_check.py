"""GRIM (Granularity-Related Inconsistency of Means) test over extracted_data.csv.

GRIM asks whether a reported mean is arithmetically reachable. For a measure that
can only take integer values, the sum of N observations is an integer, so the mean
must be one of N+1 discrete values k/N. A mean of 3.47 from N=20 is impossible --
only multiples of 0.05 are reachable -- which indicates a reporting error.

The test only applies under three conditions, and a row failing any of them is
excluded and logged rather than guessed at:

  1. The sample size is known.            -> "not applicable - no sample size"
  2. The measure is integer-valued.       -> "not applicable - continuous measure"
                                             "not applicable - measure type unknown"
  3. n < 10^decimals, or granularity      -> "not applicable - no discriminating power"
     1/n is finer than the reported
     precision and every mean is reachable.

Condition 2 is a heuristic judgement made from the variable label. It is the main
limitation of this script, so every classification is written to the output file
for inspection.

Usage:
    python grim_check.py
    python grim_check.py --data extracted_data.csv --out grim_results.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

# Units and terms implying a measure on a continuous scale: GRIM cannot apply.
# Checked BEFORE the integer patterns, because a unit is stronger evidence than a
# word like "count" or "birth" appearing in the label ("White blood cell count
# (x 10^3/mL)" and "Birth weight in kgs" are both continuous).
CONTINUOUS_RE = re.compile(
    # explicit units in brackets
    r"\(\s*(kg|g|mg|cm|mm|m|kg/m2|kg/m²|m2|mmhg|mm\s*hg|mg/dl|mmol/l|mmol|µmol|umol"
    r"|g/l|g/dl|u/l|iu/l|iu|ng/ml|pg/ml|µg|ug|ml|l|l/min|mj|kj|kcal|%|s|sec|secs"
    r"|seconds|min|mins|minutes|h|hr|hrs|hours|bpm|met|mets|met-min|°c|c|years|year"
    r"|yrs|y)\s*[\)\],]"
    # rate or concentration units anywhere: MJ/day, x 10^3/mL, mg/kg/min,
    # and scientific-notation cell counts written as "[count *10^9]" or "x 10^9/L"
    r"|\b(mj|kj|kcal)\s*/|/\s*(ml|dl|l|mm3|µl|ul|day|kg|min|h|hr)\b"
    r"|×\s*10|x\s*10\^?\d|\*\s*10\^?\d|10\^\d|10\s*\d\s*\]"
    # named continuous quantities
    r"|\b(bmi|body mass index|weight|height|circumference|blood pressure|cholesterol"
    r"|triglyceride|glucose|hba1c|creatinine|albumin|haemoglobin|hemoglobin|bilirubin"
    r"|alt|ast|crp|egfr|ldl|hdl|insulin|vitamin|temperature|saturation|vo2|velocity"
    r"|density|concentration|clearance|expenditure|age)\b"
    # haematology cell populations: reported as concentrations, not tallies, so the
    # word "count" in their labels must not route them to the integer tier
    r"|\b(leu[ck]ocyte\w*|lymphocyte\w*|monocyte\w*|eosinophil\w*|neutrophil\w*"
    r"|basophil\w*|granulocyte\w*|platelet\w*|thrombocyte\w*|erythrocyte\w*"
    r"|reticulocyte\w*|h(a)?ematocrit|cell count)\b",
    re.I)

# Tier 1: named instruments scored as a sum of integer items or point allocations.
# Checked BEFORE the continuous patterns so that a name containing an incidental
# continuous keyword ("Age-adjusted Charlson Comorbidity Index") still resolves
# correctly. Only scores whose integer construction is certain belong here.
NAMED_SCORE_RE = re.compile(
    # psychiatric / cognitive instruments (sums of integer item responses)
    r"\b(hdrs|ham-?d|hamilton|hama|madrs|phq-?\d*|gad-?\d*|bdi(?:-?ii)?|beck|mmse"
    r"|moca|shaps|panss|y-?bocs|ies-?r|psqi|epworth|ess|audit|fagerstr\w+"
    r"|hads|who-?5|ces-?d)\b"
    # ICU / illness severity (integer point allocations)
    r"|\b(apache(?:\s*(?:i{1,3}v?|\d))?|sofa|qsofa|saps(?:\s*(?:ii|3|\d))?|news-?2?"
    r"|mews|rass)\b"
    # comorbidity indices (integer weight sums)
    r"|\b(charlson|cci|elixhauser|cirs(?:-g)?)\b"
    # neuro / trauma scales
    r"|\b(gcs|glasgow coma|nihss|mrs|modified rankin|rankin|hunt[\s-]and[\s-]hess"
    r"|hunt-hess|rotterdam ct|marshall ct)\b"
    # function / frailty (integer sums or ordinal levels)
    r"|\b(barthel|sppb|fugl-?meyer|fma(?:-le)?|holden|clinical frailty|katz|lawton"
    r"|braden|morse fall|apgar)\b"
    # organ-specific integer scores
    r"|\b(cha2ds2-?vasc|has-?bled|child-?pugh|meld(?:-na)?|nyha|asa)\b",
    re.I)

# Tier 3: generic count language. Weaker evidence than a named instrument, so it
# is consulted only after the continuous patterns have had their say.
# Bare "days", "times" and "admissions" are deliberately absent: they match
# timepoints ("score at admission") and rates ("stool frequency per day") that
# need not be integer. Count framing must be explicit.
INTEGER_RE = re.compile(
    # "comorbidity" is absent too: it names a section, not a count. The genuine
    # count phrasing ("number of comorbidities") is already caught by "number of",
    # and named indices like Charlson are handled in tier 1.
    r"\b(number of|no\.? of|count of|counts?|episodes?|visits?|sessions?"
    r"|children|parity|gravida|gravidity|medications?|cigarettes?"
    r"|falls?|births?|attempts?|items?|steps?)\b", re.I)

# Generated output goes here, never to the repo root, so a fresh run cannot
# overwrite the committed results of the published run.
RESULTS_DIR = Path("results")

# Valid total-score ranges for named instruments, plus an optional threshold below
# which a reported mean is more likely a per-item or subscale average than a total.
#
# The subscale threshold is set ONLY where a group mean that low cannot plausibly
# be a real total. It is deliberately absent for PHQ-9, GAD-7, BDI, MADRS, SOFA,
# Charlson and similar: low totals are genuine there (healthy-control arms, mild
# illness), and excluding them would discard real data.
#   (regex, min, max, subscale_below)
INSTRUMENT_SPECS = [
    (re.compile(r"\bpsqi\b", re.I),                      0, 21, 4),
    (re.compile(r"\b(ess|epworth)\b", re.I),             0, 24, 4),
    (re.compile(r"\bphq-?9\b", re.I),                    0, 27, None),
    (re.compile(r"\bgad-?7\b", re.I),                    0, 21, None),
    (re.compile(r"\bbdi(?:-?ii)?\b|beck depression", re.I), 0, 63, None),
    (re.compile(r"\bmadrs\b", re.I),                     0, 60, None),
    (re.compile(r"\b(hdrs|ham-?d|hamd)\b", re.I),        0, 52, None),
    (re.compile(r"\bhama\b", re.I),                      0, 56, None),
    (re.compile(r"\bces-?d\b", re.I),                    0, 60, None),
    (re.compile(r"\baudit\b", re.I),                     0, 40, None),
    (re.compile(r"\bmmse\b", re.I),                      0, 30, None),
    (re.compile(r"\bmoca\b", re.I),                      0, 30, None),
    (re.compile(r"\bsppb\b", re.I),                      0, 12, None),
    (re.compile(r"\bsofa\b", re.I),                      0, 24, None),
    (re.compile(r"\bapache\s*iii\b", re.I),              0, 299, None),
    (re.compile(r"\bapache\s*i{1,2}\b", re.I),           0, 71, None),
    (re.compile(r"\bnihss\b", re.I),                     0, 42, None),
    (re.compile(r"\b(gcs|glasgow coma)\b", re.I),        3, 15, None),
    (re.compile(r"\bbarthel\b", re.I),                   0, 100, None),
    (re.compile(r"\b(mrs|modified rankin|rankin)\b", re.I), 0, 6, None),
    (re.compile(r"\bcha2ds2-?vasc\b", re.I),             0, 9, None),
    (re.compile(r"\bhas-?bled\b", re.I),                 0, 9, None),
    (re.compile(r"\bchild-?pugh\b", re.I),               5, 15, None),
    (re.compile(r"\bnyha\b", re.I),                      1, 4, None),
    (re.compile(r"\bapgar\b", re.I),                     0, 10, None),
]

REASON_OUT_OF_RANGE = "not applicable - mean outside instrument range"
REASON_SUBSCALE = "not applicable - likely subscale or per-item average"
REASON_NO_N = "not applicable - no sample size"
REASON_CONTINUOUS = "not applicable - continuous measure"
REASON_UNKNOWN = "not applicable - measure type unknown"
REASON_NO_POWER = "not applicable - no discriminating power"


def decimals(value: str) -> int:
    return len(value.partition(".")[2])


def _classify(label: str) -> str:
    """Precedence, strongest evidence first:
      1. a named instrument known to be integer-valued
      2. a stated unit or named continuous quantity
      3. generic count language
    Anything else stays "unknown" and is excluded rather than assumed.
    """
    if NAMED_SCORE_RE.search(label):
        return "integer"
    if CONTINUOUS_RE.search(label):
        return "continuous"
    if INTEGER_RE.search(label):
        return "integer"
    return "unknown"


def classify_measure(variable: str) -> str:
    """"integer", "continuous", or "unknown" from the variable label.

    extract_tables.py prefixes a row's own label with its section divider
    ("ASA, n(%) - Height(m)"). The row's own label is the authority on what the
    measure is; the section text is consulted only when the row label alone says
    nothing ("Age - Mean (SD)"). Without this split, a section heading naming an
    instrument would reclassify every continuous row beneath it.
    """
    own = variable.rpartition(" - ")[2] or variable
    verdict = _classify(own)
    if verdict != "unknown":
        return verdict

    # Fall back to the full label, but only to EXCLUDE. A section heading may
    # rule a row out ("Age - Mean (SD)" is continuous), never rule one in: a
    # heading like "Type of diabetes medication" would otherwise admit the
    # continuous rows beneath it (QUICKI, EQ-5D) to a test that cannot apply.
    fallback = _classify(variable)
    return fallback if fallback == "continuous" else "unknown"


def instrument_range(label: str) -> tuple[float, float, float | None] | None:
    """(min, max, subscale_below) for the first matching named instrument."""
    own = label.rpartition(" - ")[2] or label
    for pattern, lo, hi, sub in INSTRUMENT_SPECS:
        if pattern.search(own):
            return lo, hi, sub
    return None


def range_verdict(label: str, mean: str) -> str | None:
    """Reason to exclude this row on instrument-range grounds, or None.

    A mean outside the instrument's possible total range cannot be a total at all.
    A mean below `subscale_below` is more consistent with a per-item or subscale
    average, which is not the integer-sum quantity GRIM tests.
    """
    spec = instrument_range(label)
    if spec is None:
        return None
    lo, hi, sub = spec
    try:
        value = float(mean)
    except ValueError:
        return None
    if value < lo or value > hi:
        return REASON_OUT_OF_RANGE
    if sub is not None and value < sub:
        return REASON_SUBSCALE
    return None


def grim(mean: str, n: int) -> tuple[bool, str]:
    """Is `mean` reachable as a mean of n integers? Returns (consistent, nearest)."""
    d = decimals(mean)
    quant = Decimal(1).scaleb(-d)
    try:
        target = Decimal(mean).quantize(quant, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return True, mean

    base = math.floor(float(mean) * n)
    best, best_gap = None, None
    for total in (base - 1, base, base + 1):
        candidate = (Decimal(total) / Decimal(n)).quantize(quant,
                                                           rounding=ROUND_HALF_UP)
        if candidate == target:
            return True, str(candidate)
        gap = abs(candidate - target)
        if best_gap is None or gap < best_gap:
            best, best_gap = candidate, gap
    return False, str(best)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path,
                        default=RESULTS_DIR / "extracted_data.csv")
    parser.add_argument("--out", type=Path, default=RESULTS_DIR / "grim_results.csv")
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    if not args.data.exists():
        print(f"{args.data} not found", file=sys.stderr)
        return 1

    rows = list(csv.DictReader(args.data.open(encoding="utf-8")))
    results: list[dict] = []
    cats: Counter[str] = Counter()
    reasons: Counter[str] = Counter()

    for r in rows:
        out = dict(r)
        out["measure_type"] = kind = classify_measure(r["variable"])
        out["granularity"] = out["nearest_achievable"] = ""

        if not r["n"]:
            category, reason = "not-applicable", REASON_NO_N
        elif kind == "continuous":
            category, reason = "not-applicable", REASON_CONTINUOUS
        elif kind == "unknown":
            category, reason = "not-applicable", REASON_UNKNOWN
        elif range_verdict(r["variable"], r["mean"]):
            category = "not-applicable"
            reason = range_verdict(r["variable"], r["mean"])
        else:
            n = int(r["n"])
            d = decimals(r["mean"])
            if n <= 0:
                category, reason = "not-applicable", REASON_NO_N
            elif n >= 10 ** d:
                category, reason = "not-applicable", REASON_NO_POWER
                out["granularity"] = f"1/{n}={1/n:.5f}"
            else:
                consistent, nearest = grim(r["mean"], n)
                category = "checked-passed" if consistent else "checked-flagged"
                reason = "" if consistent else f"mean unreachable for n={n}"
                out["granularity"] = f"1/{n}={1/n:.5f}"
                out["nearest_achievable"] = nearest

        out["category"] = category
        out["reason"] = reason
        results.append(out)
        cats[category] += 1
        if reason:
            reasons[reason] += 1

    fields = list(rows[0]) + ["measure_type", "category", "reason",
                              "granularity", "nearest_achievable"]
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
