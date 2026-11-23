with recursive

kept_dates as (
    select company_date
    from {{ ref("int_park_days__kept") }}

    union all

    select statement_company_date as company_date
    from {{ ref("int_statements__labeled") }}
    where
        timeline_status = 'kept'
        and mapping_status = 'mapped'
),

bounds as (
    select
        cast(
            {{ dbt.date_trunc("month", "min(company_date)") }}
            as date
        ) as first_date,
        cast(
            {{ dbt.last_day("max(company_date)", "month") }}
            as date
        ) as last_date
    from kept_dates
),

all_dates (company_date) as (
    select first_date
    from bounds
    where first_date is not null

    union all

    select
        cast(
            {{ dbt.dateadd("day", "1", "company_date") }}
            as date
        )
    from all_dates
    cross join bounds
    where
        {{ dbt.dateadd("day", "1", "company_date") }}
        <= bounds.last_date
),

season_dates as (
    select company_date
    from all_dates
    where extract(month from company_date) between 3 and 10
),

month_names (company_month, month_name) as (
    values
    (3, 'March'),
    (4, 'April'),
    (5, 'May'),
    (6, 'June'),
    (7, 'July'),
    (8, 'August'),
    (9, 'September'),
    (10, 'October')
),

derived as (
    select
        cast(season_dates.company_date as date) as company_date,
        cast(extract(year from season_dates.company_date) as integer)
            as company_year,
        cast(extract(month from season_dates.company_date) as integer)
            as company_month,
        cast(month_names.month_name as varchar) as month_name,
        cast(extract(day from season_dates.company_date) as integer)
            as day_of_month,
        cast(
            {{ dbt.datediff(
                company_date("extract(year from season_dates.company_date)", "0", "1"),
                "season_dates.company_date",
                "day"
            ) }} + 1
            as integer
        ) as day_of_season,
        cast(
            season_dates.company_date = cast(
                {{ dbt.last_day(
                    "season_dates.company_date",
                    "month"
                ) }} as date
            )
            as boolean
        ) as is_month_end
    from season_dates
    inner join month_names
        on
            extract(month from season_dates.company_date)
            = month_names.company_month
)

select
    company_date,
    company_year,
    company_month,
    month_name,
    day_of_month,
    day_of_season,
    is_month_end
from derived
