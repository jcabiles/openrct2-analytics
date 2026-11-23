{#
    The close register: one row per expected park and company year, from the
    park's company_start_year in the current registry to the latest company
    year with a kept statement. A park's partial first season (its first
    captured day could not carry March's statement: game month 1 or later,
    except day 1 of month 1, whose callback delivers March's statement) is
    exempt and flagged. A park with no statement for a company year that it
    already moved past is incomplete, and so is one with a kept month later
    in the same year than a missing reportable month; one whose only missing
    months come after its last kept month, or with nothing kept, may still be
    playing the year and is open. The year-closing rule lives in year_closes,
    so reversing it is a change to that one CTE.
#}
with

registered_parks as (
    select
        park_id,
        company_start_year
    from {{ ref("int_park_registry__current") }}
),

latest_year as (
    select max(company_year) as latest_company_year
    from {{ ref("fct_park_month") }}
),

year_range as (
    select
        min(registered_parks.company_start_year) as first_year,
        max(latest_year.latest_company_year) as last_year
    from registered_parks
    cross join latest_year
),

all_years as (
    select unnest(generate_series(first_year, last_year)) as company_year
    from year_range
),

expected_years as (
    select
        registered_parks.park_id,
        registered_parks.company_start_year,
        all_years.company_year
    from registered_parks
    inner join all_years
        on registered_parks.company_start_year <= all_years.company_year
),

ranked_snapshots as (
    select
        park_id,
        game_year,
        game_month,
        game_day,
        row_number() over (
            partition by park_id
            order by game_year, game_month, game_day
        ) as day_rank
    from {{ ref("stg_park_snapshot") }}
),

first_captured as (
    select
        ranked_snapshots.park_id,
        mapped.company_year as first_captured_company_year,
        -- A day-1 callback also delivers the previous month's statement, so
        -- a first captured day 1 of month m already carries month m - 1.
        -- Month 0 day 1 carries the previous year's last statement, which
        -- lies before the start year and is not counted here.
        case
            when
                ranked_snapshots.game_day = 1
                and ranked_snapshots.game_month >= 1
                then ranked_snapshots.game_month - 1
            else ranked_snapshots.game_month
        end as first_reachable_month
    from ranked_snapshots
    left join {{ ref("int_park_years__registry_mapped") }} as mapped
        on
            ranked_snapshots.park_id = mapped.park_id
            and ranked_snapshots.game_year = mapped.game_year
    where ranked_snapshots.day_rank = 1
),

statements as (
    select distinct
        park_id,
        company_year,
        statement_month
    from {{ ref("fct_park_month") }}
),

last_statement as (
    select
        park_id,
        max(company_year) as last_statement_year
    from statements
    group by park_id
),

first_seasons as (
    select
        expected_years.park_id,
        expected_years.company_year,
        first_captured.first_captured_company_year,
        first_captured.first_reachable_month,
        coalesce(
            expected_years.company_year = expected_years.company_start_year
            and first_captured.first_captured_company_year
            = expected_years.company_year
            and first_captured.first_reachable_month >= 1,
            false
        ) as is_partial_first_season
    from expected_years
    left join first_captured
        on expected_years.park_id = first_captured.park_id
),

seasons as (
    select
        first_seasons.park_id,
        first_seasons.company_year,
        first_seasons.first_captured_company_year,
        first_seasons.is_partial_first_season,
        last_statement.last_statement_year,
        case
            when first_seasons.is_partial_first_season
                then first_seasons.first_reachable_month
            else 0
        end as first_reportable_month
    from first_seasons
    left join last_statement
        on first_seasons.park_id = last_statement.park_id
),

season_months as (
    select
        seasons.park_id,
        seasons.company_year,
        seasons.first_captured_company_year,
        seasons.is_partial_first_season,
        seasons.first_reportable_month,
        calendar.statement_month,
        coalesce(seasons.last_statement_year > seasons.company_year, false)
            as has_later_statement,
        statements.statement_month is not null as is_kept
    from seasons
    cross join unnest(generate_series(0, 7)) as calendar (statement_month)
    left join statements
        on
            seasons.park_id = statements.park_id
            and seasons.company_year = statements.company_year
            and calendar.statement_month = statements.statement_month
),

park_years as (
    select
        park_id,
        company_year,
        first_captured_company_year,
        is_partial_first_season,
        first_reportable_month,
        has_later_statement,
        cast(8 - first_reportable_month as integer) as statements_expected,
        cast(count(*) filter (where is_kept) as integer) as statements_kept,
        coalesce(
            string_agg(
                cast(statement_month as varchar), ','
                order by statement_month
            ) filter (
                where not is_kept and statement_month >= first_reportable_month
            ),
            ''
        ) as missing_statement_months,
        coalesce(
            max(statement_month) filter (where is_kept)
            > min(statement_month) filter (
                where not is_kept and statement_month >= first_reportable_month
            ),
            false
        ) as has_kept_month_after_gap
    from season_months
    group by
        park_id,
        company_year,
        first_captured_company_year,
        is_partial_first_season,
        first_reportable_month,
        has_later_statement
),

statused as (
    select
        *,
        case
            when is_partial_first_season then 'partial_first_season'
            when missing_statement_months = '' then 'complete'
            when
                has_later_statement or has_kept_month_after_gap
                then 'incomplete'
            else 'open'
        end as close_status
    from park_years
),

year_closes as (
    select
        company_year,
        coalesce(
            count(*) filter (where close_status in ('open', 'incomplete')) = 0
            and count(*) filter (where close_status = 'complete') >= 1,
            false
        ) as is_company_year_closed
    from statused
    group by company_year
)

select
    statused.park_id,
    statused.company_year,
    statused.first_captured_company_year,
    statused.is_partial_first_season,
    statused.first_reportable_month,
    statused.statements_expected,
    statused.statements_kept,
    statused.missing_statement_months,
    statused.has_later_statement,
    statused.has_kept_month_after_gap,
    statused.close_status,
    year_closes.is_company_year_closed,
    statused.park_id || '|' || cast(statused.company_year as varchar)
        as park_year_close_key
from statused
inner join year_closes
    on statused.company_year = year_closes.company_year
