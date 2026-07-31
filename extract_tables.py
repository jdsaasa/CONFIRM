"""Extract baseline-characteristics tables from PMC JATS XML into a flat CSV.

Selection is caption-driven only: a paper contributes data only if one of its
<table-wrap> captions matches a baseline/characteristics pattern. There is no
positional fallback -- "Table 1" is never assumed to be the baseline table.

A paper is skipped, rather than guessed at, when:
  * no caption matches                     -> "skipped - no baseline-captioned table found"
  * the table's grid is not rectangular    -> "skipped - irregular table structure"
    (multi-level headers, merged cells, ragged rows)
  * the table is rectangular but holds no mean/SD pairs (all categorical counts)

Output:
  extracted_data.csv  one row per variable-per-group
  skipped_papers.csv  every skipped PMCID with its reason

Usage:
    python extract_tables.py
    python extract_tables.py --indir raw_papers --out extracted_data.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

# Captions that identify a baseline table. Matches the survey that reported
# 677/947 papers, so the yield here is comparable to that figure.
BASELINE_RE = re.compile(
    r"baseline|demographic|patient characteristic|participant characteristic"
    r"|clinical characteristic|subject characteristic", re.I)

# Columns holding test statistics rather than an arm's data.
STAT_COL_RE = re.compile(
    r"^\s*(p|p[\s\-]?values?|t|f|z|df|chi[\s\-]?squared?|chi2|x2|χ2|χ²"
    r"|95%\s*ci|ci|statistics?|tests?|effect\s*sizes?|sig\.?)\s*$", re.I)

# Inline markup that carries no meaning once the cell is plain text.
UNWRAP_TAGS = {"italic", "bold", "sc", "underline", "monospace", "roman",
               "sans-serif", "strike", "styled-content", "named-content"}
# <xref> pointing at a table footnote is a marker, not content: drop it whole.
FOOTNOTE_REFS = {"table-fn", "fn", "bibr", "author-notes"}
FOOTNOTE_SYMBOLS = "*†‡§¶#"

# A <sup>/<sub> holding only a letter or symbol is a footnote marker. Digits are
# kept so real notation (cm2, 10 3) is not silently mangled.
FOOTNOTE_SUP_RE = re.compile(rf"^(?:[A-Za-z]{{1,2}}|[{re.escape(FOOTNOTE_SYMBOLS)}]+)$")

DASH = "−"  # unicode minus, common in typeset tables
PLUS_MINUS = r"(?:±|\+/-|\+/−)"
NUM = r"-?−?\d[\d,]*(?:\.\d+)?"

MEAN_SD_PATTERNS = (
    re.compile(rf"({NUM})\s*{PLUS_MINUS}\s*({NUM})"),               # 45.2 +- 8.1
    re.compile(rf"({NUM})\s*\(\s*(?:SD\s*[:=]?\s*)?({NUM})\s*\)", re.I),  # 45.2 (8.1)
)
N_RE = re.compile(r"\b[nN]\s*[=:]\s*(\d[\d,]*)")

# "39/88 (42.9)" is a count over its own denominator with a percentage -- never a
# mean/SD. Matched before MEAN_SD_PATTERNS, which would otherwise read "88 (42.9)".
FRACTION_RE = re.compile(rf"^\s*({NUM})\s*/\s*({NUM})\s*\(\s*({NUM})\s*\)")

# A label of the form "Female sex, % (n)" declares percent-then-count ordering,
# the reverse of mean-then-SD.
REVERSED_LABEL_RE = re.compile(
    r"%\s*\(\s*(?:n|no\.?|num(?:ber)?)\s*\)|percent(?:age)?\s*\(\s*(?:n|no\.?)\s*\)", re.I)

REASON_NO_CAPTION = "skipped - no baseline-captioned table found"
REASON_IRREGULAR = "skipped - irregular table structure"
REASON_NO_VALUES = "skipped - no mean/SD values found"
REASON_NO_GROUP_N = "skipped - cannot verify, no group n"

REASON_BORDERLINE = "borderline - precision-scaled match only"

# "X (Y)" is either mean (SD) or count (percent). When the group's sample size is
# known the two are separable by arithmetic: for a count, Y is X as a percentage
# of n. PERCENT_TOL is in percentage points and remains the auto-exclude window.
PERCENT_TOL = 0.15

# A percentage printed to fewer decimals carries more rounding error: "99" could
# be anything in [98.5, 99.5). Tolerance therefore scales with stated precision.
# The 0- and 2-decimal values are specified; 1 decimal keeps the original 0.15,
# which is where the great majority of published percentages sit.
PRECISION_TOL = {0: 0.5, 1: 0.15, 2: 0.05}
PRECISION_TOL_MIN = 0.05


def local(tag: str) -> str:
    """Strip any namespace from an element tag."""
    return tag.rpartition("}")[2]


def cell_text(el: ET.Element) -> str:
    """Flatten an element to plain text, dropping formatting and footnote markers."""
    parts: list[str] = []

    def walk(e: ET.Element) -> None:
        if e.text:
            parts.append(e.text)
        for child in e:
            tag = local(child.tag)
            if tag == "xref" and child.get("ref-type") in FOOTNOTE_REFS:
                pass                                    # marker: drop content
            elif tag in ("sup", "sub"):
                inner = "".join(child.itertext()).strip()
                if not FOOTNOTE_SUP_RE.match(inner):
                    parts.append(inner)                 # real notation: keep
            elif tag in ("fn", "table-wrap-foot"):
                pass                                    # footnote body, not cell data
            else:
                if tag == "break":
                    parts.append(" ")
                walk(child)                             # UNWRAP_TAGS land here
            if child.tail:
                parts.append(child.tail)

    walk(el)
    text = " ".join("".join(parts).split())
    text = text.strip(FOOTNOTE_SYMBOLS + " ")
    return " ".join(text.split())


def row_cells(tr: ET.Element) -> list[ET.Element]:
    return [c for c in tr if local(c.tag) in ("td", "th")]


def span_of(cell: ET.Element, attr: str) -> int:
    try:
        return int(cell.get(attr, "1"))
    except (TypeError, ValueError):
        return 1


def check_regular(table: ET.Element) -> str | None:
    """Return a reason string if the table grid cannot be read unambiguously."""
    theads = table.findall(".//{*}thead")
    if not theads:
        return "no <thead>; header row cannot be identified"

    head_rows = [tr for tr in theads[0].findall(".//{*}tr")]
    if len(head_rows) != 1:
        return f"multi-level header ({len(head_rows)} header rows)"

    width = len(row_cells(head_rows[0]))
    if width < 2:
        return f"only {width} column(s)"

    for cell in row_cells(head_rows[0]):
        if span_of(cell, "colspan") > 1 or span_of(cell, "rowspan") > 1:
            return "merged cells in header row"

    body_rows = [tr for tr in table.findall(".//{*}tr") if tr not in head_rows]
    for tr in body_rows:
        cells = row_cells(tr)
        if not cells:
            continue
        spans = [(span_of(c, "colspan"), span_of(c, "rowspan")) for c in cells]
        # A lone cell spanning the full width is a section divider ("Demographics").
        # It carries no per-group numbers, so it leaves the data grid unambiguous.
        if len(cells) == 1 and spans[0][0] >= width:
            continue
        if any(cs > 1 or rs > 1 for cs, rs in spans):
            return "merged cells spanning part of a data row"
        if len(cells) != width:
            return f"ragged rows ({len(cells)} cells vs {width} header columns)"

    if not body_rows:
        return "no data rows"
    return None


def parse_groups(header: ET.Element) -> list[tuple[int, str, str]]:
    """Return (column index, group name, sample size) for each arm column."""
    groups = []
    for idx, cell in enumerate(row_cells(header)):
        if idx == 0:
            continue                                   # variable-name column
        text = cell_text(cell)
        if not text or STAT_COL_RE.match(text):
            continue
        n_match = N_RE.search(text)
        n = n_match.group(1).replace(",", "") if n_match else ""
        name = N_RE.sub("", text)
        name = re.sub(r"\(\s*\)|\[\s*\]", "", name)
        name = name.strip(" ,;:()[]")
        groups.append((idx, " ".join(name.split()) or text, n))
    return groups


def parse_mean_sd(text: str) -> tuple[str, str, str] | None:
    """Pull a value pair out of a cell as (first, second, form).

    form is "pm" for the unambiguous `45.2 +- 8.1` shape, or "paren" for
    `45.2 (8.1)`, which could equally be a count with its percentage.
    """
    if not text or "%" in text:
        return None                                    # percentages are categorical
    for form, pattern in zip(("pm", "paren"), MEAN_SD_PATTERNS):
        m = pattern.search(text)
        if m:
            first = m.group(1).replace(",", "").replace(DASH, "-")
            second = m.group(2).replace(",", "").replace(DASH, "-")
            return first, second, form
    return None


def parse_fraction(text: str) -> tuple[str, str, str] | None:
    """Parse `a/b (c)` as (numerator, denominator, percent), or None."""
    m = FRACTION_RE.match(text or "")
    if not m:
        return None
    return tuple(g.replace(",", "").replace(DASH, "-") for g in m.groups())


def fraction_is_consistent(num: str, den: str, pct: str) -> bool | None:
    """Does numerator/denominator equal the stated percentage?"""
    try:
        a, b, c = float(num), float(den), float(pct)
    except ValueError:
        return None
    if b <= 0:
        return None
    return abs((a / b) * 100.0 - c) <= PERCENT_TOL


def is_count_percent(first: str, second: str, n: str) -> bool | None:
    """Is `first (second)` a count and its percentage of n?

    Returns True/False, or None when n is unknown so the test cannot run.
    """
    if not n:
        return None
    try:
        count, pct, total = float(first), float(second), float(n)
    except ValueError:
        return None
    if total <= 0:
        return None
    return abs((count / total) * 100.0 - pct) <= PERCENT_TOL


def stated_decimals(pct: str) -> int:
    """Decimal places the paper printed the percentage to."""
    return len(pct.partition(".")[2])


def classify_paren(first: str, second: str, n: str) -> tuple[str, float] | None:
    """Classify an `X (Y)` cell against the group's n.

    Returns (verdict, off_by_pp) where verdict is:
      "count"      matched inside the original +-0.15 window -> exclude
      "borderline" matched only once tolerance was widened for stated precision
      "mean"       no percentage match at any tolerance -> keep
    Returns None when n is unknown and the test cannot run.
    """
    try:
        count, pct, total = float(first), float(second), float(n)
    except ValueError:
        return None
    if total <= 0:
        return None

    off = abs((count / total) * 100.0 - pct)
    if off <= PERCENT_TOL:
        return "count", off
    scaled = PRECISION_TOL.get(stated_decimals(second), PRECISION_TOL_MIN)
    if off <= scaled:
        return "borderline", off
    return "mean", off


def find_baseline_table(art: ET.Element) -> tuple[ET.Element | None, str] | None:
    """First <table-wrap> whose caption matches the baseline pattern.

    Returns None when no caption matches, or (None, caption) when the caption
    matched but the table is a scanned image with no <table> element -- the two
    cases need different skip reasons.
    """
    for wrap in art.findall(".//{*}table-wrap"):
        label = wrap.find("{*}label")
        caption = wrap.find("{*}caption")
        text = " ".join(filter(None, [
            cell_text(label) if label is not None else "",
            cell_text(caption) if caption is not None else "",
        ]))
        if BASELINE_RE.search(text):
            return wrap.find(".//{*}table"), " ".join(text.split())
    return None


def extract(path: Path, stats: Counter | None = None,
            unverified: list[dict] | None = None,
            borderline: list[dict] | None = None) -> tuple[list[dict], str | None, str]:
    """Return (rows, skip_reason, detail) for one paper.

    `stats` accumulates per-cell classification counts; `unverified` collects
    ambiguous cells whose group has no sample size; `borderline` collects rows
    excluded because a precision-widened tolerance identified them as counts.
    """
    stats = stats if stats is not None else Counter()
    unverified = unverified if unverified is not None else []
    borderline = borderline if borderline is not None else []
    art = ET.parse(path).getroot().find(".//{*}article")
    if art is None:
        return [], REASON_IRREGULAR, "no <article> element"

    found = find_baseline_table(art)
    if found is None:
        return [], REASON_NO_CAPTION, ""
    table, caption = found
    if table is None:
        return [], REASON_IRREGULAR, "table is a scanned image (no <table> element)"

    reason = check_regular(table)
    if reason:
        return [], REASON_IRREGULAR, reason

    head_row = table.findall(".//{*}thead")[0].findall(".//{*}tr")[0]
    groups = parse_groups(head_row)
    if not groups:
        return [], REASON_IRREGULAR, "no arm columns after excluding statistics"

    body_rows = [tr for tr in table.findall(".//{*}tr") if tr is not head_row]
    width = len(row_cells(head_row))
    rows: list[dict] = []
    section = ""                       # nearest full-width divider above this row
    for tr in body_rows:
        cells = row_cells(tr)
        if not cells:
            continue

        # A lone full-width cell is a section divider. check_regular() has already
        # guaranteed every other row matches the header width, so a single-cell row
        # here can only be a divider. Its text names the rows beneath it, which is
        # often the only place the variable is written ("Age" above "Mean (SD)").
        if len(cells) == 1:
            section = cell_text(cells[0])
            continue

        variable = cell_text(cells[0])
        if not variable:
            continue
        if section:
            variable = f"{section} - {variable}"
        reversed_label = bool(REVERSED_LABEL_RE.search(variable))

        for idx, group, n in groups:
            if idx >= len(cells):
                continue
            text = cell_text(cells[idx])

            # "a/b (c)": a count over its own denominator, never a mean/SD.
            frac = parse_fraction(text)
            if frac is not None:
                consistent = fraction_is_consistent(*frac)
                stats["fraction_consistent" if consistent
                      else "fraction_inconsistent"] += 1
                continue

            parsed = parse_mean_sd(text)
            if parsed is None:
                continue
            mean, sd, form = parsed

            # Label declares "% (n)": the pair is percent-then-count, so the
            # count is the second value and the percentage the first.
            if form == "paren" and reversed_label:
                verdict = is_count_percent(sd, mean, n)
                stats["reversed_verified" if verdict
                      else "reversed_unverified"] += 1
                continue

            if form == "paren":
                result = classify_paren(mean, sd, n)
                if result is None:
                    stats["ambiguous_no_n"] += 1
                    unverified.append({
                        "pmcid": path.stem, "variable": variable, "group": group,
                        "cell": text, "reason": REASON_NO_GROUP_N,
                    })
                    continue
                verdict, off = result
                if verdict == "count":
                    stats["ambiguous_count_percent"] += 1
                    continue                           # categorical, not mean/SD
                if verdict == "borderline":
                    # Excluded as count(percent): a 30-row hand-check confirmed
                    # these are integer-rounded percentages, not means. Still
                    # logged so the decision stays auditable.
                    stats["ambiguous_borderline"] += 1
                    borderline.append({
                        "pmcid": path.stem, "variable": variable, "group": group,
                        "n": n, "cell": text,
                        "pct_of_n": f"{(float(mean) / float(n)) * 100:.2f}",
                        "stated": sd, "off_by_pp": f"{off:.2f}",
                        "stated_decimals": stated_decimals(sd),
                        "tolerance_used": PRECISION_TOL.get(stated_decimals(sd),
                                                            PRECISION_TOL_MIN),
                        "reason": REASON_BORDERLINE, "decision": "excluded",
                    })
                    continue
                stats["ambiguous_kept"] += 1
            else:
                stats["plus_minus"] += 1

            rows.append({
                "pmcid": path.stem,
                "variable": variable,
                "group": group,
                "n": n,
                "mean": mean,
                "sd": sd,
            })

    if not rows:
        return [], REASON_NO_VALUES, f"caption matched: {caption[:80]}"
    return rows, None, ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--indir", type=Path, default=Path("raw_papers"))
    parser.add_argument("--out", type=Path, default=Path("extracted_data.csv"))
    parser.add_argument("--skipped", type=Path, default=Path("skipped_papers.csv"))
    parser.add_argument("--unverified", type=Path,
                        default=Path("unverified_cells.csv"),
                        help="ambiguous cells whose group has no sample size")
    parser.add_argument("--borderline", type=Path,
                        default=Path("borderline_rows.csv"),
                        help="rows kept but matched only by the widened tolerance")
    args = parser.parse_args()

    files = sorted(args.indir.glob("*.xml"))
    if not files:
        print(f"No XML files in {args.indir.resolve()}", file=sys.stderr)
        return 1

    all_rows: list[dict] = []
    skipped: list[dict] = []
    unverified: list[dict] = []
    borderline: list[dict] = []
    stats: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    extracted_papers = 0

    for path in files:
        try:
            rows, reason, detail = extract(path, stats, unverified, borderline)
        except ET.ParseError as exc:
            rows, reason, detail = [], REASON_IRREGULAR, f"XML parse error: {exc}"

        if reason:
            skipped.append({"pmcid": path.stem, "reason": reason, "detail": detail})
            reasons[reason] += 1
        else:
            all_rows.extend(rows)
            extracted_papers += 1

    with args.out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["pmcid", "variable", "group",
                                                "n", "mean", "sd"])
        writer.writeheader()
        writer.writerows(all_rows)

    with args.skipped.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["pmcid", "reason", "detail"])
        writer.writeheader()
        writer.writerows(skipped)

    with args.unverified.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["pmcid", "variable", "group",
                                                "cell", "reason"])
        writer.writeheader()
        writer.writerows(unverified)

    with args.borderline.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["pmcid", "variable", "group", "n",
                                                "cell", "pct_of_n", "stated",
                                                "off_by_pp", "stated_decimals",
                                                "tolerance_used", "reason",
                                                "decision"])
        writer.writeheader()
        writer.writerows(borderline)

    print(f"papers scanned:          {len(files)}")
    print(f"papers with data:        {extracted_papers}")
    print(f"papers skipped:          {len(skipped)}")
    for reason, count in reasons.most_common():
        print(f"    {count:4d}  {reason}")

    ambiguous = (stats["ambiguous_kept"] + stats["ambiguous_count_percent"]
                 + stats["ambiguous_no_n"] + stats["ambiguous_borderline"])
    fractions = stats["fraction_consistent"] + stats["fraction_inconsistent"]
    reversed_cells = stats["reversed_verified"] + stats["reversed_unverified"]
    print(f"\nvalue cells classified:")
    print(f"    {stats['plus_minus']:5d}  '+-' form, kept (unambiguous)")
    print(f"    {fractions:5d}  'a/b (c)' fraction -> excluded "
          f"({stats['fraction_consistent']} percent-consistent, "
          f"{stats['fraction_inconsistent']} not)")
    print(f"    {reversed_cells:5d}  '% (n)' reversed label -> excluded "
          f"({stats['reversed_verified']} confirmed by n, "
          f"{stats['reversed_unverified']} not confirmable)")
    print(f"    {ambiguous:5d}  'X (Y)' ambiguous form, of which:")
    print(f"    {stats['ambiguous_count_percent']:5d}    count(percent) within +-{PERCENT_TOL} -> excluded")
    print(f"    {stats['ambiguous_borderline']:5d}    {REASON_BORDERLINE} -> excluded")
    print(f"    {stats['ambiguous_kept']:5d}    genuine mean/SD -> kept")
    print(f"    {stats['ambiguous_no_n']:5d}    {REASON_NO_GROUP_N}")

    print(f"\ndata rows written:       {len(all_rows)}  -> {args.out}")
    print(f"skip log:                {len(skipped)} rows -> {args.skipped}")
    print(f"unverifiable cells:      {len(unverified)} rows -> {args.unverified}")
    print(f"borderline (excluded):   {len(borderline)} rows -> {args.borderline}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
