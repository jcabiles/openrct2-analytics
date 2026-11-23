{{ config(severity="warn") }}

-- Warns when ride-day rows labeled abandoned differ from row 12's layer
-- difference, which also includes any same-day reading collapse, or when row
-- 12 is missing.
with

labeled_abandoned as (
    select count(*) as rows_excluded
    from {{ ref("stg_ride_snapshot") }} as rides
    left join {{ ref("int_sessions__lineage") }} as lineage
        on rides.session_id = lineage.session_id
    where {{ timeline_status("rides.seq", "lineage") }} = 'abandoned'
),

ride_day_count as (
    select rows_excluded
    from {{ ref("fct_cleaning_rule_count") }}
    where
        rule_name = 'abandoned_branch'
        and model_name = 'int_ride_days__kept'
)

select
    labeled_abandoned.rows_excluded as labeled_rows_excluded,
    ride_day_count.rows_excluded as counted_rows_excluded
from labeled_abandoned
left join ride_day_count on true
where
    ride_day_count.rows_excluded is null
    or labeled_abandoned.rows_excluded != ride_day_count.rows_excluded
