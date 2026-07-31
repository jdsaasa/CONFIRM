# Known Limitations

Running log of real, identified limitations in this pipeline. Each entry records
what the limitation is, why it is currently tolerable (if it is), and what would
need to change to remove it. Papers are cited by PMCID where applicable.

- **Section-prefix inheritance can misclassify rows via an unrelated prefix.**
  RESOLVED for classification, but the history matters. On the 947-paper corpus
  the risk was recorded as inert: 313 rows fell back to a prefix, but none were
  testable. Scaling to 9,698 papers made it live — 2,863 rows now fall back, 31
  of them reached the checkable set, and **5 produced false flags**: PMC13069986,
  where the divider `Type of diabetes medication` (matching the generic count word
  "medications") was inherited onto `QUICKI` (~0.32) and `EQ-5D scale score`
  (~0.54), both continuous. Fixed by making the fallback able to EXCLUDE a row
  but never ADMIT one: it may return "continuous", never "integer". Verified after
  the fix: 0 of 516 checkable rows derive their verdict from prefix text.
  Residual cost: genuine integer subscales such as PMC12538054's
  `SPPB, mean (SD) - Walk (0−4)` are now excluded as "unknown" rather than tested,
  which is the conservative direction.
  *Earlier examples of the same pattern:* PMC13390134 (`ASA, n(%) - BMI`),
  PMC13373745 (`Modified APACHE II score - Mean body mass index, kg/m2`).
  *Code:* `classify_measure()` in `grim_check.py`; prefix construction in
  `extract()` in `extract_tables.py`.
  *Lesson:* a limitation recorded as "inert because nothing testable reaches it"
  is a prediction about corpus scale, not a property of the code. Re-check such
  entries whenever the corpus grows.

- **Publisher-blocked papers return metadata only.** 53 of 1,000 PMC records
  return front matter only, no `<body>`; `open access[filter]` excludes them but
  `free full text[filter]` does not. Verified by re-fetching all 53: every one
  returned 0 body characters and 0 sections, so none were wrongly discarded. The
  refusal appears as an XML comment, not an error, so the response is HTTP 200 and
  well-formed. Retrying never helps.
  *Examples:* all 53 listed in `failed_papers.csv`; PMC13402339 is in the Wiley
  Open Access Collection yet still blocked, so PMC collection membership is not a
  reliable predictor.
  *Code:* `RESTRICTED_MARKER` / `fetch_article_xml()` in `fetch_papers.py`.

- **PubMed's 9,999-record ceiling caps any single harvest.** A single ESearch
  query cannot page past `retstart=9998`; larger harvests need date-window
  slicing. The query used here matches ~171,784 records, so no single run can
  reach more than 6% of them. The script fails fast with an explanation rather
  than dying mid-run, and `--mindate`/`--maxdate` exist to slice the query, but
  nothing automates the slicing.
  *Code:* `PUBMED_RESULT_CAP` and the `--retmax` guard in `fetch_papers.py`.

- **14,233 cells have no group *n*, so the count/percent test cannot run.** They
  are excluded unadjudicated rather than guessed either way, which is the
  conservative choice but leaves the single largest block of undecided data in the
  pipeline. Recovering these sample sizes — many sit in headers the parser did not
  associate with their column — would both enlarge the dataset and make the
  residual prefix-fallback risk above live.
  *Artifacts:* `unverified_cells.csv`.
  *Code:* `REASON_NO_GROUP_N` in `extract_tables.py`.

- **Counts computed against a different denominator survive as means.** e.g.
  `Female, No. (%) 45 (61.64) n=78`, where the paper's percentage uses a
  denominator other than the column header n (45/78 = 57.69%, not 61.64%). The
  arithmetic test compares against the header n, so these fail to match and are
  kept as mean/SD. Off-by magnitude separates them in practice — near misses are
  rounded counts, large misses are genuine continuous variables — but no rule
  currently acts on that.
  *Examples:* PMC13246076 (`Female, No. (%)`); PMC13279985 (`No`, cell `13 (87)`
  with header n=13 but a true denominator of 15).
  *Code:* `is_count_percent()` / `classify_paren()` in `extract_tables.py`.

- **`pmcid + variable + group` is not a unique key: 2,072 rows (4.5%) across 132
  papers.** Section-prefix inheritance reduces this substantially, but papers whose
  tables have no divider rows at all are unreachable by that fix, so variable
  identity is
  genuinely lost — those tables disambiguate by indentation or by putting the
  variable in the column headers instead. Values, group assignment, and n remain
  correct; only the label is ambiguous. Any join or dedup on this key will
  silently collapse distinct measurements.
  *Examples:* PMC13305237 (72 rows; arms in column 0, timepoints as columns),
  PMC13259180 (16 rows; same variable at two timepoints), PMC13355162 (16 rows).
  *Code:* divider handling in `extract()` in `extract_tables.py`.

- **GRIM reaches only 516 of 45,724 rows (1.1%).** The 13.8% flag rate rests on
  that denominator. Baseline tables
  are dominated by continuous measures (age, BMI, height, weight, labs) that GRIM
  cannot evaluate by construction; the test only bites on integer instruments and
  severity scores. Excluded: 23,326 continuous, 15,075 measure type unknown, 5,663
  no sample size, 1,120 no discriminating power (n ≥ 10^decimals), 13 likely
  subscale or per-item averages, 11 means outside their instrument's valid range.
  Coverage grows only by naming more instruments with certainty, not by loosening
  the classifier.
  *Examples:* the 71 flags span 33 papers; PMC13296589 (7) and PMC12660629 (5) are
  the largest contributors, so the rate is not driven by any single table.
  *Code:* `NAMED_SCORE_RE` and the not-applicable branches in `grim_check.py`.

- **Some flagged measures are still misclassified as integer counts.**
  Ultrafiltration (L), Steps, and Cigarettes/day remain flagged despite likely
  being continuous or period-averaged measures rather than single-observation
  integer counts. Ultrafiltration is a fluid volume in litres — continuous, and
  GRIM cannot apply to it at all. Steps and cigarettes per day are integer for a
  single observation, but baseline tables normally report them averaged over a
  period (steps/day over a week, cigarettes/day over a month), which makes each
  patient's value non-integer and again puts them outside GRIM's assumptions.
  These reach the checkable set through the generic count tier (`counts?`,
  `cigarettes?`, `steps?`) and account for 7 of the 71 current flags (3 + 2 + 2),
  which should therefore be treated as unverified rather than as findings. The
  generic tier admits 14 flags in total; the other 7 — number of hospitalizations,
  Modified Falls Efficacy Scale, UPDRS limb items, training sessions attended —
  are genuine per-observation integer counts and are not in doubt.
  *Examples:* PMC12508196 (`Ultrafiltration of the studied hemodialysis session,
  L`, 3 flags), PMC12677381 (`Steps, mean (SD)`, 2 flags), PMC12885348
  (`Cigarettes per day, n`, 2 flags).
  *Code:* generic tier `INTEGER_RE` in `grim_check.py`. Fixing this means either
  removing those terms from the generic tier or requiring a per-observation
  qualifier — both trade coverage for correctness.

- **The subscale exclusion rule applies to flagged and passed rows alike, by
  design.** When a named instrument's mean falls below its subscale threshold, the
  row is excluded regardless of whether GRIM would have flagged or passed it. This
  is deliberate: a rule that suppressed only flags would be outcome-dependent,
  systematically lowering the flag rate while leaving equally-suspect passing rows
  in the denominator, which would bias the headline figure downward. Of the 12
  rows the rule removed from the checkable set, 6 had been flagged and 6 had
  passed.
  *Illustrative example:* PMC13267419 reported PSQI and ESS means of 1.21–1.93,
  and the rule excluded 8 of its rows: 6 were unreachable, 1 — an ESS value of
  1.93 at n=15 — happened to be reachable and had passed, and 1 was already
  excluded for insufficient precision. If the column is per-item averages, the
  reachable row was reachable by coincidence, not correctness, so excluding it
  with its siblings is the consistent treatment.
  *Note:* the 6 previously-passing rows are 5 in other papers (PMC12607157, four
  arms, means 2.94–3.50; PMC12578800, mean 3.82) plus the PMC13267419 ESS row
  above, so the rule removes correct-looking data as well as bad. That is the
  accepted cost of applying it symmetrically. Across the corpus the rule excluded
  13 rows: 6 flagged, 6 passed, 1 already excluded.
  *Code:* `INSTRUMENT_SPECS` / `range_verdict()` in `grim_check.py`.

- **Duration measurement granularity remains unresolved for two papers.** Duration
  measurement granularity for PMC13250868 (ICU stay) and PMC13318024 (disease
  duration) remains unresolved — supplementary materials that might document this
  exist but require a separate fetch mechanism and file parsers (docx/PDF) outside
  the current pipeline's scope. Treated as an open question for future work, not
  investigated further in v1. Neither paper's body text states whether these were
  recorded in whole or fractional days; both variables are consequently classified
  "unknown" and excluded from the GRIM denominator, so no result currently depends
  on the answer.
  *Examples:* PMC13250868 (`Appendix.docx`, `IANN_A_2685913_SM4813.docx`, no
  descriptive caption); PMC13318024 (`S2 Data — Study protocol`,
  `pone.0352321.s002.pdf`, the more promising of the two).
  *Code:* generic count tier in `INTEGER_RE` in `grim_check.py`, which
  deliberately omits bare "days".
