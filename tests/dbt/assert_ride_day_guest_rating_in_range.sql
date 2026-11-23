-- The guest rating is a percent: out of range or on a non-ride is bad.
{{ config(severity='error') }}

select
    ride_day_key,
    ride_key,
    classification,
    guest_rating_pct
from {{ ref('fct_ride_day') }}
where
    guest_rating_pct not between 0 and 100
    or (guest_rating_pct is not null and classification <> 'ride')
