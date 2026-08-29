# Drug Safety Master Data Management & Adverse Event Quality Dashboard

A portfolio project demonstrating master data management (MDM) and data
quality engineering on **real** pharmacovigilance data, built for a Data
Management internship application.

It pulls real adverse event reports from the FDA's public API, standardizes
inconsistent drug names into a master reference table, cleans and
deduplicates the records, and produces an analysis-ready table plus a data
quality scorecard — the same category of work a Data Management/MDM team
does with FAERS data in a biopharma company.

## What is openFDA / FAERS?

The [FDA Adverse Event Reporting System (FAERS)](https://www.fda.gov/drugs/surveillance/fda-adverse-event-reporting-system-faers)
is the FDA's database of adverse event and medication error reports
submitted by drug manufacturers, healthcare providers, and consumers. It's
the backbone of post-market drug safety surveillance in the US.
[openFDA](https://open.fda.gov/apis/drug/event/) is the FDA's public API
that exposes a de-identified version of FAERS. This project uses the
`/drug/event.json` endpoint — no API key is required for the volume this
project pulls.

**Important caveat, straight from the FDA's own disclaimer:** FAERS is a
passive spontaneous-reporting system. A report existing does **not** mean
the drug caused the event, reporting is voluntary and inconsistent, and the
same real-world event can be reported multiple times by different parties.
This is precisely what makes it a realistic dataset for practicing data
quality work.

## Real-world data quality problems this project addresses

1. **Drug name inconsistency.** Reports record the drug name exactly as
   typed by the submitter (`patient.drug.medicinalproduct`): `"HUMIRA"`,
   `"Humira Pen"`, `"ADALIMUMAB"`, `"HUMIRA (ADALIMUMAB)"`, `"Humira 40 mg/
   0.8 mL Pre-filled Syringe"` can all refer to the same drug. Six drugs in
   this project's scope produced **235 distinct raw name variants**.
   Aggregating "top reactions for Humira" without standardizing these first
   would silently split the counts and undercount every metric.
2. **Duplicate case reports.** FAERS is known to contain the same real-world
   adverse event reported more than once — e.g. a report from the treating
   physician and a follow-up/amended report from the manufacturer, each with
   a different case ID. In this dataset, deduplication removed **45.7%** of
   parsed rows (a good chunk of that is also an artifact of this project's
   own fetch strategy — see the Drug Master section below — but a real
   near-duplicate rate remains after accounting for that).
3. **Mixed/missing units and coded values.** Patient age is reported as a
   number **plus a separate unit code** (year, month, week, day, decade) —
   without converting to a common unit, "1" (day) and "1" (year) look
   identical. Sex and seriousness are stored as numeric codes that need a
   lookup table. A large fraction of records are simply missing age or
   weight entirely, since FAERS reporting fields are almost all optional.

## Project structure

```
scripts/
  drug_config.py            shared config: the 6 canonical drugs + alias lists
  01_fetch_data.py          pulls & caches raw openFDA JSON
  02_bronze_parse.py        flattens raw JSON -> Bronze table
  03_drug_master_mapping.py builds the Drug Master + standardizes drug names
  04_silver_clean.py        standardizes units, flags DQ issues, dedups -> Silver
  05_gold_dedup.py          shapes Silver -> Gold (analysis-ready) + SQLite db
  06_scorecard.py           computes the Data Quality Scorecard
  07_sql_queries.sql        5 analysis queries against the Gold layer
data/
  raw/                      cached raw JSON pages from openFDA (gitignored -- regenerate with 01_fetch_data.py)
  processed/                bronze/silver/gold CSVs, drug_master.csv, scorecard, gold.db
```

**Note on `data/raw/`:** it's excluded from version control (`.gitignore`) —
openFDA embeds a large `openfda` metadata block (every registered brand
name, application number, etc.) on *every* drug entry, which balloons the
cache to several hundred MB for generic drugs like ibuprofen with thousands
of registered brands. It's fully reproducible by re-running
`01_fetch_data.py` (a few minutes, no API key needed), so there's no reason
to commit it.

## How to run

```bash
pip install -r requirements.txt

python scripts/01_fetch_data.py          # pulls from openFDA, caches to data/raw/ (re-run is a no-op if cache exists)
python scripts/02_bronze_parse.py
python scripts/03_drug_master_mapping.py
python scripts/04_silver_clean.py
python scripts/05_gold_dedup.py
python scripts/06_scorecard.py

sqlite3 data/processed/gold.db < scripts/07_sql_queries.sql   # or open gold.db in any SQLite client
```

Each script reads the previous stage's output from `data/processed/` and is
independently re-runnable. `01_fetch_data.py` caches every API page to
`data/raw/` and skips any page already on disk, so re-running the whole
pipeline doesn't re-hit the API.

## Design decisions (for the interview)

**Why these 6 drugs?** Humira/Adalimumab, Lipitor/Atorvastatin,
Glucophage/Metformin, Prilosec/Omeprazole, Prozac/Fluoxetine, and
Advil+Motrin/Ibuprofen. Each is a well-known brand/generic pair, and
Advil+Motrin/Ibuprofen deliberately has **two** brand names for one generic
substance — that's the case that actually forces you to build a many-to-one
mapping instead of a simple find-and-replace.

**Why search on `medicinalproduct` instead of openFDA's own
`openfda.brand_name`/`openfda.generic_name` fields?** openFDA already
provides FDA-normalized name fields, but using them would defeat the point
of this project — there'd be nothing left to standardize. `medicinalproduct`
is the free-text field exactly as the original submitter typed it, which is
where the real-world messiness actually lives.

**Why filter to `drugcharacterization == "1"` (primary suspect) in Bronze?**
Each case report lists every drug the patient was taking, including
unrelated concomitant medications (e.g. a Humira case might also list
ibuprofen as a concomitant med the patient happened to be on). Keeping only
the drug flagged as the *suspected cause* keeps the dataset scoped to what
each case is actually reporting about, rather than pulling in every
medication mentioned anywhere in the report.

**Drug Master matching strategy (3 tiers, cheapest/most certain first):**
1. **Manual exact match** against an alias dictionary seeded with real
   variants observed in the data (`drug_config.py`).
2. **Fuzzy match** (`rapidfuzz`, `WRatio`, threshold 85) against the same
   alias pool, for variants like extra dosage text (`"IBUPROFEN 400 MG"`)
   or minor formatting differences not worth hand-coding individually.
3. **Unmatched** — left unmapped and flagged rather than force-matched. A
   real MDM pipeline would route these to a data steward review queue
   instead of guessing. Only 1 of 235 raw names (`"APO?IBUPROFEN"`, a
   Canadian generic with a corrupted character) fell through all three
   tiers in this run.

Result: **99.6%** of distinct raw drug names mapped to a canonical entity.

**Age standardization.** FAERS reports `patientonsetage` with a separate
`patientonsetageunit` code (800=decade, 801=year, 802=month, 803=week,
804=day, 805=hour — from the FAERS data element definitions). Every age is
converted to a single `patient_age_years` field so it's comparable across
records; anything outside 0–120 years post-conversion is flagged
`INVALID_AGE` rather than silently kept.

**Weight "standardization."** This one has a twist: the FAERS spec defines
`patientweight` as *always* being in kilograms — there's no separate unit
field to standardize from. So true unit conversion isn't something the data
actually needs. What real submissions do contain is physically implausible
values (e.g. a weight that reads like pounds mistakenly entered where kg was
expected). Since the true source unit can't be recovered from the data, this
project doesn't guess a conversion — it flags anything outside a plausible
2–250kg range as `IMPLAUSIBLE_WEIGHT` for review. Silently "fixing" a value
you can't verify is worse than leaving it flagged.

**Deduplication, two passes:**
1. *Exact* — the same case ID + canonical drug appearing more than once.
   In this dataset this is mostly an artifact of the fetch strategy itself
   (a case matching both the "HUMIRA" and "ADALIMUMAB" search terms gets
   pulled twice, once per search), not a FAERS data problem — but it has
   to be handled before analysis either way, and it's exactly the kind of
   pipeline-induced duplication a real ETL job has to guard against.
2. *Near-duplicate* — FAERS's actual known issue: the same real-world event
   reported more than once under different case IDs. Approximated with a
   composite key (canonical drug + reaction set + sex + age + received
   date) and resolved by keeping the most recently received version, on the
   theory that a later submission is more likely to include amendments.
   This is a heuristic, not a guarantee — a false match is possible if two
   different patients of the same age/sex genuinely had the same reaction
   to the same drug on the same day. In a production system this would be
   tuned against a labeled sample.

**Why drop `UNMAPPED_DRUG` rows from Gold but keep every other flagged
row?** An unmapped drug means we don't actually know what drug the case is
about — it can't be attributed to any canonical entity, so it's useless for
per-drug analysis. Missing age/weight/sex, by contrast, is still a valid,
attributable adverse event case; excluding it would bias the safety
analysis, not just the completeness metric. That's why it stays in Gold
with its flag intact rather than being dropped.

## The Gold table

`data/processed/gold_adverse_events.csv` — one row per unique adverse event
case (case ID + canonical drug), ready for Tableau:

| column | description |
|---|---|
| `case_report_id` | FAERS safety report ID |
| `canonical_drug_id`, `canonical_brand`, `canonical_generic` | standardized drug identity |
| `drug_name_as_reported` | original raw text, kept for traceability |
| `reactions` | `;`-joined MedDRA reaction terms |
| `patient_age_years`, `age_group` | standardized age + bucket |
| `patient_sex` | Male / Female / Unknown |
| `patient_weight_kg` | as reported (FAERS spec: always kg) |
| `is_serious`, `seriousness_death`, `seriousness_hospitalization`, `seriousness_lifethreatening` | seriousness flags |
| `reporting_country`, `report_date`, `report_year` | reporting metadata |
| `data_quality_flag` | `OK` or `;`-joined list of issues found |

`data_quality_scorecard.csv` sits alongside it with completeness %,
duplicate rates, drug-mapping success rate, and the quality-flag breakdown
— built for a Tableau summary tile, not for row-level detail.

## Limitations

- FAERS/openFDA is **not** a reliable source for computing true incidence
  or comparing drug safety head-to-head — reporting volume is driven by
  media attention, litigation, and manufacturer reporting obligations as
  much as by actual event frequency. This project treats it as a **data
  quality and MDM exercise**, not a clinical safety conclusion.
- The record cap in `01_fetch_data.py` (1,500 records per search term) is a
  deliberate scope choice to keep the pull fast and reproducible for a
  portfolio project, not a technical ceiling — openFDA has ~690K+ Humira
  reports alone.
- The near-duplicate heuristic in Silver is not validated against
  ground-truth labels; it's a defensible, explainable approximation of a
  problem FAERS documentation itself acknowledges exists.
