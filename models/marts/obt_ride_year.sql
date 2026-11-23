{#
    One row per ride occupancy per company year with at least one kept
    ride-day. Ride-days of rides only are rolled up by the company year of
    their company date. A year still in progress covers only its captured
    days; first_company_date and last_company_date state that period. Ranks
    are within a park and company year, never across parks.
#}
with

ride_days as (
    select
        fct_ride_day.ride_key,
        fct_ride_day.park_id,
        fct_ride_day.company_date,
        dim_date.company_year,
        fct_ride_day.customers_increase,
        fct_ride_day.guest_rating_pct,
        fct_ride_day.ride_age_months
    from {{ ref("fct_ride_day") }} as fct_ride_day
    inner join {{ ref("dim_date") }} as dim_date
        on fct_ride_day.company_date = dim_date.company_date
    where fct_ride_day.classification = 'ride'
),

years as (
    select
        ride_key,
        park_id,
        company_year,
        min(company_date) as first_company_date,
        max(company_date) as last_company_date,
        count(*) as ride_days,
        sum(customers_increase) as riders,
        arg_max(guest_rating_pct, company_date) filter (
            where guest_rating_pct is not null
        ) as latest_guest_rating_pct,
        arg_max(ride_age_months, company_date) filter (
            where ride_age_months is not null
        ) as latest_ride_age_months
    from ride_days
    group by ride_key, park_id, company_year
),

named as (
    select
        years.*,
        dim_ride.ride_name
    from years
    inner join {{ ref("dim_ride") }} as dim_ride
        on years.ride_key = dim_ride.ride_key
),

ranked as (
    select
        named.*,
        row_number() over (
            partition by named.park_id, named.company_year
            order by named.riders desc nulls last, named.ride_key asc
        ) as riders_rank_in_park_year
    from named
)

select
    cast(ride_key || '|' || company_year as varchar) as ride_year_key,
    cast(ride_key as varchar) as ride_key,
    cast(park_id as varchar) as park_id,
    cast(ride_name as varchar) as ride_name,
    cast(company_year as integer) as company_year,
    cast(first_company_date as date) as first_company_date,
    cast(last_company_date as date) as last_company_date,
    cast(ride_days as integer) as ride_days,
    cast(riders as bigint) as riders,
    cast(riders_rank_in_park_year as integer) as riders_rank_in_park_year,
    cast(latest_guest_rating_pct as integer) as latest_guest_rating_pct,
    cast(latest_ride_age_months as integer) as latest_ride_age_months
from ranked
