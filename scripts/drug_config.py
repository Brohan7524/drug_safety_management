"""
Shared configuration: the list of canonical drugs this project tracks.

Each entry defines one real-world drug substance and the various brand/generic
names it is known by. This list is the seed for two different things:

1. 01_fetch_data.py uses `search_terms` to query the openFDA API (raw text
   search against patient.drug.medicinalproduct, the "as reported" field).
2. 03_drug_master_mapping.py uses `canonical_brand` / `canonical_generic` /
   `known_aliases` to build the manual alias dictionary and the fuzzy-match
   candidate pool for standardizing messy reported names.

Picked to include both brand+generic pairs (Humira/Adalimumab) and a drug
with TWO common brand names for the same generic (Advil/Motrin/Ibuprofen),
since that's the scenario that actually requires drug-name standardization.
"""

CANONICAL_DRUGS = [
    {
        "canonical_id": "ADALIMUMAB",
        "canonical_brand": "Humira",
        "canonical_generic": "Adalimumab",
        # Terms used to query openFDA (matched against medicinalproduct free text)
        "search_terms": ["HUMIRA", "ADALIMUMAB"],
        # Known aliases/variants seen in real FAERS data -> manual mapping seed
        "known_aliases": [
            "HUMIRA", "HUMIRA PEN", "HUMIRA(ADALIMUMAB)", "ADALIMUMAB",
            "ADALIMUMAB-ADBM", "ADALIMUMAB-ADAZ", "ADALIMUMAB [HUMIRA]",
        ],
    },
    {
        "canonical_id": "ATORVASTATIN",
        "canonical_brand": "Lipitor",
        "canonical_generic": "Atorvastatin",
        "search_terms": ["LIPITOR", "ATORVASTATIN"],
        "known_aliases": [
            "LIPITOR", "ATORVASTATIN", "ATORVASTATIN CALCIUM",
            "ATORVASTATIN (LIPITOR)", "LIPITOR (ATORVASTATIN CALCIUM)",
        ],
    },
    {
        "canonical_id": "METFORMIN",
        "canonical_brand": "Glucophage",
        "canonical_generic": "Metformin",
        "search_terms": ["GLUCOPHAGE", "METFORMIN"],
        "known_aliases": [
            "GLUCOPHAGE", "GLUCOPHAGE XR", "METFORMIN", "METFORMIN HCL",
            "METFORMIN HYDROCHLORIDE", "METFORMIN (GLUCOPHAGE)",
        ],
    },
    {
        "canonical_id": "OMEPRAZOLE",
        "canonical_brand": "Prilosec",
        "canonical_generic": "Omeprazole",
        "search_terms": ["PRILOSEC", "OMEPRAZOLE"],
        "known_aliases": [
            "PRILOSEC", "PRILOSEC OTC", "OMEPRAZOLE", "OMEPRAZOLE MAGNESIUM",
            "OMEPRAZOLE (PRILOSEC)",
        ],
    },
    {
        "canonical_id": "FLUOXETINE",
        "canonical_brand": "Prozac",
        "canonical_generic": "Fluoxetine",
        "search_terms": ["PROZAC", "FLUOXETINE"],
        "known_aliases": [
            "PROZAC", "FLUOXETINE", "FLUOXETINE HCL",
            "FLUOXETINE HYDROCHLORIDE", "FLUOXETINE (PROZAC)",
        ],
    },
    {
        "canonical_id": "IBUPROFEN",
        # Two brand names for the same generic substance -- the key case
        # that makes drug-name standardization necessary rather than a
        # simple dictionary lookup.
        "canonical_brand": "Advil/Motrin",
        "canonical_generic": "Ibuprofen",
        "search_terms": ["ADVIL", "MOTRIN", "IBUPROFEN"],
        "known_aliases": [
            "ADVIL", "MOTRIN", "IBUPROFEN", "IBUPROFEN (ADVIL)",
            "IBUPROFEN (MOTRIN)", "CHILDRENS ADVIL", "CHILDRENS MOTRIN",
            "JUNIOR STRENGTH ADVIL", "ADVIL PM",
        ],
    },
]

# FAERS coded value lookups (from the FDA FAERS data element definitions)
AGE_UNIT_TO_YEARS = {
    "800": 10,       # Decade
    "801": 1,        # Year
    "802": 1 / 12,   # Month
    "803": 1 / 52,   # Week
    "804": 1 / 365,  # Day
    "805": 1 / 8760,  # Hour
}

SEX_MAP = {
    "1": "Male",
    "2": "Female",
    "0": "Unknown",
}
