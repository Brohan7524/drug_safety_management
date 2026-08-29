"""
03_drug_master_mapping.py

Builds a "Drug Master" reference table that maps every distinct raw,
as-reported drug name (from the Bronze table) to one canonical drug entity
(brand + generic name), and applies that mapping to produce a standardized
dataset.

Why this step exists: FAERS/openFDA data reports drug names exactly as the
submitter typed them -- "HUMIRA", "Humira Pen", "ADALIMUMAB", "Humira
(adalimumab)", etc. all refer to the same real-world drug. Without
standardizing these, aggregate analysis (e.g. "top reactions for Humira")
silently undercounts because rows are split across name variants.

Matching strategy (three tiers, cheapest/most-certain first):
1. Exact match against a manual alias dictionary seeded from
   drug_config.CANONICAL_DRUGS[*]["known_aliases"] -- these are real
   variants observed in the data, mapped by hand with full confidence.
2. Fuzzy match (rapidfuzz) against the same alias pool for anything not
   caught by the exact dictionary -- catches near-variants like extra
   whitespace, punctuation, or minor misspellings/formatting differences.
   Accepted only above SCORE_THRESHOLD; below that we don't guess.
3. Unmatched -- left as-is and flagged, rather than force-mapped. In a
   real MDM job these would go to a human steward review queue.

Output:
  data/processed/drug_master.csv          (raw_name -> canonical mapping + method/score)
  data/processed/bronze_with_canonical.csv (bronze rows + canonical drug columns)
"""
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process

from drug_config import CANONICAL_DRUGS

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
SCORE_THRESHOLD = 85  # rapidfuzz score (0-100) below which we refuse to auto-map

# ---------------------------------------------------------------------------
# Build the manual alias dictionary and the fuzzy-match candidate pool from
# drug_config.py, so there is exactly one place (drug_config.py) that defines
# what "Humira" means.
# ---------------------------------------------------------------------------
MANUAL_ALIAS_MAP: dict[str, dict] = {}
FUZZY_CANDIDATES: dict[str, str] = {}  # alias text -> canonical_id

for drug in CANONICAL_DRUGS:
    canonical_info = {
        "canonical_id": drug["canonical_id"],
        "canonical_brand": drug["canonical_brand"],
        "canonical_generic": drug["canonical_generic"],
    }
    for alias in drug["known_aliases"] + [drug["canonical_brand"], drug["canonical_generic"]]:
        key = alias.strip().upper()
        MANUAL_ALIAS_MAP[key] = canonical_info
        FUZZY_CANDIDATES[key] = drug["canonical_id"]

CANONICAL_LOOKUP = {d["canonical_id"]: d for d in CANONICAL_DRUGS}


def match_name(raw_name: str) -> dict:
    """Return {canonical_id, canonical_brand, canonical_generic, match_method, match_score} for one raw name."""
    cleaned = (raw_name or "").strip().upper()
    if not cleaned:
        return {
            "canonical_id": None, "canonical_brand": None, "canonical_generic": None,
            "match_method": "unmatched", "match_score": 0,
        }

    # Tier 1: exact match against the manual alias dictionary
    if cleaned in MANUAL_ALIAS_MAP:
        info = MANUAL_ALIAS_MAP[cleaned]
        return {**info, "match_method": "manual_exact", "match_score": 100}

    # Tier 2: fuzzy match against the same alias pool
    best = process.extractOne(
        cleaned, FUZZY_CANDIDATES.keys(), scorer=fuzz.WRatio
    )
    if best is not None:
        candidate_text, score, _ = best
        if score >= SCORE_THRESHOLD:
            canonical_id = FUZZY_CANDIDATES[candidate_text]
            info = CANONICAL_LOOKUP[canonical_id]
            return {
                "canonical_id": canonical_id,
                "canonical_brand": info["canonical_brand"],
                "canonical_generic": info["canonical_generic"],
                "match_method": "fuzzy",
                "match_score": round(score, 1),
            }

    # Tier 3: no confident match -- leave unmatched rather than guess
    return {
        "canonical_id": None, "canonical_brand": None, "canonical_generic": None,
        "match_method": "unmatched", "match_score": 0,
    }


def main() -> None:
    bronze_path = OUT_DIR / "bronze_adverse_events.csv"
    if not bronze_path.exists():
        raise SystemExit(f"{bronze_path} not found. Run 02_bronze_parse.py first.")

    bronze = pd.read_csv(bronze_path, dtype={"case_report_id": str})

    # Build the drug master table: one row per DISTINCT raw name (not per bronze row) --
    # this is the actual reference/master table you'd hand to a data steward.
    distinct_names = bronze["drug_name_raw"].dropna().unique()
    master_rows = [{"drug_name_raw": name, **match_name(name)} for name in sorted(distinct_names)]
    drug_master = pd.DataFrame(master_rows)

    master_path = OUT_DIR / "drug_master.csv"
    drug_master.to_csv(master_path, index=False)

    n_matched = (drug_master["match_method"] != "unmatched").sum()
    print(f"Drug master: {len(drug_master)} distinct raw names -> "
          f"{n_matched} mapped ({n_matched / len(drug_master):.1%}), "
          f"{len(drug_master) - n_matched} unmatched")
    print(drug_master["match_method"].value_counts().to_string())
    print(f"Wrote {master_path}")

    # Apply the mapping to bronze
    enriched = bronze.merge(drug_master, on="drug_name_raw", how="left")
    enriched_path = OUT_DIR / "bronze_with_canonical.csv"
    enriched.to_csv(enriched_path, index=False)
    print(f"Wrote {enriched_path} ({len(enriched)} rows)")


if __name__ == "__main__":
    main()
