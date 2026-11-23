with

landing_guest_boarded as (
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
        guest_id,
        guest_key,
        ride_id,
        detected_at_ticks,
        ride_price_listed_tenths,
        happiness,
        min_intensity,
        max_intensity,
        nausea_tolerance,
        guest_cash_tenths
    from {{ source('landing', 'guest_boarded') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by event_id
            order by received_at, _raw_file, _raw_line
        ) as delivery_rank
    from landing_guest_boarded
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
        guest_id,
        guest_key,
        ride_id,
        detected_at_ticks,
        {{ tenths_to_usd('ride_price_listed_tenths') }}
            as ride_price_listed_usd,
        happiness,
        min_intensity,
        max_intensity,
        nausea_tolerance,
        {{ tenths_to_usd('guest_cash_tenths') }} as guest_cash_usd
    from ranked
    where delivery_rank = 1
)

select * from final
