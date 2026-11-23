{{ config(severity="error") }}

-- Returns each count row where rows_in differs from rows_kept plus
-- rows_excluded, any count is negative, or both rows_excluded and
-- rows_changed are positive. Rows 13 and 20 (abandoned_branch for
-- fct_park_month, and exit_without_arrival) are the real identity checks,
-- because their rows_excluded is counted on its own. The other 18 pass by
-- construction: a removed count is the difference of two row counts, and a
-- rule that changes values keeps every row. They are protected only by the
-- negative-count and both-above-0 clauses. This test runs on every target.
select
    cleaning_rule_key,
    rows_in,
    rows_kept,
    rows_excluded,
    rows_changed
from {{ ref("fct_cleaning_rule_count") }}
where
    rows_in != rows_kept + rows_excluded
    or rows_in < 0
    or rows_kept < 0
    or rows_excluded < 0
    or rows_changed < 0
    or (rows_excluded > 0 and rows_changed > 0)
