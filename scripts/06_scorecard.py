"""
06_scorecard.py

Computes a Data Quality Scorecard summarizing the whole pipeline: field
completeness, how much duplication was found and removed, how successfully
raw drug names were mapped to canonical entities, and the breakdown of
records by data quality flag. This is the artifact you'd hand to a
stakeholder (or show an interviewer) to answer "how good is this data?"
without them having to read the code.

Output: data/processed/data_quality_scorecard.csv
"""
import json
from pathlib import Path

import pandas as pd

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"

# Fields we report completeness for, and which table each lives in.
# Bronze is "as received"; Silver/Gold show the effect of cleaning.
COMPLETENESS_FIELDS = [
    "patient_age_raw", "patient_sex_raw", "patient_weight_raw",
    "reactions_raw", "reporting_country_raw", "report_date_raw",
]


def completeness_rows(df: pd.DataFrame, stage: str) -> list[dict]:
    rows = []
    for field in COMPLETENESS_FIELDS:
        non_null = df[field].notna() & (df[field].astype(str).str.strip() != "")
        rows.append({
            "metric_group": "field_completeness",
            "stage": stage,
            "metric": field,
            "value_pct": round(non_null.mean() * 100, 1),
            "value_n": int(non_null.sum()),
            "value_total": len(df),
        })
    return rows


def main() -> None:
    bronze = pd.read_csv(OUT_DIR / "bronze_adverse_events.csv", dtype={"case_report_id": str})
    silver = pd.read_csv(OUT_DIR / "silver_adverse_events.csv", dtype={"case_report_id": str})
    drug_master = pd.read_csv(OUT_DIR / "drug_master.csv")
    dedup_stats = json.loads((OUT_DIR / "dedup_stats.json").read_text(encoding="utf-8"))

    rows = []

    # --- 1. Field completeness, bronze (raw) vs silver (post-cleaning) ---
    rows += completeness_rows(bronze, "bronze")
    rows += completeness_rows(silver, "silver")

    # --- 2. Duplicate rate found and removed ---
    rows.append({
        "metric_group": "deduplication", "stage": "bronze_to_silver",
        "metric": "exact_case_drug_duplicates_removed",
        "value_pct": round(dedup_stats["exact_duplicates_removed"] / dedup_stats["bronze_rows"] * 100, 1),
        "value_n": dedup_stats["exact_duplicates_removed"], "value_total": dedup_stats["bronze_rows"],
    })
    rows.append({
        "metric_group": "deduplication", "stage": "bronze_to_silver",
        "metric": "near_duplicate_repeat_submissions_removed",
        "value_pct": round(dedup_stats["near_duplicates_removed"] / dedup_stats["bronze_rows"] * 100, 1),
        "value_n": dedup_stats["near_duplicates_removed"], "value_total": dedup_stats["bronze_rows"],
    })
    rows.append({
        "metric_group": "deduplication", "stage": "bronze_to_silver",
        "metric": "total_duplicate_rate",
        "value_pct": round(dedup_stats["duplicate_rate"] * 100, 1),
        "value_n": dedup_stats["bronze_rows"] - dedup_stats["silver_rows"], "value_total": dedup_stats["bronze_rows"],
    })

    # --- 3. Drug name -> canonical mapping success rate ---
    n_mapped = (drug_master["match_method"] != "unmatched").sum()
    n_total_names = len(drug_master)
    rows.append({
        "metric_group": "drug_name_mapping", "stage": "drug_master",
        "metric": "distinct_raw_names_mapped_to_canonical",
        "value_pct": round(n_mapped / n_total_names * 100, 1),
        "value_n": int(n_mapped), "value_total": n_total_names,
    })
    for method, count in drug_master["match_method"].value_counts().items():
        rows.append({
            "metric_group": "drug_name_mapping", "stage": "drug_master",
            "metric": f"match_method_{method}",
            "value_pct": round(count / n_total_names * 100, 1),
            "value_n": int(count), "value_total": n_total_names,
        })

    # --- 4. Records by data quality flag (silver, post-dedup) ---
    flag_counts = silver["data_quality_flag"].apply(lambda f: f.split(";")[0]).value_counts()
    for flag, count in flag_counts.items():
        rows.append({
            "metric_group": "quality_flags", "stage": "silver",
            "metric": flag,
            "value_pct": round(count / len(silver) * 100, 1),
            "value_n": int(count), "value_total": len(silver),
        })

    scorecard = pd.DataFrame(rows)
    out_path = OUT_DIR / "data_quality_scorecard.csv"
    scorecard.to_csv(out_path, index=False)

    print(scorecard.to_string(index=False))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
