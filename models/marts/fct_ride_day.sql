{#
    One row per ride occupancy per game day on the kept timeline, cast from
    int_ride_days__kept without a join. The key is ride_key plus the game date;
    park_day_key links each row to fct_park_day.
#}
select
    cast(ride_day_key as varchar) as ride_day_key,
    cast(ride_key as varchar) as ride_key,
    cast(park_day_key as varchar) as park_day_key,
    cast(park_id as varchar) as park_id,
    cast(session_id as varchar) as session_id,
    cast(event_id as varchar) as event_id,
    cast(game_year as integer) as game_year,
    cast(game_month as integer) as game_month,
    cast(game_day as integer) as game_day,
    cast(company_date as date) as company_date,
    cast(classification as varchar) as classification,
    cast(ride_type as integer) as ride_type,
    cast(status as varchar) as status,
    cast(is_open_day as boolean) as is_open_day,
    cast(ride_age_months as integer) as ride_age_months,
    cast(excitement_hundredths as integer) as excitement_hundredths,
    cast(intensity_hundredths as integer) as intensity_hundredths,
    cast(nausea_hundredths as integer) as nausea_hundredths,
    cast(price_1_usd as decimal(18, 2)) as price_1_usd,
    cast(price_2_usd as decimal(18, 2)) as price_2_usd,
    cast(ride_price_listed_usd as decimal(18, 2))
        as ride_price_listed_usd,
    cast(customers_increase as bigint) as customers_increase,
    cast(profit_usd as decimal(18, 2)) as profit_usd,
    cast(availability_from_downtime_pct as integer)
        as availability_from_downtime_pct,
    cast(longest_queue_seen_minutes as integer) as longest_queue_seen_minutes,
    cast(guest_rating_pct as integer) as guest_rating_pct
from {{ ref("int_ride_days__kept") }}
