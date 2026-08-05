"""Run CONFIRM's checks against a single trial and report in prose.

The bulk pipeline answers "which of these thousands of papers is worth a
look". This answers "what does the arithmetic say about this one paper",
which is the question a reviewer working through INSPECT-SR check 4.8 has.

It shells out to the three existing stages rather than reimplementing them,
so the verified code path is the one that runs.

Usage:
    python confirm_one.py 42345586          # PMID
    python confirm_one.py PMC13296589       # PMCID
    python confirm_one.py 42345586 --keep   # leave the working files in place
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP
from pathlib import Path

HERE = Path(__file__).resolve().parent

_DASHES = str.maketrans({"\u2010": "-", "\u2011": "-", "\u2012": "-",
                         "\u2013": "-", "\u2014": "-", "\u2212": "-"})

# A trailing count/percent fragment left behind when the sample size was
# lifted out of the column header: "... frequency (%", "..., n (%)", "... (%".
_TRAILING_COUNT = re.compile(
    r"[\s,;:-]*(?:frequency|freq\.?|no\.?|n)?\s*\(\s*%\s*\)?\s*$", re.I)


def clean_label(label: str) -> str:
    """Tidy a column header for display. Does not touch the stored data."""
    s = label.translate(_DASHES).strip()
    s = _TRAILING_COUNT.sub("", s)
    if s.count("(") > s.count(")"):          # drop an unclosed bracket
        s = s[:s.rfind("(")]
    s = s.strip(" ,;:-")
    return s or label



def build_query(identifier: str) -> str:
    """PubMed query for one article, from either identifier form."""
    ident = identifier.strip()
    if ident.upper().startswith("PMC"):
        return f"{ident.upper()}[pmcid]"
    if ident.isdigit():
        return f"{ident}[pmid]"
    raise SystemExit(f"'{identifier}' is not a PMID or a PMCID.")


def run(cmd: list[str]) -> None:
    """Run one pipeline stage, surfacing its output only if it fails."""
    result = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"\nstage failed: {' '.join(cmd)}\n", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(1)


def neighbours(mean: str, n: int) -> tuple[str, str, int, int]:
    """The two achievable means either side of a reported value."""
    d = len(mean.partition(".")[2])
    quant = Decimal(1).scaleb(-d)
    lo = math.floor(float(mean) * n)
    # step out until the pair genuinely brackets the reported value
    while (Decimal(lo) / Decimal(n)).quantize(quant, rounding=ROUND_HALF_UP) > Decimal(mean):
        lo -= 1
    hi = lo + 1
    lo_v = (Decimal(lo) / Decimal(n)).quantize(quant, rounding=ROUND_HALF_UP)
    hi_v = (Decimal(hi) / Decimal(n)).quantize(quant, rounding=ROUND_HALF_EVEN)
    return str(lo_v), str(hi_v), lo, hi


def report(rows: list[dict], identifier: str) -> None:
    flagged = [r for r in rows if r["category"] == "checked-flagged"]
    passed = [r for r in rows if r["category"] == "checked-passed"]
    excluded = [r for r in rows if r["category"] == "not-applicable"]
    checkable = len(flagged) + len(passed)

    print()
    print("CONFIRM - single-trial check")
    print("=" * 60)
    print(f"Paper:  {identifier}")
    print(f"Rows extracted from the baseline table:  {len(rows)}")
    print()
    print("GRIM (INSPECT-SR check 4.8)")
    print("-" * 60)

    if checkable == 0:
        print("No rows were checkable, so GRIM was not applied to this paper.")
        print("This is not a clean result: it means the test could not run.")
    elif not flagged:
        print(f"No inconsistencies found. {checkable} of {len(rows)} rows were")
        print(f"checkable; all {checkable} report a mean reachable at the stated")
        print("sample size.")
    else:
        print(f"{len(flagged)} of {checkable} checkable rows report a mean that is not")
        print("reachable at the stated sample size:")
        print()
        for r in flagged:
            n = int(r["n"])
            lo_v, hi_v, lo_t, hi_t = neighbours(r["mean"], n)
            print(f"  {r['variable']}")
            print(f"    group {clean_label(r['group'])!r}, n = {n}")
            print(f"    reported {r['mean']}; achievable "
                  f"{lo_t}/{n} = {lo_v} and {hi_t}/{n} = {hi_v}")
            print()

    print("Coverage")
    print("-" * 60)
    print(f"{len(rows)} rows extracted, of which {checkable} were checkable.")
    if excluded:
        print(f"{len(excluded)} excluded and not tested:")
        reasons: dict[str, int] = {}
        for r in excluded:
            key = r["reason"].replace("not applicable - ", "")
            reasons[key] = reasons.get(key, 0) + 1
        for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print(f"    {count:4}  {reason}")
    print()
    print("GRIM applies only to measures that can take integer values, at")
    print("sample sizes small enough for the test to discriminate. Excluded")
    print("rows have not been tested and no conclusion should be drawn about")
    print("them. A flagged mean means the reported value is not reachable as")
    print("a mean of integers at the stated n; it does not by itself indicate")
    print("the cause.")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("identifier", help="PMID (42345586) or PMCID (PMC13296589)")
    parser.add_argument("--keep", action="store_true",
                        help="keep the intermediate files instead of deleting them")
    args = parser.parse_args()

    query = build_query(args.identifier)
    workdir = Path(tempfile.mkdtemp(prefix="confirm_one_", dir=HERE))
    xml_dir = workdir / "xml"
    data_csv = workdir / "extracted.csv"
    grim_csv = workdir / "grim.csv"

    try:
        print(f"fetching {args.identifier} ...", file=sys.stderr)
        run([sys.executable, "fetch_papers.py", "--query", query,
             "--retmax", "1", "--outdir", str(xml_dir),
             "--failed", str(workdir / "failed.csv")])

        xml_files = list(xml_dir.glob("*.xml"))
        if not xml_files:
            raise SystemExit(
                f"No PMC full text found for {args.identifier}. The article may "
                "not be deposited in PMC, or the identifier may be wrong.")

        print("extracting the baseline table ...", file=sys.stderr)
        run([sys.executable, "extract_tables.py", "--indir", str(xml_dir),
             "--out", str(data_csv), "--skipped", str(workdir / "skipped.csv"),
             "--unverified", str(workdir / "unverified.csv"),
             "--borderline", str(workdir / "borderline.csv")])

        rows_in = list(csv.DictReader(data_csv.open(encoding="utf-8")))
        if not rows_in:
            skipped = workdir / "skipped.csv"
            reason = ""
            if skipped.exists():
                for r in csv.DictReader(skipped.open(encoding="utf-8")):
                    reason = r.get("reason", "")
                    break
            print(f"\nNo baseline table could be extracted from {args.identifier}.")
            if reason:
                print(f"Reason: {reason}")
            print("CONFIRM selects tables by caption and does not guess, so this")
            print("means no caption matched a baseline/characteristics pattern, or")
            print("the table's structure could not be parsed.")
            return 1

        print("running the GRIM check ...", file=sys.stderr)
        run([sys.executable, "grim_check.py", "--data", str(data_csv),
             "--out", str(grim_csv)])

        rows = list(csv.DictReader(grim_csv.open(encoding="utf-8")))
        report(rows, xml_files[0].stem)
        return 0

    finally:
        if args.keep:
            print(f"working files kept in {workdir}", file=sys.stderr)
        else:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
