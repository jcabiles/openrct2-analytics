with

landing_guest_arrived as (
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
        generated_at_ticks,
        in_cohort,
        guest_cash_tenths
    from {{ source('landing', 'guest_arrived') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by event_id
            order by received_at, _raw_file, _raw_line
        ) as delivery_rank
    from landing_guest_arrived
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
        generated_at_ticks,
        in_cohort,
        {{ tenths_to_usd('guest_cash_tenths') }} as guest_cash_usd
    from ranked
    where delivery_rank = 1
)

select * from final
