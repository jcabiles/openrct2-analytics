with

landing_session_start as (
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
        api_version,
        park_name,
        scenario_name,
        headless,
        game_speed,
        climate,
        loaded_save_id,
        loaded_save_session_id,
        loaded_save_seq_floor,
        loaded_save_lines_waiting
    from {{ source('landing', 'session_start') }}
),

session_play_mode as (
    select
        session_id,
        play_mode
    from {{ ref('stg_session_play_mode') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by event_id
            order by received_at, _raw_file, _raw_line
        ) as delivery_rank
    from landing_session_start
),

final as (
    select
        ranked.schema_version,
        ranked.event_type,
        ranked.plugin_version,
        ranked.park_id,
        ranked.session_id,
        ranked.seq,
        ranked.event_id,
        ranked.game_year,
        ranked.game_month,
        ranked.game_day,
        ranked.game_ticks_elapsed,
        ranked.emitted_at,
        ranked.received_at,
        ranked._raw_file,
        ranked._raw_line,
        ranked.api_version,
        ranked.park_name,
        ranked.scenario_name,
        ranked.headless,
        ranked.game_speed,
        ranked.climate,
        ranked.loaded_save_id,
        ranked.loaded_save_session_id,
        ranked.loaded_save_seq_floor,
        ranked.loaded_save_lines_waiting,
        coalesce(session_play_mode.play_mode, 'managed') as play_mode
    from ranked
    left join session_play_mode
        on ranked.session_id = session_play_mode.session_id
    where ranked.delivery_rank = 1
)

select * from final
