-- 07_sql_queries.sql
--
-- Analysis queries against the Gold layer, run in SQLite.
--
-- Run with:  sqlite3 data/processed/gold.db < scripts/07_sql_queries.sql
-- (or open data/processed/gold.db in DB Browser for SQLite / any SQLite client
--  and run each query interactively)
--
-- Table: gold_adverse_events (one row per unique case+drug, see 05_gold_dedup.py)

-- =============================================================
-- Query 1: Top 10 reported reactions per drug
-- Reactions are stored as a "; "-joined string per case (a case can have
-- multiple reactions), so we split them out with SQLite's json_each over a
-- json array built from the string, then count per drug+reaction.
-- =============================================================
WITH split_reactions AS (
    SELECT
        g.canonical_brand,
        TRIM(je.value) AS reaction
    FROM gold_adverse_events g,
         json_each('["' || REPLACE(g.reactions, '; ', '","') || '"]') je
    WHERE g.reactions IS NOT NULL AND g.reactions != ''
),
ranked AS (
    SELECT
        canonical_brand,
        reaction,
        COUNT(*) AS report_count,
        RANK() OVER (PARTITION BY canonical_brand ORDER BY COUNT(*) DESC) AS rnk
    FROM split_reactions
    GROUP BY canonical_brand, reaction
)
SELECT canonical_brand, reaction, report_count
FROM ranked
WHERE rnk <= 10
ORDER BY canonical_brand, report_count DESC;


-- =============================================================
-- Query 2: Adverse event report volume over time, by drug (by year)
-- =============================================================
SELECT
    canonical_brand,
    report_year,
    COUNT(*) AS report_count
FROM gold_adverse_events
WHERE report_year IS NOT NULL
GROUP BY canonical_brand, report_year
ORDER BY canonical_brand, report_year;


-- =============================================================
-- Query 3: Seriousness rate by drug (% of reports flagged as "serious",
-- plus the breakdown of death / hospitalization / life-threatening)
-- =============================================================
SELECT
    canonical_brand,
    COUNT(*) AS total_reports,
    SUM(is_serious) AS serious_reports,
    ROUND(100.0 * SUM(is_serious) / COUNT(*), 1) AS serious_rate_pct,
    SUM(seriousness_death) AS death_reports,
    SUM(seriousness_hospitalization) AS hospitalization_reports,
    SUM(seriousness_lifethreatening) AS lifethreatening_reports
FROM gold_adverse_events
GROUP BY canonical_brand
ORDER BY serious_rate_pct DESC;


-- =============================================================
-- Query 4: Data quality issues by reporting country
-- (which countries' submissions have the most missing/invalid data)
-- =============================================================
SELECT
    reporting_country,
    COUNT(*) AS total_reports,
    SUM(CASE WHEN data_quality_flag != 'OK' THEN 1 ELSE 0 END) AS reports_with_issues,
    ROUND(100.0 * SUM(CASE WHEN data_quality_flag != 'OK' THEN 1 ELSE 0 END) / COUNT(*), 1) AS issue_rate_pct
FROM gold_adverse_events
GROUP BY reporting_country
HAVING total_reports >= 10   -- ignore countries with too few reports to be meaningful
ORDER BY issue_rate_pct DESC
LIMIT 20;


-- =============================================================
-- Query 5: Reaction profile by age group and drug -- which age groups
-- report which reactions most, useful for spotting demographic-specific
-- safety signals
-- =============================================================
SELECT
    canonical_brand,
    age_group,
    COUNT(*) AS report_count,
    ROUND(100.0 * SUM(is_serious) / COUNT(*), 1) AS serious_rate_pct
FROM gold_adverse_events
WHERE age_group IS NOT NULL
GROUP BY canonical_brand, age_group
ORDER BY canonical_brand, age_group;
