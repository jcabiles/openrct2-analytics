with

landing_game_action as (
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
        hook,
        action,
        action_label,
        args_flags,
        is_client_only,
        player,
        type,
        args_json,
        args_ride,
        args_ride_type,
        args_ride_object,
        args_price_tenths,
        args_x,
        args_y,
        args_z,
        result_error,
        result_cost_tenths,
        result_ride,
        action_at_ticks,
        action_game_year,
        action_game_month,
        action_game_day
    from {{ source('landing', 'game_action') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by event_id
            order by received_at, _raw_file, _raw_line
        ) as delivery_rank
    from landing_game_action
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
        hook,
        action,
        action_label,
        args_flags,
        is_client_only,
        player,
        type,
        args_json,
        args_ride,
        args_ride_type,
        args_ride_object,
        {{ tenths_to_usd('args_price_tenths') }} as args_price_usd,
        args_x,
        args_y,
        args_z,
        result_error,
        {{ tenths_to_usd('result_cost_tenths') }} as result_cost_usd,
        result_ride,
        action_at_ticks,
        action_game_year,
        action_game_month,
        action_game_day
    from ranked
    where delivery_rank = 1
)

select * from final
