{#
    One row per ride occupancy per game day on the kept timeline. An
    occupancy is one stretch of a ride slot with the same identity; a new one
    starts when the slot is first read, when the build month, ride type, ride
    object or classification changes, or when total_customers falls. The
    counter rises are computed per reading, before the day's last reading is
    chosen, and then summed per day, so a dropped reading loses no rise.
#}
with

snapshots as (
    select
        park_id,
        session_id,
        seq,
        event_id,
        game_year,
        game_month,
        game_day,
        game_ticks_elapsed,
        ride_id,
        ride_name,
        classification,
        ride_type,
        ride_object,
        build_date_months_elapsed,
        status,
        age_months,
        excitement_hundredths,
        intensity_hundredths,
        nausea_hundredths,
        price_1_usd,
        price_2_usd,
        shop_item,
        shop_item_secondary,
        total_customers,
        total_profit_usd,
        downtime_pct,
        satisfaction_pct,
        queue_time_max_minutes
    from {{ ref("stg_ride_snapshot") }}
),

labeled as (
    select
        snapshots.*,
        lineage.session_started_at,
        {{ timeline_status("snapshots.seq", "lineage") }}
            as timeline_status
    from snapshots
    left join {{ ref("int_sessions__lineage") }} as lineage
        on snapshots.session_id = lineage.session_id
),

kept as (
    select *
    from labeled
    where timeline_status = 'kept'
),

with_previous as (
    select
        *,
        row_number() over reading_order as reading_number,
        lag(build_date_months_elapsed) over reading_order
            as prior_build_month,
        lag(ride_type) over reading_order as prior_ride_type,
        lag(ride_object) over reading_order as prior_ride_object,
        lag(classification) over reading_order as prior_classification,
        lag(total_customers) over reading_order as prior_total_customers
    from kept
    window reading_order as (
        partition by park_id, ride_id
        order by
            game_ticks_elapsed,
            session_started_at nulls first,
            session_id,
            seq
    )
),

boundaries as (
    select
        *,
        case
            when
                reading_number = 1
                or (
                    build_date_months_elapsed
                    is distinct from prior_build_month
                )
                or (ride_type is distinct from prior_ride_type)
                or (ride_object is distinct from prior_ride_object)
                or (classification is distinct from prior_classification)
                or total_customers < prior_total_customers
                then 1
            else 0
        end as is_new_occupancy
    from with_previous
),

numbered as (
    select
        *,
        -- this order must match the reading_order window in with_previous
        sum(is_new_occupancy) over (
            partition by park_id, ride_id
            order by
                game_ticks_elapsed,
                session_started_at nulls first,
                session_id,
                seq
            rows between unbounded preceding and current row
        ) as occupancy_number
    from boundaries
),

occupancies as (
    select
        *,
        min(game_ticks_elapsed) over (
            partition by park_id, ride_id, occupancy_number
        ) as first_seen_ticks
    from numbered
),

keyed_occupancies as (
    select
        *,
        park_id || '|' || ride_id || '|' || build_date_months_elapsed
        || '|' || first_seen_ticks as ride_key
    from occupancies
),

reading_changes as (
    select
        *,
        {{ counter_change("total_customers", ["ride_key"]) }}
            as reading_customers_increase,
        {{ counter_change("total_profit_usd", ["ride_key"]) }}
            as reading_profit_usd
    from keyed_occupancies
),

daily as (
    select
        *,
        sum(reading_customers_increase) over day_window as customers_increase,
        sum(reading_profit_usd) over day_window as profit_usd,
        max(queue_time_max_minutes) over day_window as day_queue_max_minutes,
        row_number() over (
            partition by
                park_id, ride_id, occupancy_number,
                game_year, game_month, game_day
            order by
                game_ticks_elapsed desc,
                session_started_at desc nulls last,
                session_id desc,
                seq desc
        ) as day_rank
    from reading_changes
    window day_window as (
        partition by
            park_id, ride_id, occupancy_number,
            game_year, game_month, game_day
    )
),

with_company_date as (
    select
        daily.ride_key,
        daily.park_id,
        daily.ride_id,
        daily.session_id,
        daily.seq,
        daily.event_id,
        daily.game_year,
        daily.game_month,
        daily.game_day,
        daily.game_ticks_elapsed,
        daily.first_seen_ticks,
        calendar.company_year,
        calendar.company_date,
        daily.ride_name,
        daily.classification,
        daily.ride_type,
        daily.ride_object,
        daily.build_date_months_elapsed,
        daily.status,
        daily.age_months as ride_age_months,
        daily.excitement_hundredths,
        daily.intensity_hundredths,
        daily.nausea_hundredths,
        daily.price_1_usd,
        daily.price_2_usd,
        daily.shop_item,
        daily.shop_item_secondary,
        daily.total_customers,
        daily.customers_increase,
        daily.total_profit_usd,
        daily.profit_usd,
        daily.downtime_pct,
        daily.satisfaction_pct,
        daily.day_queue_max_minutes
    from daily
    left join {{ ref("int_park_days__company_calendar") }} as calendar
        on
            daily.park_id = calendar.park_id
            and daily.game_year = calendar.game_year
            and daily.game_month = calendar.game_month
            and daily.game_day = calendar.game_day
    where daily.day_rank = 1
),

keyed as (
    select
        *,
        ride_key || '|' || game_year || '|' || game_month || '|' || game_day
            as ride_day_key,
        park_id || '|' || game_year || '|' || game_month || '|' || game_day
            as park_day_key,
        status = 'open' as is_open_day,
        case when classification = 'ride' then price_1_usd end
            as ride_price_listed_usd,
        case when classification = 'ride' then 100 - downtime_pct end
            as availability_from_downtime_pct,
        case when classification = 'ride' then day_queue_max_minutes end
            as longest_queue_seen_minutes,
        case when classification = 'ride' then satisfaction_pct end
            as guest_rating_pct
    from with_company_date
)

select
    ride_day_key,
    ride_key,
    park_day_key,
    park_id,
    ride_id,
    session_id,
    seq,
    event_id,
    game_year,
    game_month,
    game_day,
    game_ticks_elapsed,
    first_seen_ticks,
    company_year,
    company_date,
    ride_name,
    classification,
    ride_type,
    ride_object,
    build_date_months_elapsed,
    status,
    is_open_day,
    ride_age_months,
    excitement_hundredths,
    intensity_hundredths,
    nausea_hundredths,
    price_1_usd,
    price_2_usd,
    ride_price_listed_usd,
    shop_item,
    shop_item_secondary,
    total_customers,
    customers_increase,
    total_profit_usd,
    profit_usd,
    availability_from_downtime_pct,
    longest_queue_seen_minutes,
    guest_rating_pct
from keyed
