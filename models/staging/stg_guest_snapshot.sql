with

landing_guest_snapshot as (
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
        happiness,
        hunger,
        thirst,
        nausea,
        energy,
        guest_cash_tenths,
        items_carried,
        thought_type,
        thought_item
    from {{ source('landing', 'guest_snapshot') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by event_id
            order by received_at, _raw_file, _raw_line
        ) as delivery_rank
    from landing_guest_snapshot
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
        happiness,
        hunger,
        thirst,
        nausea,
        energy,
        {{ tenths_to_usd('guest_cash_tenths') }} as guest_cash_usd,
        items_carried,
        thought_type,
        nullif(thought_item, 65535) as thought_item
    from ranked
    where delivery_rank = 1
)

select * from final
