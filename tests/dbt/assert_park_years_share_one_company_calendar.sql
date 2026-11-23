{{ config(severity="error", store_failures=true) }}

-- Returns a row (a failure) for each break in the one company calendar that
-- every park's years must share. The severity is error on every target. A row
-- names the check that failed (failed_check), the parks, the company year and
-- game year involved (null when the check spans years) and the values seen.
--   1  A park-year's company year differs from the registry recompute
--      company_start_year + (game_year - game_year_origin).
--   2  A park-year's first or last statement company date lies outside
--      1 March to 1 October of its company year.
--   3  A park has two rows for one company year, or two company years for one
--      game year.
--   4  One statement company date maps to two (company year, month) pairs,
--      across all parks' kept statements.
--   5  One (company year, month) pair maps to two statement company dates,
--      across all parks' kept statements.
-- Catches: a mart grouped on the wrong year column, a superseded registry row,
-- a date outside its season, duplicate current registry rows, and (checks 4
-- and 5) two parks that share a company year or a statement date and date one
-- company month differently. Checks 2, 4 and 5 are guards on the company_date
-- formula against a future model change: every statement date is
-- company_date(company_year, statement_month, 1), a one-to-one function, so
-- they cannot fire on data the pipeline builds today.
-- Cannot catch: a registry row that is wrong but self-consistent, because that
-- park's dates all shift into another valid company year and every check
-- agrees (ADR 0023, "What was given up"). With one park, checks 4 and 5 reduce
-- to per-park checks. Checks 4 and 5 compare parks only where they share a
-- company year or a date: two parks in separate company years with a
-- self-consistent shift pass. Exactly one managed park per company year is not
-- checked.
with

park_years as (
    select
        park_id,
        company_year,
        game_year,
        first_statement_company_date,
        last_statement_company_date
    from {{ ref("obt_park_year") }}
),

registry as (
    select
        park_id,
        company_start_year,
        game_year_origin
    from {{ ref("int_park_registry__current") }}
),

statements as (
    select distinct
        park_id,
        company_year,
        statement_month,
        statement_company_date,
        cast(statement_company_date as varchar) as date_label,
        cast(company_year as varchar)
        || '-' || cast(statement_month as varchar) as month_label
    from {{ ref("fct_park_month") }}
),

registry_recompute as (
    select
        1 as failed_check,
        park_years.park_id as parks,
        park_years.company_year,
        park_years.game_year,
        'company_year '
        || coalesce(cast(park_years.company_year as varchar), 'null')
        || ', registry recompute '
        || coalesce(
            cast(
                registry.company_start_year
                + (park_years.game_year - registry.game_year_origin)
                as varchar
            ),
            'no registry row'
        ) as observed
    from park_years
    left join registry
        on park_years.park_id = registry.park_id
    where
        park_years.company_year is distinct from (
            registry.company_start_year
            + (park_years.game_year - registry.game_year_origin)
        )
),

season_window as (
    select
        2 as failed_check,
        park_id as parks,
        company_year,
        game_year,
        'first ' || cast(first_statement_company_date as varchar)
        || ', last ' || cast(last_statement_company_date as varchar)
            as observed
    from park_years
    where
        first_statement_company_date
        not between make_date(company_year, 3, 1)
        and make_date(company_year, 10, 1)
        or last_statement_company_date
        not between make_date(company_year, 3, 1)
        and make_date(company_year, 10, 1)
),

repeated_company_year as (
    select
        3 as failed_check,
        park_id as parks,
        company_year,
        cast(null as integer) as game_year,
        cast(count(*) as varchar) || ' rows for one company year' as observed
    from park_years
    group by park_id, company_year
    having count(*) > 1
),

repeated_game_year as (
    select
        3 as failed_check,
        park_id as parks,
        cast(null as integer) as company_year,
        game_year,
        cast(count(*) as varchar) || ' rows for one game year' as observed
    from park_years
    group by park_id, game_year
    having count(*) > 1
),

one_date_two_months as (
    select
        4 as failed_check,
        string_agg(distinct park_id, ', ' order by park_id) as parks,
        cast(null as integer) as company_year,
        cast(null as integer) as game_year,
        date_label
        || ' maps to '
        || string_agg(distinct month_label, ', ' order by month_label)
            as observed
    from statements
    group by statement_company_date, date_label
    having count(distinct month_label) > 1
),

one_month_two_dates as (
    select
        5 as failed_check,
        string_agg(distinct park_id, ', ' order by park_id) as parks,
        company_year,
        cast(null as integer) as game_year,
        'month ' || cast(statement_month as varchar)
        || ' maps to '
        || string_agg(distinct date_label, ', ' order by date_label)
            as observed
    from statements
    group by company_year, statement_month
    having count(distinct date_label) > 1
)

select * from registry_recompute
union all
select * from season_window
union all
select * from repeated_company_year
union all
select * from repeated_game_year
union all
select * from one_date_two_months
union all
select * from one_month_two_dates
