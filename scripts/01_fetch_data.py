"""
01_fetch_data.py

Pulls adverse event reports from the openFDA Drug Adverse Event API
(https://api.fda.gov/drug/event.json) for the drugs listed in drug_config.py,
and caches the raw JSON responses to disk.

Design decisions:
- No API key is used. openFDA allows ~240 requests/min and 1,000/day per IP
  without one, which is plenty for a one-time data pull like this. If you
  hit a 429, the script backs off and retries.
- We search on `patient.drug.medicinalproduct`, the free-text "as reported"
  drug name field, using each brand/generic term separately. This is
  deliberately the messy field (not openFDA's own normalized brand_name/
  generic_name arrays) because the whole point of this project is to
  standardize inconsistent drug names ourselves.
- Raw pages are cached as one JSON file per (search term, page). Re-running
  the script skips any page already on disk, so you only hit the API once.
- Pagination uses `skip`/`limit`. openFDA actually allows `limit` up to 1000,
  but (undocumented, confirmed empirically) any request with `limit>=1000`
  gets rejected with a 403 API_KEY_MISSING error when no key is supplied --
  `limit<=500` works fine anonymously. So we page in batches of 500. Deep
  paging is also effectively disallowed (skip beyond ~25000), so we cap the
  number of pages per search term with MAX_RECORDS_PER_TERM.
"""
import json
import time
from pathlib import Path

import requests

from drug_config import CANONICAL_DRUGS

API_URL = "https://api.fda.gov/drug/event.json"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

PAGE_SIZE = 500  # openFDA requires an API key for limit>=1000; 500 works anonymously
MAX_RECORDS_PER_TERM = 1500  # 3 pages per search term -> keeps the pull small but real
REQUEST_TIMEOUT = 30
MAX_RETRIES = 5


def fetch_page(search_term: str, skip: int, limit: int) -> dict | None:
    """Fetch one page of results for a search term, retrying on rate limits."""
    params = {
        "search": f'patient.drug.medicinalproduct:"{search_term}"',
        "limit": limit,
        "skip": skip,
    }
    for attempt in range(1, MAX_RETRIES + 1):
        resp = requests.get(API_URL, params=params, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 404:
            # openFDA returns 404 when a search matches zero records
            print(f"    no more results for {search_term!r} at skip={skip}")
            return None
        if resp.status_code == 429:
            wait = 2 ** attempt
            print(f"    rate limited, backing off {wait}s (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(wait)
            continue
        # Other errors: log and give up on this page
        print(f"    request failed ({resp.status_code}): {resp.text[:200]}")
        return None
    print(f"    gave up on {search_term!r} skip={skip} after {MAX_RETRIES} retries")
    return None


def cache_path(search_term: str, skip: int) -> Path:
    safe_term = search_term.replace(" ", "_").replace("/", "_")
    return RAW_DIR / f"{safe_term}_skip{skip}.json"


def fetch_search_term(search_term: str) -> None:
    """Fetch (and cache) all pages for one search term up to the record cap."""
    for skip in range(0, MAX_RECORDS_PER_TERM, PAGE_SIZE):
        out_path = cache_path(search_term, skip)
        if out_path.exists():
            print(f"    skip={skip}: already cached ({out_path.name})")
            continue

        print(f"    skip={skip}: fetching...")
        data = fetch_page(search_term, skip, PAGE_SIZE)
        if data is None:
            break  # no more results (or unrecoverable error) -- stop paging this term

        out_path.write_text(json.dumps(data), encoding="utf-8")
        n_results = len(data.get("results", []))
        print(f"    skip={skip}: cached {n_results} records -> {out_path.name}")

        if n_results < PAGE_SIZE:
            break  # last page

        time.sleep(0.3)  # be polite, stay well under the rate limit


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    all_terms = sorted({term for drug in CANONICAL_DRUGS for term in drug["search_terms"]})

    print(f"Fetching openFDA adverse event data for {len(all_terms)} search terms...")
    for term in all_terms:
        print(f"  [{term}]")
        fetch_search_term(term)

    print("Done. Raw JSON cached in", RAW_DIR)


if __name__ == "__main__":
    main()
