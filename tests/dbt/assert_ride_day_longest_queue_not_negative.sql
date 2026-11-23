-- Queue time in minutes cannot be negative, and only rides carry it.
{{ config(severity='error') }}

select
    ride_day_key,
    ride_key,
    classification,
    longest_queue_seen_minutes
from {{ ref('fct_ride_day') }}
where
    longest_queue_seen_minutes < 0
    or (longest_queue_seen_minutes is not null and classification <> 'ride')
