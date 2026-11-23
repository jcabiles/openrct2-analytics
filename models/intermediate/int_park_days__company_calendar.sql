{#
    One row per park and valid game day in every mapped park-year. The
    company date is derived once per month, then advanced by the game day.
#}
with

mapped_years as (
    select
        park_id,
        game_year,
        company_year
    from {{ ref("int_park_years__registry_mapped") }}
    where mapping_status = 'mapped'
),

game_months as (
    select month_values.game_month
    from (
        values
        (0), (1), (2), (3), (4), (5), (6), (7)
    ) as month_values (game_month)
),

day_numbers as (
    select day_values.game_day
    from (
        values
        (1), (2), (3), (4), (5), (6), (7), (8), (9), (10),
        (11), (12), (13), (14), (15), (16), (17), (18), (19), (20),
        (21), (22), (23), (24), (25), (26), (27), (28), (29), (30), (31)
    ) as day_values (game_day)
),

month_starts as (
    select
        mapped_years.park_id,
        mapped_years.game_year,
        mapped_years.company_year,
        game_months.game_month,
        cast(
            {{ company_date(
                "mapped_years.company_year",
                "game_months.game_month",
                "1"
            ) }} as date
        ) as month_start
    from mapped_years
    cross join game_months
),

days as (
    select
        month_starts.park_id,
        month_starts.game_year,
        month_starts.game_month,
        day_numbers.game_day,
        month_starts.company_year,
        cast(
            {{ dbt.dateadd(
                "day",
                "day_numbers.game_day - 1",
                "month_start"
            ) }} as date
        ) as company_date,
        month_starts.month_start
    from month_starts
    cross join day_numbers
),

valid_days as (
    select
        park_id,
        game_year,
        game_month,
        game_day,
        company_year,
        company_date
    from days
    where
        cast({{ dbt.date_trunc("month", "company_date") }} as date)
        = month_start
),

keyed as (
    select
        park_id,
        game_year,
        game_month,
        game_day,
        company_year,
        company_date,
        park_id || '|' || game_year || '|' || game_month || '|' || game_day
            as park_day_key
    from valid_days
)

select
    park_day_key,
    park_id,
    game_year,
    game_month,
    game_day,
    company_year,
    company_date
from keyed
