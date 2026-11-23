-- total_customers fall resets occupancy; negative delta: bad rule/partition.
{{ config(severity='error') }}

select
    ride_day_key,
    ride_key,
    session_id,
    event_id,
    customers_increase
from {{ ref('fct_ride_day') }}
where customers_increase < 0
