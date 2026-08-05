"""Run CONFIRM's checks against a single trial and report in prose.

The bulk pipeline answers "which of these thousands of papers is worth a
look". This answers "what does the arithmetic say about this one paper",
which is the question a reviewer working through INSPECT-SR check 4.8 has.

Both tests are run. GRIM constrains the reported mean; GRIMMER applies the
same argument to the standard deviation and reaches rows GRIM cannot, since
the SD stays discrete at sample sizes where the mean does not.

It shells out to the existing stages rather than reimplementing them, so the
verified code path is the one that runs.

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
    while (Decimal(lo) / Decimal(n)).quantize(quant, rounding=ROUND_HALF_UP) > Decimal(mean):
        lo -= 1
    hi = lo + 1
    lo_v = (Decimal(lo) / Decimal(n)).quantize(quant, rounding=ROUND_HALF_UP)
    hi_v = (Decimal(hi) / Decimal(n)).quantize(quant, rounding=ROUND_HALF_EVEN)
    return str(lo_v), str(hi_v), lo, hi


def split(rows: list[dict]) -> tuple[list, list, list]:
    flagged = [r for r in rows if r["category"] == "checked-flagged"]
    passed = [r for r in rows if r["category"] == "checked-passed"]
    excluded = [r for r in rows if r["category"] == "not-applicable"]
    return flagged, passed, excluded


def exclusion_counts(excluded: list[dict]) -> list[tuple[str, int]]:
    reasons: dict[str, int] = {}
    for r in excluded:
        key = r["reason"].replace("not applicable - ", "")
        reasons[key] = reasons.get(key, 0) + 1
    return sorted(reasons.items(), key=lambda kv: -kv[1])


def report(grim_rows: list[dict], grimmer_rows: list[dict],
           identifier: str) -> None:
    g_flag, g_pass, g_excl = split(grim_rows)
    m_flag, m_pass, m_excl = split(grimmer_rows)
    g_check = len(g_flag) + len(g_pass)
    m_check = len(m_flag) + len(m_pass)
    total = len(grim_rows)

    print()
    print("CONFIRM - single-trial check")
    print("=" * 62)
    print(f"Paper:  {identifier}")
    print(f"Rows extracted from the baseline table:  {total}")
    print()

    # ---- GRIM -------------------------------------------------------------
    print("GRIM - reported means (INSPECT-SR check 4.8)")
    print("-" * 62)
    if g_check == 0:
        print("No rows were checkable, so GRIM was not applied to this paper.")
        print("That is not a clean result: it means the test could not run.")
    elif not g_flag:
        print(f"No inconsistencies found. {g_check} of {total} rows were checkable;")
        print(f"all {g_check} report a mean reachable at the stated sample size.")
    else:
        print(f"{len(g_flag)} of {g_check} checkable rows report a mean that is not")
        print("reachable at the stated sample size:")
        print()
        for r in g_flag:
            n = int(r["n"])
            lo_v, hi_v, lo_t, hi_t = neighbours(r["mean"], n)
            print(f"  {r['variable']}")
            print(f"    group {clean_label(r['group'])!r}, n = {n}")
            print(f"    reported {r['mean']}; achievable "
                  f"{lo_t}/{n} = {lo_v} and {hi_t}/{n} = {hi_v}")
            print()

    # ---- GRIMMER ----------------------------------------------------------
    print("GRIMMER - reported standard deviations (INSPECT-SR check 4.8)")
    print("-" * 62)
    if m_check == 0:
        print("No rows were checkable, so GRIMMER was not applied to this paper.")
        print("That is not a clean result: it means the test could not run.")
    elif not m_flag:
        print(f"No inconsistencies found. {m_check} of {total} rows were checkable;")
        print(f"all {m_check} report an SD reachable at the stated sample size.")
    else:
        print(f"{len(m_flag)} of {m_check} checkable rows report a standard deviation")
        print("that no set of integers can produce at the stated sample size:")
        print()
        for r in m_flag:
            print(f"  {r['variable']}")
            print(f"    group {clean_label(r['group'])!r}, n = {r['n']}")
            print(f"    reported mean {r['mean']}, SD {r['sd']}")
            print()

    # ---- coverage ---------------------------------------------------------
    print("Coverage")
    print("-" * 62)
    print(f"{total} rows extracted from the table.")
    print()
    print(f"  GRIM:     {g_check:4} checkable, {len(g_excl):4} excluded")
    for reason, count in exclusion_counts(g_excl):
        print(f"              {count:4}  {reason}")
    print()
    print(f"  GRIMMER:  {m_check:4} checkable, {len(m_excl):4} excluded")
    for reason, count in exclusion_counts(m_excl):
        print(f"              {count:4}  {reason}")
    print()
    print("Both tests apply only to measures that can take integer values.")
    print("GRIM additionally needs a sample small enough for the reachable")
    print("means to be spaced further apart than the reported precision;")
    print("GRIMMER has no such ceiling, so it reaches rows GRIM cannot.")
    print("Rows whose mean already fails GRIM are excluded from GRIMMER")
    print("rather than reported twice.")
    print()
    print("Excluded rows have not been tested and no conclusion should be")
    print("drawn about them. A flag means the reported value is not reachable")
    print("from integer data at the stated n; it does not by itself indicate")
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
    grimmer_csv = workdir / "grimmer.csv"

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

        print("running GRIM ...", file=sys.stderr)
        run([sys.executable, "grim_check.py", "--data", str(data_csv),
             "--out", str(grim_csv)])

        print("running GRIMMER ...", file=sys.stderr)
        run([sys.executable, "grimmer_check.py", "--data", str(data_csv),
             "--out", str(grimmer_csv)])

        grim_rows = list(csv.DictReader(grim_csv.open(encoding="utf-8")))
        grimmer_rows = list(csv.DictReader(grimmer_csv.open(encoding="utf-8")))
        report(grim_rows, grimmer_rows, xml_files[0].stem)
        return 0

    finally:
        if args.keep:
            print(f"working files kept in {workdir}", file=sys.stderr)
        else:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
