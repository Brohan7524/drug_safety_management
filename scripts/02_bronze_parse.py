"""
02_bronze_parse.py

Reads the cached raw openFDA JSON pages and flattens them into a single
"Bronze" table: one row per (case report, suspect drug entry). This is
intentionally close to the raw source -- minimal cleaning, so downstream
data quality problems (inconsistent drug names, unnormalized age units,
duplicate reports) are still visible and fixed explicitly in later steps.

Grain: one row per FAERS case report per PRIMARY SUSPECT drug entry that
matches one of the drugs we searched for. A single case can list several
concomitant medications (blood pressure pills, etc.) -- we only keep the
drug entry that was actually flagged as the suspected cause
(drugcharacterization == "1"), and only if its reported name plausibly
matches one of our target drugs (a cheap substring pre-filter; the real
standardization happens in 03_drug_master_mapping.py).

Output: data/processed/bronze_adverse_events.csv
"""
import json
from pathlib import Path

import pandas as pd

from drug_config import CANONICAL_DRUGS

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"

# Primary suspect drug only -- see FAERS data element definitions for drugcharacterization
SUSPECT_CODE = "1"

# Build a flat set of every seed term across all canonical drugs, used as a cheap
# relevance pre-filter so we don't drag in unrelated concomitant medications that
# happen to share a case with one of our target drugs.
ALL_SEED_TERMS = sorted(
    {alias.upper() for drug in CANONICAL_DRUGS for alias in drug["known_aliases"]}
    | {term.upper() for drug in CANONICAL_DRUGS for term in drug["search_terms"]}
)


def is_relevant(raw_name: str) -> bool:
    """Cheap pre-filter: does this raw drug name look like one of our target drugs?"""
    if not raw_name:
        return False
    upper = raw_name.upper()
    return any(seed in upper for seed in ALL_SEED_TERMS)


def extract_rows(report: dict, search_term: str) -> list[dict]:
    """Flatten one FAERS case report into 0+ bronze rows (one per matching suspect drug)."""
    rows = []
    patient = report.get("patient", {})
    reactions = [
        r.get("reactionmeddrapt", "").strip()
        for r in patient.get("reaction", [])
        if r.get("reactionmeddrapt")
    ]

    for drug in patient.get("drug", []):
        if drug.get("drugcharacterization") != SUSPECT_CODE:
            continue
        raw_name = (drug.get("medicinalproduct") or "").strip()
        if not is_relevant(raw_name):
            continue

        rows.append({
            "case_report_id": report.get("safetyreportid"),
            "matched_search_term": search_term,
            "drug_name_raw": raw_name,
            "active_substance_raw": (
                drug.get("activesubstance", {}).get("activesubstancename", "").strip()
            ),
            "reactions_raw": "; ".join(reactions),
            "patient_age_raw": patient.get("patientonsetage"),
            "patient_age_unit_raw": patient.get("patientonsetageunit"),
            "patient_sex_raw": patient.get("patientsex"),
            "patient_weight_raw": patient.get("patientweight"),
            "serious_raw": report.get("serious"),
            "seriousness_death": report.get("seriousnessdeath"),
            "seriousness_hospitalization": report.get("seriousnesshospitalization"),
            "seriousness_lifethreatening": report.get("seriousnesslifethreatening"),
            "seriousness_disabling": report.get("seriousnessdisabling"),
            "seriousness_congenital": report.get("seriousnesscongenitalanomali"),
            "seriousness_other": report.get("seriousnessother"),
            "report_date_raw": report.get("receivedate"),
            "receipt_date_raw": report.get("receiptdate"),
            "reporting_country_raw": report.get("occurcountry") or report.get("primarysourcecountry"),
            "report_version": report.get("safetyreportversion"),
            "is_duplicate_flag_raw": report.get("duplicate"),
        })
    return rows


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_files = sorted(RAW_DIR.glob("*.json"))
    if not raw_files:
        raise SystemExit(f"No cached raw files found in {RAW_DIR}. Run 01_fetch_data.py first.")

    all_rows = []
    for path in raw_files:
        search_term = path.stem.split("_skip")[0].replace("_", " ")
        data = json.loads(path.read_text(encoding="utf-8"))
        for report in data.get("results", []):
            all_rows.extend(extract_rows(report, search_term))

    df = pd.DataFrame(all_rows)
    print(f"Parsed {len(raw_files)} raw files -> {len(df)} bronze rows "
          f"({df['case_report_id'].nunique()} unique case IDs)")

    out_path = OUT_DIR / "bronze_adverse_events.csv"
    df.to_csv(out_path, index=False)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
