# CONFIRM

[![DOI](https://zenodo.org/badge/1318297081.svg)](https://doi.org/10.5281/zenodo.21740555)

Baseline-table extraction and arithmetic verification for randomized controlled
trials with full text in PubMed Central.

The pipeline runs in three independent stages. Each writes CSV files that the next
stage reads, so stages can be re-run separately.

**Where output goes.** Every script writes to `results/`, which is gitignored. The
CSVs at the repo root (`extracted_data.csv`, `grim_results.csv`,
`failed_papers.csv`, `unverified_cells.csv`) are the committed record of the
published 9,698-paper run and are never written to. Running the pipeline cannot
overwrite them. `grim_results_corrected.csv` is the corrected re-run of the same data and is also never written to — see "Correction to the v1.0 results" in `FINDINGS.md`.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### NCBI API key

`fetch_papers.py` reads an NCBI API key from the `NCBI_API_KEY` environment
variable. It is never read from a file and never hardcoded.

```powershell
$env:NCBI_API_KEY = "your-key-here"
```

Without a key the script still runs but throttles itself to 2.5 requests/second
instead of 8, roughly three times slower. Keys are free from
<https://account.ncbi.nlm.nih.gov/settings/>.

## Running the pipeline

### 1. Fetch — `fetch_papers.py`

ESearch → ELink → EFetch. Downloads JATS XML into `raw_papers/`, one file per
PMCID. Rate-limited, retries on transient failures, and resumable: re-running
skips files already on disk without issuing a request.

```powershell
python fetch_papers.py --retmax 1000
python fetch_papers.py --retmax 9999 --mindate 2024/01/01 --maxdate 2024/12/31
```

PubMed serves at most 9,999 records per query, so larger harvests need
`--mindate`/`--maxdate` to slice the query into date windows. Papers whose
publisher blocks XML download are skipped and logged to
`results/failed_papers.csv` with their PMCID, PMID, and reason.

### 2. Extract — `extract_tables.py`

Finds each paper's baseline table by caption match, then writes one row per
variable-per-group. Tables with multi-level headers, merged cells spanning part
of a data row, or ragged rows are rejected rather than guessed at.

```powershell
python extract_tables.py
```

| Output | Contents |
| --- | --- |
| `results/extracted_data.csv` | `pmcid, variable, group, n, mean, sd` |
| `results/skipped_papers.csv` | every skipped paper with its reason |
| `results/unverified_cells.csv` | ambiguous cells whose group has no sample size |
| `results/borderline_rows.csv` | cells excluded as counts only by a precision-widened tolerance |

`X (Y)` cells are ambiguous between mean (SD) and count (percent). Where the
group's *n* is known, the two are separated arithmetically: if `(X ÷ n) × 100`
matches Y, the cell is a count and is excluded. Where *n* is unknown the cell is
logged, not guessed.

### 3. Verify — `grim_check.py`

Applies the GRIM test: for a measure that takes only integer values, the mean of
n observations must be one of n+1 discrete values, so an unreachable mean
indicates a reporting error.

```powershell
python grim_check.py
```

Writes `results/grim_results.csv` — every extracted row annotated with
`measure_type`, `category` (`checked-flagged`, `checked-passed`,
`not-applicable`), `reason`, `granularity`, and `nearest_achievable`.

A row is only tested when its measure is known to be integer-valued, its sample
size is known, and `n < 10^decimals` so the test has discriminating power.
Everything else is excluded with a recorded reason.

**Expect a small checkable fraction — this is by design, not a malfunction.** In
the published run only **1.1% of extracted rows were checkable** (516 of 45,724).
Baseline tables are dominated by continuous measures — age, BMI, height, weight,
lab values — and GRIM cannot evaluate any of them, because a continuous mean is
always arithmetically reachable. The test only applies to integer-valued measures:
psychometric instruments and severity scores.

A consequence worth knowing before your first run: **a small test run will
typically report zero or near-zero checkable rows**, and `flagged: n/a - nothing
was checkable` is the correct output for a handful of papers, not an error. Expect
to need a few hundred papers before GRIM has anything to say, and a few thousand
before the flag rate is stable.

## Results

- **`FINDINGS.md`** — investigated findings, graded by how strongly each is
  corroborated, with the counter-scenario that would dissolve it where one exists.
- **`LIMITATIONS.md`** — known limitations, each with the papers it affects and
  what would be needed to remove it.

Read both before using `extracted_data.csv` for anything. Flags are starting
points for inspection, not conclusions.

## Licence and citation

MIT licensed — see `LICENSE`. Citation metadata is in `CITATION.cff`.
