{#
    One row per park per game day on the kept timeline. The game-date key
    stays independent of company_date, which is carried from the intermediate
    model alongside day-start readings and the next kept admissions rise.
#}
select
    cast(park_day_key as varchar) as park_day_key,
    cast(park_id as varchar) as park_id,
    cast(session_id as varchar) as session_id,
    cast(event_id as varchar) as event_id,
    cast(game_year as integer) as game_year,
    cast(game_month as integer) as game_month,
    cast(game_day as integer) as game_day,
    cast(company_date as date) as company_date,
    cast(admissions_increase as bigint) as admissions_increase,
    cast(park_rating as integer) as park_rating,
    cast(guests_in_park as integer) as guests_in_park,
    cast(cash_usd as decimal(18, 2)) as cash_usd,
    cast(weather as varchar) as weather,
    cast(temperature_c as integer) as temperature_c,
    true as is_kept_operating_day
from {{ ref("int_park_days__kept") }}
