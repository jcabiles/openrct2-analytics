-- Availability is a percent: out of range or on a non-ride is a bad rule.
{{ config(severity='error') }}

select
    ride_day_key,
    ride_key,
    classification,
    availability_from_downtime_pct
from {{ ref('fct_ride_day') }}
where
    availability_from_downtime_pct not between 0 and 100
    or (availability_from_downtime_pct is not null and classification <> 'ride')
