-- Each row is a game day of a closed month that a session captured but that
-- was not kept, one row per park, day and session.
-- reason: save_boundary (snapshot fell at or after the session's proven cut);
-- no_cut (kept-path session wrote no save, so all its snapshots are abandoned);
-- abandoned_session (session off the kept path, or with no lineage row).
-- Real data lists one day per session boundary by design (ADR 0006, ADR 0024).
-- Warn severity: this never blocks a build. Never-captured days are the error
-- test's (`assert_every_day_of_a_closed_month_was_captured`). The clock is game
-- day, with company dates for reading.
{{ config(severity="warn", store_failures=true) }}

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

captured as (
    select distinct
        park_id,
        game_year,
        game_month,
        game_day,
        session_id
    from {{ ref("stg_park_snapshot") }}
),

kept_days as (
    select distinct
        park_id,
        game_year,
        game_month,
        game_day
    from {{ ref("fct_park_day") }}
),

not_kept as (
    select
        statements.park_id,
        statements.statement_year,
        statements.statement_month,
        calendar_days.game_year,
        calendar_days.game_month,
        calendar_days.game_day,
        calendar_days.company_date,
        captured.session_id
    from statements
    inner join calendar_days
        on
            statements.park_id = calendar_days.park_id
            and statements.statement_year = calendar_days.game_year
            and statements.statement_month = calendar_days.game_month
    inner join captured
        on
            calendar_days.park_id = captured.park_id
            and calendar_days.game_year = captured.game_year
            and calendar_days.game_month = captured.game_month
            and calendar_days.game_day = captured.game_day
    left join kept_days
        on
            calendar_days.park_id = kept_days.park_id
            and calendar_days.game_year = kept_days.game_year
            and calendar_days.game_month = kept_days.game_month
            and calendar_days.game_day = kept_days.game_day
    where kept_days.park_id is null
)

select
    not_kept.park_id,
    not_kept.statement_year,
    not_kept.statement_month,
    not_kept.game_year,
    not_kept.game_month,
    not_kept.game_day,
    not_kept.company_date,
    not_kept.session_id,
    case
        when lineage.is_on_kept_path and lineage.cut_seq is not null
            then 'save_boundary'
        when lineage.is_on_kept_path and lineage.cut_seq is null
            then 'no_cut'
        else 'abandoned_session'
    end as reason
from not_kept
left join {{ ref("int_sessions__lineage") }} as lineage
    on not_kept.session_id = lineage.session_id
