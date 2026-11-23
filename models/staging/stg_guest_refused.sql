with

landing_guest_refused as (
    select
        schema_version,
        event_type,
        plugin_version,
        park_id,
        session_id,
        seq,
        event_id,
        game_year,
        game_month,
        game_day,
        game_ticks_elapsed,
        emitted_at,
        received_at,
        _raw_file,
        _raw_line,
        guest_key,
        guest_id,
        thought_type,
        ride_id
    from {{ source('landing', 'guest_refused') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by event_id
            order by received_at, _raw_file, _raw_line
        ) as delivery_rank
    from landing_guest_refused
),

final as (
    select
        schema_version,
        event_type,
        plugin_version,
        park_id,
        session_id,
        seq,
        event_id,
        game_year,
        game_month,
        game_day,
        game_ticks_elapsed,
        emitted_at,
        received_at,
        _raw_file,
        _raw_line,
        guest_key,
        guest_id,
        thought_type,
        ride_id
    from ranked
    where delivery_rank = 1
)

select * from final
