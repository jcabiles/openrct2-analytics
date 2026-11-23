{{ config(severity="error") }}

with calendar as (
    select
        park_id,
        game_year,
        game_month,
        game_day,
        company_date,
        {{ company_date(
            "company_year",
            "game_month",
            "game_day"
        ) }} as expected_company_date
    from {{ ref("int_park_days__company_calendar") }}
),

calendar_date_failures as (
    select
        'company_date_mismatch' as failure,
        park_id,
        game_year,
        game_month,
        game_day,
        company_date,
        expected_company_date,
        cast(null as integer) as calendar_row_count
    from calendar
    where company_date is distinct from expected_company_date
),

calendar_counts as (
    select
        mapped.park_id,
        mapped.game_year,
        count(calendar.park_id) as calendar_row_count
    from {{ ref("int_park_years__registry_mapped") }} as mapped
    left join {{ ref("int_park_days__company_calendar") }} as calendar
        on
            mapped.park_id = calendar.park_id
            and mapped.game_year = calendar.game_year
    where mapped.mapping_status = 'mapped'
    group by mapped.park_id, mapped.game_year
),

calendar_count_failures as (
    select
        'calendar_day_count' as failure,
        park_id,
        game_year,
        cast(null as integer) as game_month,
        cast(null as integer) as game_day,
        cast(null as date) as company_date,
        cast(null as date) as expected_company_date,
        calendar_row_count
    from calendar_counts
    where calendar_row_count != 245
)

select
    failure,
    park_id,
    game_year,
    game_month,
    game_day,
    company_date,
    expected_company_date,
    calendar_row_count
from calendar_date_failures
union all
select
    failure,
    park_id,
    game_year,
    game_month,
    game_day,
    company_date,
    expected_company_date,
    calendar_row_count
from calendar_count_failures
