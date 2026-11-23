{{ config(severity=sample_warn_severity(), store_failures=true) }}

-- One row means a game day in a closed month has no park snapshot, so the
-- month cannot be complete; replay save_to_replay. It is null when the session
-- before the gap started from the park's file, or when no kept day precedes
-- the gap; replay from the park's original file then.
-- Days before the park's first captured day are not checked. A park with no
-- snapshot has no first captured day and returns no row. A park-year without
-- a registry mapping has no calendar rows; the test
-- assert_every_kept_statement_has_a_company_date errors on its statements.
-- Severity follows ADR 0031: warn on ci and dev using the committed sample,
-- and error otherwise. The clock is the game day, with company dates carried
-- for reading.
with

statements as (
    select
        park_id,
        statement_year,
        statement_month,
        statement_company_date
    from {{ ref("fct_park_month") }}
),

calendar_days as (
    select
        park_id,
        game_year,
        game_month,
        game_day,
        company_date,
        (game_year * 8 + game_month) * 32 + game_day as day_index
    from {{ ref("int_park_days__company_calendar") }}
),

snapshot_days as (
    select distinct
        park_id,
        game_year,
        game_month,
        game_day
    from {{ ref("stg_park_snapshot") }}
),

first_captured as (
    select
        snapshot_days.park_id,
        min(
            (snapshot_days.game_year * 8 + snapshot_days.game_month) * 32
            + snapshot_days.game_day
        ) as first_day_index
    from snapshot_days
    group by snapshot_days.park_id
),

closed_month_days as (
    select
        calendar_days.park_id,
        statements.statement_year,
        statements.statement_month,
        statements.statement_company_date,
        calendar_days.game_year,
        calendar_days.game_month,
        calendar_days.game_day,
        calendar_days.company_date,
        calendar_days.day_index
    from calendar_days
    inner join statements
        on
            calendar_days.park_id = statements.park_id
            and calendar_days.game_year = statements.statement_year
            and calendar_days.game_month = statements.statement_month
    inner join first_captured
        on calendar_days.park_id = first_captured.park_id
    where calendar_days.day_index >= first_captured.first_day_index
),

never_captured as (
    select closed_month_days.*
    from closed_month_days
    left join snapshot_days
        on
            closed_month_days.park_id = snapshot_days.park_id
            and closed_month_days.game_year = snapshot_days.game_year
            and closed_month_days.game_month = snapshot_days.game_month
            and closed_month_days.game_day = snapshot_days.game_day
    where snapshot_days.park_id is null
),

kept_days as (
    select
        park_id,
        game_year,
        game_month,
        game_day,
        session_id,
        (game_year * 8 + game_month) * 32 + game_day as day_index
    from {{ ref("fct_park_day") }}
),

neighbour_indexes as (
    select
        never_captured.park_id,
        never_captured.game_year,
        never_captured.game_month,
        never_captured.game_day,
        max(kept_days.day_index) filter (
            where kept_days.day_index < never_captured.day_index
        ) as day_index_before,
        min(kept_days.day_index) filter (
            where kept_days.day_index > never_captured.day_index
        ) as day_index_after
    from never_captured
    left join kept_days
        on never_captured.park_id = kept_days.park_id
    group by
        never_captured.park_id,
        never_captured.game_year,
        never_captured.game_month,
        never_captured.game_day
),

neighbours as (
    select
        neighbour_indexes.park_id,
        neighbour_indexes.game_year,
        neighbour_indexes.game_month,
        neighbour_indexes.game_day,
        days_before.session_id as session_id_before,
        days_after.session_id as session_id_after
    from neighbour_indexes
    left join kept_days as days_before
        on
            neighbour_indexes.park_id = days_before.park_id
            and neighbour_indexes.day_index_before = days_before.day_index
    left join kept_days as days_after
        on
            neighbour_indexes.park_id = days_after.park_id
            and neighbour_indexes.day_index_after = days_after.day_index
),

with_save as (
    select
        never_captured.park_id,
        never_captured.statement_year,
        never_captured.statement_month,
        never_captured.statement_company_date,
        never_captured.game_year,
        never_captured.game_month,
        never_captured.game_day,
        never_captured.company_date,
        neighbours.session_id_before,
        neighbours.session_id_after,
        lineage.loaded_save_id as save_to_replay
    from never_captured
    inner join neighbours
        on
            never_captured.park_id = neighbours.park_id
            and never_captured.game_year = neighbours.game_year
            and never_captured.game_month = neighbours.game_month
            and never_captured.game_day = neighbours.game_day
    left join {{ ref("int_sessions__lineage") }} as lineage
        on neighbours.session_id_before = lineage.session_id
)

select
    park_id,
    statement_year,
    statement_month,
    statement_company_date,
    game_year,
    game_month,
    game_day,
    company_date,
    session_id_before,
    session_id_after,
    save_to_replay
from with_save
