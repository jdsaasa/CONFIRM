# Findings

Investigated findings from the pipeline, recorded as they are resolved. Each entry
states what was found, how strongly it is corroborated, and what remains open.
Papers are cited by PMCID. Same convention as `LIMITATIONS.md`.

## Overview

**Corpus: 9,698 papers** (the first 9,999 PMIDs of the query, less publisher-blocked
records), yielding 45,724 extracted rows from 2,800 papers with usable baseline
tables. Of **516 checkable rows, 71 are flagged (13.8%)**, across 33 papers.

The ten flags below were investigated during the initial 947-paper corpus and all
survive unchanged in the full run:

Charlson Comorbidity Index ×4 and APACHE II ×3 (both in PMC13296589, both
corroborated by an independent pooled-column check beyond GRIM alone — see
flagship entry), PHQ-9 ×1 (PMC13370186), Day 7 MADRS ×1 (PMC13389161 — see MADRS
entry), BDI ×1 (PMC13260263). PHQ-9 and BDI flags are confirmed unreachable by
GRIM and hand-verified arithmetically, but have not been investigated further
beyond that.

**61 of the 71 flags are uninvestigated.** They are arithmetically confirmed
unreachable but nothing further is known about them. Papers with the most flags:
PMC13296589 (7), PMC12660629 (5), PMC12625294 (4), PMC12625497 (4). Do not treat
the uninvestigated flags as findings — the MADRS entry below shows how readily a
confirmed-unreachable mean dissolves under one plausible attrition scenario, and
`LIMITATIONS.md` lists flags that survive only because their measure type is still
misclassified.

Arithmetic for the two least-investigated of the ten (confirmed unreachable by
hand, but not examined beyond that):

| Flag | n | Mean | Nearest reachable values | Verdict |
| --- | --- | --- | --- | --- |
| PHQ-9, PMC13370186, Waitlist | 44 | 9.38 | 412/44 = 9.36, 413/44 = 9.39 | unreachable |
| BDI, PMC13260263, arm T | 8 | 9.2 | 73/8 = 9.1, 74/8 = 9.3 | unreachable |

The 13.8% rate rests on a denominator of 516 — 1.1% of all extracted rows. See
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
