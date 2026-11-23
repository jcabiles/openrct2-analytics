{{ config(severity="error") }}

-- Returns each ride and company year where the riders summed from ride-days,
-- from ride-months and from the ride-year row are not all equal.
with

ride_day_riders as (
    select
        fct_ride_day.ride_key,
        dim_date.company_year,
        sum(fct_ride_day.customers_increase) as day_riders
    from {{ ref("fct_ride_day") }} as fct_ride_day
    inner join {{ ref("dim_date") }} as dim_date
        on fct_ride_day.company_date = dim_date.company_date
    where fct_ride_day.classification = 'ride'
    group by fct_ride_day.ride_key, dim_date.company_year
),

month_riders as (
    select
        ride_key,
        company_year,
        sum(riders) as month_riders
    from {{ ref("obt_ride_month") }}
    group by ride_key, company_year
),

year_riders as (
    select
        ride_key,
        company_year,
        riders as year_riders
    from {{ ref("obt_ride_year") }}
),

keys as (
    select
        ride_key,
        company_year
    from ride_day_riders

    union

    select
        ride_key,
        company_year
    from month_riders

    union

    select
        ride_key,
        company_year
    from year_riders
)

select
    keys.ride_key,
    keys.company_year,
    ride_day_riders.day_riders,
    month_riders.month_riders,
    year_riders.year_riders
from keys
left join ride_day_riders
    on
        keys.ride_key = ride_day_riders.ride_key
        and keys.company_year = ride_day_riders.company_year
left join month_riders
    on
        keys.ride_key = month_riders.ride_key
        and keys.company_year = month_riders.company_year
left join year_riders
    on
        keys.ride_key = year_riders.ride_key
        and keys.company_year = year_riders.company_year
where
    ride_day_riders.ride_key is null
    or month_riders.ride_key is null
    or year_riders.ride_key is null
    or ride_day_riders.day_riders is distinct from month_riders.month_riders
    or ride_day_riders.day_riders is distinct from year_riders.year_riders
