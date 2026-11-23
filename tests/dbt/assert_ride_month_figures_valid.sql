{{ config(severity="error") }}

-- Returns each ride-month whose count, availability, queue or riders is
-- out of range.
select
    ride_month_key,
    ride_days,
    average_availability_from_downtime_pct,
    longest_queue_seen_minutes,
    riders
from {{ ref("obt_ride_month") }}
where
    ride_days < 1
    or average_availability_from_downtime_pct < 0
    or average_availability_from_downtime_pct > 100
    or longest_queue_seen_minutes < 0
    or riders < 0
