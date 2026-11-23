{#
    One row per park and game year landed in stg_envelope, mapped to a company
    year by int_park_years__registry_mapped. A park-year the registry cannot
    map stays in the model with a mapping_status other than mapped and null
    dates, and a singular test fails the build on it. Every month-to-date
    rule lives in the company_date macro, including what counts as a month
    out of range (probed with a fixed year, since only the month decides).
#}
with

landed_days as (
    select distinct
        park_id,
        game_year,
        game_month,
        game_day
    from {{ ref("stg_envelope") }}
),

ranked_days as (
    select
        park_id,
        game_year,
        game_month,
        game_day,
        row_number() over (
            partition by park_id, game_year
            order by game_month, game_day
        ) as from_first,
        row_number() over (
            partition by park_id, game_year
            order by game_month desc, game_day desc
        ) as from_last,
        case
            when {{ company_date("2000", "game_month", "1") }} is null
                then 1
            else 0
        end as is_month_out_of_range
    from landed_days
),

park_years as (
    select
        park_id,
        game_year,
        max(case when from_first = 1 then game_month end) as first_month,
        max(case when from_first = 1 then game_day end) as first_day,
        max(case when from_last = 1 then game_month end) as last_month,
        max(case when from_last = 1 then game_day end) as last_day,
        sum(is_month_out_of_range) as months_out_of_range
    from ranked_days
    group by park_id, game_year
),

registered as (
    select
        park_years.park_id,
        park_years.game_year,
        park_years.first_month,
        park_years.first_day,
        park_years.last_month,
        park_years.last_day,
        years.data_set,
        years.company_start_year,
        years.game_year_origin,
        years.company_year as mapped_company_year,
        case
            when years.mapping_status != 'mapped'
                then years.mapping_status
            when park_years.months_out_of_range > 0
                then 'game_month_out_of_range'
            when years.mapping_status = 'mapped'
                then 'mapped'
        end as mapping_status
    from park_years
    left join {{ ref("int_park_years__registry_mapped") }} as years
        on
            park_years.park_id = years.park_id
            and park_years.game_year = years.game_year
)

select
    park_id,
    game_year,
    data_set,
    company_start_year,
    game_year_origin,
    case
        when mapping_status = 'mapped' then mapped_company_year
    end as company_year,
    {{ company_date("company_year", "0", "1") }} as season_start,
    {{ company_date("company_year", "7", "31") }} as season_end,
    {{ company_date("company_year", "first_month", "first_day") }}
        as first_company_date,
    {{ company_date("company_year", "last_month", "last_day") }}
        as last_company_date,
    mapping_status
from registered
