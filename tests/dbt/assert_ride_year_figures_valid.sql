{{ config(severity="error") }}

-- Returns each ride-year whose figures are out of range, and each park and
-- company year whose ranks are not exactly 1 to its row count.
with

ranks as (
    select
        park_id,
        company_year,
        count(*) as rides,
        count(distinct riders_rank_in_park_year) as distinct_ranks,
        min(riders_rank_in_park_year) as lowest_rank,
        max(riders_rank_in_park_year) as highest_rank
    from {{ ref("obt_ride_year") }}
    group by park_id, company_year
)

select
    ride_year_key,
    park_id,
    company_year
from {{ ref("obt_ride_year") }}
where
    ride_days < 1
    or first_company_date > last_company_date
    or riders < 0
    or riders_rank_in_park_year < 1
    or latest_guest_rating_pct < 0
    or latest_guest_rating_pct > 100
    or latest_ride_age_months < 0

union all

select
    cast(null as varchar) as ride_year_key,
    park_id,
    company_year
from ranks
where
    lowest_rank is distinct from 1
    or highest_rank is distinct from rides
    or distinct_ranks is distinct from rides
