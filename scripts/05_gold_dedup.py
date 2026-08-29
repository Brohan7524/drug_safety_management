"""
05_gold_dedup.py

Shapes the deduplicated Silver table into the "Gold" layer: one row per
unique adverse event case (case_report_id + canonical drug), with a final,
business-ready set of columns. This is the table Tableau (and the SQL
queries in 07) reads from.

Gold differs from Silver in scope, not content: Silver already did the
cleaning and deduplication; Gold just selects/renames the final analysis
columns and adds a couple of small derived fields (age bucket, report year)
that are convenient for dashboarding but don't belong in a cleaning step.

Output: data/processed/gold_adverse_events.csv, data/processed/gold.db (SQLite)
"""
import sqlite3
from pathlib import Path

import pandas as pd

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"

AGE_BUCKETS = [0, 2, 12, 18, 40, 65, 120]
AGE_BUCKET_LABELS = ["0-2 (Infant)", "2-12 (Child)", "12-18 (Teen)", "18-40 (Adult)", "40-65 (Middle Age)", "65+ (Senior)"]


def parse_fda_date(series: pd.Series) -> pd.Series:
    """FAERS dates are YYYYMMDD ints/strings; coerce invalid/missing to NaT."""
    return pd.to_datetime(series, format="%Y%m%d", errors="coerce")


def main() -> None:
    silver_path = OUT_DIR / "silver_adverse_events.csv"
    if not silver_path.exists():
        raise SystemExit(f"{silver_path} not found. Run 04_silver_clean.py first.")

    df = pd.read_csv(silver_path, dtype={"case_report_id": str})

    df["report_date"] = parse_fda_date(df["report_date_raw"])
    df["report_year"] = df["report_date"].dt.year
    df["age_group"] = pd.cut(
        df["patient_age_years"], bins=AGE_BUCKETS, labels=AGE_BUCKET_LABELS, right=True, include_lowest=True
    )

    gold = pd.DataFrame({
        "case_report_id": df["case_report_id"],
        "canonical_drug_id": df["canonical_id"],
        "canonical_brand": df["canonical_brand"],
        "canonical_generic": df["canonical_generic"],
        "drug_name_as_reported": df["drug_name_raw"],
        "reactions": df["reactions_raw"],
        "patient_age_years": df["patient_age_years"],
        "age_group": df["age_group"],
        "patient_sex": df["patient_sex_std"],
        "patient_weight_kg": df["patient_weight_raw"],
        "is_serious": df["is_serious"],
        "seriousness_death": df["seriousness_death"].fillna(0).astype(int),
        "seriousness_hospitalization": df["seriousness_hospitalization"].fillna(0).astype(int),
        "seriousness_lifethreatening": df["seriousness_lifethreatening"].fillna(0).astype(int),
        "reporting_country": df["reporting_country_raw"],
        "report_date": df["report_date"].dt.strftime("%Y-%m-%d"),
        "report_year": df["report_year"],
        "data_quality_flag": df["data_quality_flag"],
    })

    # Gold is analysis-ready: drop rows with no usable drug identity at all
    # (the ~2 UNMAPPED_DRUG cases) rather than let them dilute per-drug metrics.
    gold = gold[gold["canonical_drug_id"].notna()].reset_index(drop=True)

    out_csv = OUT_DIR / "gold_adverse_events.csv"
    gold.to_csv(out_csv, index=False)
    print(f"Gold rows: {len(gold)} unique cases across {gold['canonical_drug_id'].nunique()} drugs")
    print(f"Wrote {out_csv}")

    db_path = OUT_DIR / "gold.db"
    with sqlite3.connect(db_path) as conn:
        gold.to_sql("gold_adverse_events", conn, if_exists="replace", index=False)
    print(f"Wrote {db_path} (table: gold_adverse_events)")


if __name__ == "__main__":
    main()
