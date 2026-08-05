# Findings

Investigated findings from the pipeline, recorded as they are resolved. Each entry
states what was found, how strongly it is corroborated, and what remains open.
Papers are cited by PMCID. Same convention as `LIMITATIONS.md`.

## Overview

**Corpus: 9,698 papers** (the first 9,999 PMIDs of the query, less publisher-blocked
records), yielding 45,724 extracted rows from 2,800 papers with usable baseline
tables. Of **509 checkable rows, 67 are flagged (13.2%)**, across 30 papers.

GRIMMER, added in v1.1, tests the standard deviation on the same principle.
It is checkable on 1,496 rows and flags 33 across 27 papers, none of which
overlap the GRIM flags. Two fall in PMC13296589, on rows that pass GRIM:
SPPB in the exercise arm (n = 12, mean 8.75, SD 1.55) and GAD-7 in the
COMBAT-ICU arm (n = 13, mean 3.77, SD 2.00). Both were confirmed by
enumerating every achievable sum of squares within the instrument's range,
and both remain unreachable under the population-SD convention as well.
Three more fall in PMC12815704, where GRIM finds nothing at all — see the
GRIMMER finding below.

Ten flags were investigated during the initial 947-paper corpus. Nine survive
unchanged in the full run; the BDI flag was later withdrawn as a rounding
artifact (see "Correction to the v1.0 results" below):

Charlson Comorbidity Index ×4 and APACHE II ×3 (both in PMC13296589, both
corroborated by an independent pooled-column check beyond GRIM alone — see
flagship entry), PHQ-9 ×1 (PMC13370186), Day 7 MADRS ×1 (PMC13389161 — see MADRS
entry), BDI ×1 (PMC13260263). The PHQ-9 flag is confirmed unreachable by GRIM 
and hand-verified arithmetically,
but has not been investigated further beyond
that. The BDI flag was withdrawn: the
mean is reachable under round-half-even
rounding.

**58 of the 67 flags are uninvestigated.** They are arithmetically confirmed
unreachable but nothing further is known about them. Papers with the most flags:
PMC13296589 (7), PMC12660629 (5), PMC12625294 (4), PMC12625497 (4). Do not treat
the uninvestigated flags as findings — the MADRS entry below shows how readily a
confirmed-unreachable mean dissolves under one plausible attrition scenario, and
`LIMITATIONS.md` lists flags that survive only because their measure type is still
misclassified.

Arithmetic for the two of the ten confirmed by hand but not examined further
(the BDI row has since been withdrawn):

| Flag | n | Mean | Nearest reachable values | Verdict |
| --- | --- | --- | --- | --- |
| PHQ-9, PMC13370186, Waitlist | 44 | 9.38 | 412/44 = 9.36, 413/44 = 9.39 | unreachable |
| BDI, PMC13260263, arm T | 8 | 9.2 | 74/8 = 9.25 | withdrawn — see correction |

The 13.2% rate rests on a denominator of 509 — 1.1% of all extracted rows. See
`LIMITATIONS.md` on GRIM's narrow reach.

## Flagship finding — PMC13296589, Table 3

The pooled 'All' column cannot be reconciled with the n-weighted average of the
three arms for Age, APACHE II, and the Charlson Comorbidity Index, while all
twelve outcome-measure rows in the same table reconcile to within rounding.
Exhaustive search over possible per-arm analysed sample sizes finds no plausible
missing-data pattern that resolves the CCI or APACHE II discrepancies. This is the
strongest finding in the dataset — corroborated by GRIM, the pooled-column check,
and elimination of the missing-data explanation.

Supporting detail:

| Variable | Pooled 'All' | n-weighted arms | Missingness that would be needed |
| --- | --- | --- | --- |
| Age | 65.12 | 66.024 | drop 8 of 11 controls |
| APACHE II | 18.61 | 18.506 | drop 7 of 12 from Exercise |
| Charlson CI | 2.21 | 2.177 | drop 11 of 13 from COMBAT-ICU |

Arm sizes are 13 / 12 / 11 (total 36), each stated explicitly in its own header
cell. GRIM independently flags all four CCI columns and three of four APACHE II
columns. Age is supported by the pooled-column check alone — GRIM does not apply,
since age may have been recorded continuously rather than in whole years. Age is
an eligibility criterion ("adults aged 18 years or older") and a pre-specified GEE
covariate, and the words "missing", "imputation" and "complete case" appear zero
times in the paper, which is what makes the required dropout implausible rather
than merely unreported. Length of stay (hospital and ICU) reconciles once
one-decimal rounding is accounted for and should **not** be cited as inconsistent.

*Artifacts:* `PMC13296589_table3_raw.xml` (complete source table).

## MADRS anomaly — PMC13389161

Resolved as a weaker, open finding, not a flagship result. Day 7 MADRS mean for
Midazolam arm (15.57, n=12) is mathematically unreachable at the stated n — but
fully explained if only 7 of 12 patients had a Day 7 assessment (109/7 = 15.5714,
matches exactly). The unusual SD (21.3) is NOT anomalous — it's consistent with a
normal bimodal responder/non-responder pattern, well within the statistically
possible range for that mean. Resolving this needs the paper's actual Day 7
analysis population (a CONSORT flow-diagram question), which this pipeline can't
determine from the table alone.

Supporting detail: at n=12 the nearest attainable means are 186/12 = 15.50 and
187/12 = 15.58. Sweeping every n from 2 to 12, **n=7 is the only value at which
15.57 is reachable**. The other three MADRS cells in the same table (Ketamine Day
7 at 15.94/n=18, and both baseline values) are independently reachable, isolating
the discrepancy to this one cell. On the SD: maximum attainable SD for a 0–60
scale at mean 15.57 is 26.30 (population) or 27.47 (sample, n−1), so 21.3 sits at
77.5% of the maximum; an integer sample such as [60, 60, 6×10] yields mean 15.00,
SD 21.02.

## GRIMMER finding — PMC12815704, Table 1

All three MMSE arms report a standard deviation that no set of integer scores
can produce at the stated sample size, under the standard sample-SD convention.
GRIM passes every checkable row in this paper, so v1.0 would not have surfaced
it.

| Group | n | Reported | Nearest achievable |
|---|---|---|---|
| CG | 28 | 24.50 (2.00) | 1.99 and 2.01 |
| TCG | 28 | 25.00 (1.75) | 1.74 and 1.76 |
| TCOG | 29 | 25.00 (1.50) | 1.49 and 1.51 |

Each was confirmed by enumerating every achievable sum of squares for n integer
scores in the MMSE range 0–30 summing to the implied total: 1,781 for CG, 1,630
for TCG, 1,708 for TCOG. In each case the reported SD falls between two adjacent
achievable values rather than on one. Values verified against the published
Table 1.

The MMSE's 0–30 range is not load-bearing: the values remain unreachable when
the range constraint is dropped entirely. The SD convention is load-bearing for
one arm — TCG's 1.75 is reachable if the SD was computed with an n denominator
rather than n−1. CG and TCOG remain unreachable under either convention, and no
single convention accounts for all three.

Separately, every mean and SD in the row is a multiple of 0.25 (24.50, 25.00,
25.00; 2.00, 1.75, 1.50), which INSPECT-SR check 4.3 lists as a marker worth
noting. That observation is independent of GRIMMER.

## Correction to the v1.0 results

The v1.0 run reported 71 flagged rows of 516 checkable (13.8%) across 33 papers.
A subsequent audit found four of those flags to be artifacts of the rounding
convention used by the check, not reporting inconsistencies.

GRIM in v1.0 assessed reachability under round-half-up only. Where a journal
rounds using round-half-even (banker's rounding), a quotient ending in exactly 5
at the next decimal place rounds down rather than up, and the reported mean is in
fact reachable.

| PMCID | Variable | n | Reported mean | Reachable as |
|---|---|---|---|---|
| PMC12641942 | MMSE | 8 | 26.2 | 210/8 = 26.25 |
| PMC13103870 | Charlson comorbidity index | 40 | 3.72 | 149/40 = 3.725 |
| PMC13175143 | GAD-7 | 80 | 9.12 | 730/80 = 9.125 |
| PMC13260263 | BDI | 8 | 9.2 | 74/8 = 9.25 |

**Corrected v1.0 result: 67 flagged rows of 516 checkable (13.0%) across 30 papers.**

From v1.1 onward a mean is treated as unreachable only if it is unreachable under
both conventions. The original v1.0 output is retained unchanged in
`grim_results.csv`; the corrected run is in `grim_results_corrected.csv`. The
script that identified the artifacts is in `audit/`.
