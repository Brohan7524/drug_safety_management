"""
04_silver_clean.py

Takes the canonical-drug-enriched bronze data and produces a "Silver" table:
standardized field values, an explicit data quality flag per record, and
case reports deduplicated (FAERS is well known to contain duplicate
submissions of the same real-world event).

Cleaning rules
--------------
Age: FAERS reports patient age with a separate unit code (year/month/week/
day/hour/decade -- see drug_config.AGE_UNIT_TO_YEARS). We convert everything
to a single `patient_age_years` field so ages are comparable. Values outside
a physically plausible human range (0-120 years) are flagged, not discarded.

Weight: the FAERS spec defines patient weight as always being in kilograms
(there's no separate unit field), so there's no unit conversion to perform.
However real submissions sometimes contain physically implausible values --
e.g. "185" for an adult reads like pounds mistakenly entered where kg was
expected. We can't recover the true unit from the data, so rather than
silently "fixing" it we flag anything outside a plausible kg range for
review. This is the honest approach: guessing a conversion could easily make
a correct value wrong.

Sex / drug mapping / reactions / country: flagged when missing, using the
canonical mapping produced in step 03.

Deduplication (two passes, mirroring a real FAERS data quality issue):
1. Exact: the same case_report_id + canonical drug should appear once. If a
   case listed the same drug as suspect twice (e.g. two dose entries), keep
   one.
2. Near-duplicate: FAERS is known to contain the same real-world adverse
   event submitted multiple times under different case IDs (e.g. one report
   from the treating physician, a follow-up/amended report from the
   manufacturer). We approximate this with a heuristic composite key --
   same canonical drug + same reaction set + same age/sex + same received
   date -- and keep only the most recently received version of each group.

Output: data/processed/silver_adverse_events.csv, data/processed/dedup_stats.json
"""
import json
from pathlib import Path

import pandas as pd

from drug_config import AGE_UNIT_TO_YEARS, SEX_MAP

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"

PLAUSIBLE_AGE_YEARS = (0, 120)
PLAUSIBLE_WEIGHT_KG = (2, 250)  # ~4.4lb preemie to ~550lb, generous bounds


def standardize_age(row: pd.Series) -> float | None:
    raw_age = row["patient_age_raw"]
    unit_code = row["patient_age_unit_raw"]
    if pd.isna(raw_age) or pd.isna(unit_code):
        return None
    multiplier = AGE_UNIT_TO_YEARS.get(str(int(unit_code)))
    if multiplier is None:
        return None
    return round(float(raw_age) * multiplier, 2)


def build_quality_flags(row: pd.Series) -> str:
    flags = []
    if pd.isna(row["patient_age_years"]):
        flags.append("MISSING_AGE")
    elif not (PLAUSIBLE_AGE_YEARS[0] <= row["patient_age_years"] <= PLAUSIBLE_AGE_YEARS[1]):
        flags.append("INVALID_AGE")

    if pd.isna(row["patient_sex_std"]) or row["patient_sex_std"] == "Unknown":
        flags.append("MISSING_SEX")

    if pd.isna(row["patient_weight_raw"]):
        flags.append("MISSING_WEIGHT")
    elif not (PLAUSIBLE_WEIGHT_KG[0] <= row["patient_weight_raw"] <= PLAUSIBLE_WEIGHT_KG[1]):
        flags.append("IMPLAUSIBLE_WEIGHT")

    if pd.isna(row["reactions_raw"]) or not str(row["reactions_raw"]).strip():
        flags.append("MISSING_REACTIONS")

    if pd.isna(row["reporting_country_raw"]) or not str(row["reporting_country_raw"]).strip():
        flags.append("MISSING_COUNTRY")

    if pd.isna(row["canonical_id"]):
        flags.append("UNMAPPED_DRUG")

    if pd.isna(row["report_date_raw"]):
        flags.append("MISSING_REPORT_DATE")

    return ";".join(flags) if flags else "OK"


def dedup_exact(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    before = len(df)
    df = df.sort_values("receipt_date_raw").drop_duplicates(
        subset=["case_report_id", "canonical_id"], keep="last"
    )
    return df, before - len(df)


def dedup_near_duplicates(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Collapse likely repeat-submissions of the same real-world event.

    Heuristic composite key: same canonical drug, same reaction set (order-
    independent), same patient sex, same age-in-years, same received date.
    Independent case IDs sharing all of these are almost certainly the same
    underlying event reported more than once -- keep the most recently
    received (most likely to include follow-up corrections).
    """
    before = len(df)

    def normalize_reactions(s: str) -> str:
        if pd.isna(s):
            return ""
        return "|".join(sorted(x.strip().upper() for x in str(s).split(";") if x.strip()))

    df = df.copy()
    df["_dedup_key"] = (
        df["canonical_id"].astype(str) + "||"
        + df["reactions_raw"].apply(normalize_reactions) + "||"
        + df["patient_sex_std"].astype(str) + "||"
        + df["patient_age_years"].astype(str) + "||"
        + df["report_date_raw"].astype(str)
    )
    df = df.sort_values("receipt_date_raw").drop_duplicates(subset="_dedup_key", keep="last")
    df = df.drop(columns="_dedup_key")
    return df, before - len(df)


def main() -> None:
    bronze_path = OUT_DIR / "bronze_with_canonical.csv"
    if not bronze_path.exists():
        raise SystemExit(f"{bronze_path} not found. Run 03_drug_master_mapping.py first.")

    df = pd.read_csv(bronze_path, dtype={"case_report_id": str})
    n_bronze = len(df)

    # --- standardize fields ---
    df["patient_age_years"] = df.apply(standardize_age, axis=1)
    df["patient_sex_std"] = df["patient_sex_raw"].apply(
        lambda v: SEX_MAP.get(str(int(v)) if pd.notna(v) else None, "Unknown")
    )
    df["is_serious"] = df["serious_raw"] == 1

    # --- quality flags (computed before dedup so dedup logic can be audited) ---
    df["data_quality_flag"] = df.apply(build_quality_flags, axis=1)

    # --- dedup pass 1: exact case+drug duplicates ---
    df, n_exact_dupes = dedup_exact(df)

    # --- dedup pass 2: near-duplicate real-world events ---
    df, n_near_dupes = dedup_near_duplicates(df)

    n_silver = len(df)
    print(f"Bronze rows: {n_bronze}")
    print(f"  removed {n_exact_dupes} exact case+drug duplicates")
    print(f"  removed {n_near_dupes} near-duplicate (repeat-submission) records")
    print(f"Silver rows: {n_silver} ({(n_bronze - n_silver) / n_bronze:.1%} removed as duplicates)")
    print(df["data_quality_flag"].apply(lambda f: f.split(";")[0]).value_counts().to_string())

    out_path = OUT_DIR / "silver_adverse_events.csv"
    df.to_csv(out_path, index=False)
    print(f"Wrote {out_path}")

    stats = {
        "bronze_rows": n_bronze,
        "exact_duplicates_removed": n_exact_dupes,
        "near_duplicates_removed": n_near_dupes,
        "silver_rows": n_silver,
        "duplicate_rate": round((n_exact_dupes + n_near_dupes) / n_bronze, 4),
    }
    stats_path = OUT_DIR / "dedup_stats.json"
    stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(f"Wrote {stats_path}")


if __name__ == "__main__":
    main()
