"""Fetch full-text XML for PubMed randomized controlled trials that are in PMC.

Pipeline:
    1. ESearch  (db=pubmed)  -> PMIDs for RCTs that have a PMC full-text record
    2. ELink    (pubmed->pmc) -> PMCID for each PMID
    3. EFetch   (db=pmc)      -> JATS XML, one file per article in raw_papers/

The NCBI API key is read from the NCBI_API_KEY environment variable. It is
never written to disk or logged; only its presence is reported.

Usage:
    python fetch_papers.py --retmax 200
    python fetch_papers.py --query 'randomized controlled trial[pt] AND asthma[mh]'
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

# Generated output goes here, never to the repo root, so a fresh run cannot
# overwrite the committed results of the published run.
RESULTS_DIR = Path("results")

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL_NAME = "rct-screener"

# NCBI allows 10 req/s with an API key and 3 req/s without. Stay under both.
RATE_WITH_KEY = 8.0
RATE_WITHOUT_KEY = 2.5

# PubMed's "pubmed pmc[sb]" subset = citations that have a full-text record in PMC.
DEFAULT_QUERY = 'randomized controlled trial[Publication Type] AND "pubmed pmc"[sb]'

ESEARCH_PAGE = 5000   # max PMIDs per ESearch call
ELINK_BATCH = 200     # PMIDs per ELink call

# PubMed refuses retstart > 9998, so one query can yield at most 9,999 PMIDs.
# Larger harvests need the query split into date windows (see --mindate/--maxdate).
PUBMED_RESULT_CAP = 9999

RESTRICTED_MARKER = "does not allow downloading of the full text"


class RateLimiter:
    """Blocks so that calls are spaced at least 1/rate seconds apart."""

    def __init__(self, per_second: float):
        self._interval = 1.0 / per_second
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next_at - now
            if delay > 0:
                time.sleep(delay)
                now = self._next_at
            self._next_at = now + self._interval


class EutilsClient:
    """Rate-limited, retrying client for the E-utilities endpoints."""

    def __init__(self, api_key: str | None, email: str | None, rate: float,
                 max_retries: int = 4, timeout: int = 60):
        self.api_key = api_key
        self.email = email
        self.limiter = RateLimiter(rate)
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = f"{TOOL_NAME} (python-requests)"

    def _common_params(self) -> list[tuple[str, str]]:
        params = [("tool", TOOL_NAME)]
        if self.email:
            params.append(("email", self.email))
        if self.api_key:
            params.append(("api_key", self.api_key))
        return params

    def get(self, endpoint: str, params: list[tuple[str, str]],
            post: bool = False) -> bytes:
        payload = params + self._common_params()
        url = f"{EUTILS}/{endpoint}"
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            self.limiter.wait()
            try:
                if post:
                    resp = self.session.post(url, data=payload, timeout=self.timeout)
                else:
                    resp = self.session.get(url, params=payload, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = exc
                resp = None
            else:
                if resp.status_code == 200:
                    return resp.content
                if resp.status_code not in (429, 500, 502, 503, 504):
                    resp.raise_for_status()
                last_error = requests.HTTPError(
                    f"{resp.status_code} from {endpoint}", response=resp
                )

            if attempt == self.max_retries:
                break
            backoff = 2.0 ** attempt
            if resp is not None:
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    backoff = max(backoff, float(retry_after))
            print(f"  ! {endpoint} failed ({last_error}); "
                  f"retrying in {backoff:.0f}s", file=sys.stderr)
            time.sleep(backoff)

        raise RuntimeError(f"{endpoint} failed after {self.max_retries} retries: "
                           f"{last_error}")


def search_pmids(client: EutilsClient, query: str, retmax: int,
                 mindate: str | None = None, maxdate: str | None = None) -> list[str]:
    """Return up to `retmax` PMIDs matching `query` (hard-capped at 9,999)."""
    pmids: list[str] = []
    retstart = 0

    while len(pmids) < retmax:
        page = min(ESEARCH_PAGE, retmax - len(pmids))
        params = [
            ("db", "pubmed"),
            ("term", query),
            ("retmax", str(page)),
            ("retstart", str(retstart)),
            ("retmode", "xml"),
        ]
        if mindate or maxdate:
            params += [("datetype", "pdat"),
                       ("mindate", mindate or "1800/01/01"),
                       ("maxdate", maxdate or "3000/01/01")]
        raw = client.get("esearch.fcgi", params)
        root = ET.fromstring(raw)
        error = root.findtext("ERROR") or root.findtext(".//ERROR")
        if error:
            raise RuntimeError(f"ESearch error: {error.strip()}")

        batch = [e.text for e in root.findall("./IdList/Id") if e.text]
        pmids.extend(batch)

        total = int(root.findtext("Count") or 0)
        if retstart == 0:
            print(f"PubMed reports {total} matching records; "
                  f"fetching up to {retmax}.")
            if total > PUBMED_RESULT_CAP:
                print(f"  note: only the first {PUBMED_RESULT_CAP:,} are reachable "
                      f"for one query; narrow it or use --mindate/--maxdate "
                      f"to cover the rest.")
        retstart += page
        if not batch or retstart >= total:
            break

    return pmids[:retmax]


def map_to_pmcids(client: EutilsClient, pmids: list[str]) -> dict[str, str]:
    """Map PMID -> PMCID via ELink. PMIDs with no PMC record are omitted.

    Note: ELink merges results when IDs are comma-separated, so each ID is
    passed as its own `id=` parameter to keep one LinkSet per input PMID.
    """
    mapping: dict[str, str] = {}

    for start in range(0, len(pmids), ELINK_BATCH):
        chunk = pmids[start:start + ELINK_BATCH]
        params = [("dbfrom", "pubmed"), ("db", "pmc"),
                  ("linkname", "pubmed_pmc"), ("retmode", "xml")]
        params += [("id", pmid) for pmid in chunk]
        raw = client.get("elink.fcgi", params, post=True)
        root = ET.fromstring(raw)

        for linkset in root.findall("./LinkSet"):
            pmid = linkset.findtext("./IdList/Id")
            if not pmid:
                continue
            for linksetdb in linkset.findall("./LinkSetDb"):
                if linksetdb.findtext("LinkName") != "pubmed_pmc":
                    continue
                target = linksetdb.findtext("./Link/Id")
                if target:
                    mapping[pmid] = f"PMC{target}"
                    break

        print(f"  linked {min(start + ELINK_BATCH, len(pmids))}/{len(pmids)} PMIDs "
              f"-> {len(mapping)} PMCIDs")

    return mapping


def fetch_article_xml(client: EutilsClient, pmcid: str) -> bytes:
    """Download one article's JATS XML. Raises if PMC returns no usable article."""
    numeric = pmcid.removeprefix("PMC")
    raw = client.get("efetch.fcgi", [
        ("db", "pmc"),
        ("id", numeric),
        ("retmode", "xml"),
    ])

    root = ET.fromstring(raw)
    if root.find(".//{*}article") is None:
        detail = (root.findtext(".//error") or root.findtext(".//Error")
                  or "no <article> element in response")
        raise ValueError(detail.strip())
    if RESTRICTED_MARKER in raw.decode("utf-8", "replace"):
        raise ValueError("publisher blocks XML full-text download")
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--query", default=DEFAULT_QUERY,
                        help="PubMed query (default: RCTs with PMC full text)")
    parser.add_argument("--retmax", type=int, default=100,
                        help="maximum number of articles to fetch (default: 100)")
    parser.add_argument("--outdir", type=Path, default=Path("raw_papers"),
                        help="output directory (default: raw_papers)")
    parser.add_argument("--overwrite", action="store_true",
                        help="re-download articles already present in outdir")
    parser.add_argument("--failed", type=Path,
                        default=RESULTS_DIR / "failed_papers.csv",
                        help="log of papers that could not be downloaded")
    parser.add_argument("--mindate", help="earliest publication date, e.g. 2024/01/01")
    parser.add_argument("--maxdate", help="latest publication date, e.g. 2024/12/31")
    args = parser.parse_args()

    if args.retmax < 1:
        parser.error("--retmax must be at least 1")
    if args.retmax > PUBMED_RESULT_CAP:
        parser.error(
            f"--retmax cannot exceed {PUBMED_RESULT_CAP}: PubMed rejects "
            f"retstart > 9998, so a single query can return at most "
            f"{PUBMED_RESULT_CAP:,} PMIDs. To harvest more, run the script once "
            f"per date window with --mindate/--maxdate.")

    api_key = os.environ.get("NCBI_API_KEY")
    email = os.environ.get("NCBI_EMAIL")
    if api_key:
        rate = RATE_WITH_KEY
        print(f"Using NCBI_API_KEY from environment ({rate:g} req/s).")
    else:
        rate = RATE_WITHOUT_KEY
        print("NCBI_API_KEY is not set; throttling to "
              f"{rate:g} req/s. Set it for faster runs.", file=sys.stderr)

    client = EutilsClient(api_key=api_key, email=email, rate=rate)
    args.outdir.mkdir(parents=True, exist_ok=True)

    print(f"\nQuery: {args.query}")
    pmids = search_pmids(client, args.query, args.retmax,
                         mindate=args.mindate, maxdate=args.maxdate)
    if not pmids:
        print("No records matched the query.")
        return 0
    print(f"Got {len(pmids)} PMIDs.\n")

    print("Converting PMIDs to PMCIDs...")
    pmid_to_pmcid = map_to_pmcids(client, pmids)
    unlinked = len(pmids) - len(pmid_to_pmcid)
    if unlinked:
        print(f"  {unlinked} PMIDs had no PMC record; skipping them.")
    print()

    saved = skipped = failed = 0
    failures: list[dict] = []
    total = len(pmid_to_pmcid)

    for i, (pmid, pmcid) in enumerate(pmid_to_pmcid.items(), start=1):
        if not re.fullmatch(r"PMC\d+", pmcid):      # guard against odd filenames
            print(f"[{i}/{total}] {pmcid}: unexpected PMCID format, skipping",
                  file=sys.stderr)
            failures.append({"pmcid": pmcid, "pmid": pmid,
                             "reason": "unexpected PMCID format"})
            failed += 1
            continue

        target = args.outdir / f"{pmcid}.xml"
        if target.exists() and not args.overwrite:
            skipped += 1
            continue

        try:
            xml = fetch_article_xml(client, pmcid)
        except (RuntimeError, ValueError, ET.ParseError, requests.HTTPError) as exc:
            print(f"[{i}/{total}] {pmcid} (PMID {pmid}): {exc}", file=sys.stderr)
            failures.append({"pmcid": pmcid, "pmid": pmid, "reason": str(exc)})
            failed += 1
            continue

        target.write_bytes(xml)
        saved += 1
        print(f"[{i}/{total}] saved {target} ({len(xml):,} bytes)")

    args.failed.parent.mkdir(parents=True, exist_ok=True)
    with args.failed.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["pmcid", "pmid", "reason"])
        writer.writeheader()
        writer.writerows(failures)

    print(f"\nDone. saved={saved} already-present={skipped} failed={failed} "
          f"-> {args.outdir.resolve()}")
    print(f"failure log: {len(failures)} rows -> {args.failed}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
