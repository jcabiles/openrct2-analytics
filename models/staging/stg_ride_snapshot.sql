with

landing_ride_snapshot as (
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
        ride_id,
        ride_name,
        ride_type,
        ride_object,
        classification,
        status,
        excitement_hundredths,
        intensity_hundredths,
        nausea_hundredths,
        price_1_tenths,
        price_2_tenths,
        shop_item,
        shop_item_secondary,
        total_customers,
        build_date_months_elapsed,
        age_months,
        running_cost_per_fortnight_tenths,
        total_profit_tenths,
        income_per_game_hour_tenths,
        profit_per_game_hour_tenths,
        value_tenths,
        reliability_pct,
        downtime_pct,
        satisfaction_pct,
        guests_on_ride,
        station_count,
        queue_time_max_minutes
    from {{ source('landing', 'ride_snapshot') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by event_id
            order by received_at, _raw_file, _raw_line
        ) as delivery_rank
    from landing_ride_snapshot
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
        ride_id,
        ride_name,
        ride_type,
        ride_object,
        classification,
        status,
        nullif(excitement_hundredths, -1) as excitement_hundredths,
        nullif(intensity_hundredths, -1) as intensity_hundredths,
        nullif(nausea_hundredths, -1) as nausea_hundredths,
        {{ tenths_to_usd('price_1_tenths') }} as price_1_usd,
        {{ tenths_to_usd('price_2_tenths') }} as price_2_usd,
        nullif(shop_item, 255) as shop_item,
        nullif(shop_item_secondary, 255) as shop_item_secondary,
        total_customers,
        build_date_months_elapsed,
        age_months,
        {{ tenths_to_usd('running_cost_per_fortnight_tenths') }}
            as running_cost_per_fortnight_usd,
        {{ tenths_to_usd('total_profit_tenths') }} as total_profit_usd,
        {{ tenths_to_usd('income_per_game_hour_tenths') }}
            as income_per_game_hour_usd,
        {{ tenths_to_usd('profit_per_game_hour_tenths') }}
            as profit_per_game_hour_usd,
        value_tenths,
        reliability_pct,
        downtime_pct,
        nullif(satisfaction_pct, 1275) as satisfaction_pct,
        guests_on_ride,
        station_count,
        queue_time_max_minutes
    from ranked
    where delivery_rank = 1
)

select * from final
