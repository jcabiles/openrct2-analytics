{#
    Answers which parks are registered, their latest kept session labels, and
    the span of their kept company dates. Grain: one row per registered park;
    key: park_id. Labels use Type 1 replacement. park_number is the park's
    1-based position among non-Sandbox parks by company start year, then the
    earliest session start of any session (nulls last), then park ID; Sandbox
    parks have none. Unit: none; clock: company date for the first and last
    kept park-day, wall clock for the latest kept session start, and for the
    park number the company start year order with the earliest session start
    (wall clock) as tie-break.
#}
with

registry as (
    select
        park_id,
        company_start_year,
        game_year_origin,
        data_set,
        note
    from {{ ref("int_park_registry__current") }}
),

first_starts as (
    select
        park_id,
        min(emitted_at) as first_session_start
    from {{ ref("stg_session_start") }}
    group by park_id
),

numbered as (
    select
        registry.park_id,
        cast(row_number() over (
            order by
                registry.company_start_year asc,
                first_starts.first_session_start asc nulls last,
                registry.park_id asc
        ) as integer) as park_number
    from registry
    left join first_starts
        on registry.park_id = first_starts.park_id
    where registry.note is distinct from {{ practice_note() }}
),

kept_starts as (
    select
        session_starts.park_id,
        session_starts.session_id,
        session_starts.emitted_at,
        session_starts.park_name,
        session_starts.scenario_name,
        session_starts.climate,
        row_number() over (
            partition by session_starts.park_id
            order by
                session_starts.emitted_at desc,
                session_starts.session_id desc
        ) as start_rank
    from {{ ref("stg_session_start") }} as session_starts
    left join {{ ref("int_sessions__lineage") }} as lineage
        on session_starts.session_id = lineage.session_id
    where
        {{ timeline_status("session_starts.seq", "lineage") }} = 'kept'
),

latest_start as (
    select
        park_id,
        park_name,
        scenario_name,
        climate
    from kept_starts
    where start_rank = 1
),

park_days as (
    select
        park_id,
        min(company_date) as first_company_date,
        max(company_date) as last_company_date
    from {{ ref("int_park_days__kept") }}
    group by park_id
),

final as (
    select
        registry.park_id,
        latest_start.park_name,
        latest_start.scenario_name,
        latest_start.climate,
        registry.data_set,
        registry.company_start_year,
        registry.game_year_origin,
        numbered.park_number,
        park_days.first_company_date,
        park_days.last_company_date
    from registry
    left join numbered
        on registry.park_id = numbered.park_id
    left join latest_start
        on registry.park_id = latest_start.park_id
    left join park_days
        on registry.park_id = park_days.park_id
)

select
    park_id,
    park_name,
    scenario_name,
    climate,
    data_set,
    company_start_year,
    game_year_origin,
    park_number,
    first_company_date,
    last_company_date
from final
