with

landing_park_snapshot as (
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
        cash_tenths,
        guests_in_park,
        park_rating,
        total_admissions,
        weather,
        temperature_c
    from {{ source('landing', 'park_snapshot') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by event_id
            order by received_at, _raw_file, _raw_line
        ) as delivery_rank
    from landing_park_snapshot
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
        {{ tenths_to_usd('cash_tenths') }} as cash_usd,
        guests_in_park,
        park_rating,
        total_admissions,
        weather,
        temperature_c
    from ranked
    where delivery_rank = 1
)

select * from final
