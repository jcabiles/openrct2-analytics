-- Returns a row (a failure) for each event type whose row count in
-- stg_envelope differs from its landed source, repeat deliveries included.
-- An empty source and an empty envelope agree at zero, so an empty extract
-- passes.
with

source_counts as (
    select
        'finance_month' as event_type,
        count(*) as source_rows
    from {{ source("landing", "finance_month") }}

    union all

    select
        'game_action' as event_type,
        count(*) as source_rows
    from {{ source("landing", "game_action") }}

    union all

    select
        'guest_arrived' as event_type,
        count(*) as source_rows
    from {{ source("landing", "guest_arrived") }}

    union all

    select
        'guest_boarded' as event_type,
        count(*) as source_rows
    from {{ source("landing", "guest_boarded") }}

    union all

    select
        'guest_left' as event_type,
        count(*) as source_rows
    from {{ source("landing", "guest_left") }}

    union all

    select
        'guest_refused' as event_type,
        count(*) as source_rows
    from {{ source("landing", "guest_refused") }}

    union all

    select
        'guest_snapshot' as event_type,
        count(*) as source_rows
    from {{ source("landing", "guest_snapshot") }}

    union all

    select
        'park_snapshot' as event_type,
        count(*) as source_rows
    from {{ source("landing", "park_snapshot") }}

    union all

    select
        'plugin_stats' as event_type,
        count(*) as source_rows
    from {{ source("landing", "plugin_stats") }}

    union all

    select
        'ride_snapshot' as event_type,
        count(*) as source_rows
    from {{ source("landing", "ride_snapshot") }}

    union all

    select
        'save_written' as event_type,
        count(*) as source_rows
    from {{ source("landing", "save_written") }}

    union all

    select
        'session_start' as event_type,
        count(*) as source_rows
    from {{ source("landing", "session_start") }}

    union all

    select
        'weather_change' as event_type,
        count(*) as source_rows
    from {{ source("landing", "weather_change") }}
),

envelope_counts as (
    select
        event_type,
        count(*) as envelope_rows
    from {{ ref("stg_envelope") }}
    group by event_type
)

select
    s.event_type,
    s.source_rows,
    coalesce(e.envelope_rows, 0) as envelope_rows
from source_counts as s
left join envelope_counts as e on s.event_type = e.event_type
where s.source_rows != coalesce(e.envelope_rows, 0)
