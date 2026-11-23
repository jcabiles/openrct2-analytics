{#
    One row per ride occupancy per game month with at least one kept ride-day,
    labeled with its company month. Ride-days of rides only are rolled up by
    game month, so the page needs no classification filter and no daily rows.
    Availability is the mean of daily readings, never a share of the month.
#}
with

ride_days as (
    select
        ride_key,
        park_id,
        game_year,
        game_month,
        company_date,
        availability_from_downtime_pct,
        longest_queue_seen_minutes,
        customers_increase
    from {{ ref("fct_ride_day") }}
    where classification = 'ride'
),

months as (
    select
        ride_key,
        park_id,
        game_year,
        game_month,
        min(company_date) as first_company_date,
        count(*) as ride_days,
        avg(availability_from_downtime_pct) as average_availability,
        max(longest_queue_seen_minutes) as longest_queue_seen_minutes,
        sum(customers_increase) as riders
    from ride_days
    group by ride_key, park_id, game_year, game_month
),

labeled as (
    select
        months.*,
        dim_date.company_year
    from months
    inner join {{ ref("dim_date") }} as dim_date
        on months.first_company_date = dim_date.company_date
),

named as (
    select
        labeled.*,
        dim_ride.ride_name
    from labeled
    inner join {{ ref("dim_ride") }} as dim_ride
        on labeled.ride_key = dim_ride.ride_key
)

select
    cast(
        ride_key || '|' || game_year || '|' || game_month as varchar
    ) as ride_month_key,
    cast(ride_key as varchar) as ride_key,
    cast(park_id as varchar) as park_id,
    cast(ride_name as varchar) as ride_name,
    cast(game_year as integer) as game_year,
    cast(game_month as integer) as game_month,
    cast(company_year as integer) as company_year,
    cast(date_trunc('month', first_company_date) as date) as company_date,
    cast(ride_days as integer) as ride_days,
    cast(average_availability as decimal(18, 2))
        as average_availability_from_downtime_pct,
    cast(longest_queue_seen_minutes as integer)
        as longest_queue_seen_minutes,
    cast(riders as bigint) as riders
from named
