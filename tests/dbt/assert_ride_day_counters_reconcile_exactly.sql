{{ config(severity="error") }}

-- A returned row has a ride whose daily counter changes do not reconcile.
-- Known limit 1: a new occupancy first seen at a tick that two kept sessions
-- share takes the earlier session's reading at that tick into the new key,
-- so the test fails there even when the model is right.
-- Known limit 2: the profit comparison is skipped for any ride_key with a
-- null total_profit_usd on a kept reading.
with

snapshots as (
    select
        park_id,
        session_id,
        seq,
        ride_id,
        game_ticks_elapsed,
        total_customers,
        total_profit_usd
    from {{ ref("stg_ride_snapshot") }}
),

labeled as (
    select
        snapshots.*,
        {{ timeline_status("snapshots.seq", "lineage") }}
            as timeline_status
    from snapshots
    left join {{ ref("int_sessions__lineage") }} as lineage
        on snapshots.session_id = lineage.session_id
),

kept_readings as (
    select *
    from labeled
    where timeline_status = 'kept'
),

occupancy_starts as (
    select distinct
        park_id,
        ride_id,
        first_seen_ticks,
        ride_key
    from {{ ref("int_ride_days__kept") }}
),

ranked_occupancies as (
    select
        kept_readings.park_id,
        kept_readings.session_id,
        kept_readings.seq,
        kept_readings.ride_id,
        kept_readings.game_ticks_elapsed,
        kept_readings.total_customers,
        kept_readings.total_profit_usd,
        occupancy_starts.ride_key,
        row_number() over (
            partition by
                kept_readings.park_id,
                kept_readings.session_id,
                kept_readings.seq,
                kept_readings.ride_id
            order by occupancy_starts.first_seen_ticks desc
        ) as occupancy_rank
    from kept_readings
    inner join occupancy_starts
        on
            kept_readings.park_id = occupancy_starts.park_id
            and kept_readings.ride_id = occupancy_starts.ride_id
            and kept_readings.game_ticks_elapsed
            >= occupancy_starts.first_seen_ticks
),

keyed_readings as (
    select *
    from ranked_occupancies
    where occupancy_rank = 1
),

session_bounds as (
    select
        session_id,
        ride_key,
        min(seq) as least_seq,
        max(seq) as greatest_seq,
        bool_or(total_profit_usd is null) as has_null_profit
    from keyed_readings
    group by session_id, ride_key
),

session_changes as (
    select
        session_bounds.ride_key,
        session_bounds.has_null_profit,
        greatest_reading.total_customers
        - least_reading.total_customers as customers_change,
        greatest_reading.total_profit_usd
        - least_reading.total_profit_usd as profit_change
    from session_bounds
    inner join keyed_readings as least_reading
        on
            session_bounds.session_id = least_reading.session_id
            and session_bounds.ride_key = least_reading.ride_key
            and session_bounds.least_seq = least_reading.seq
    inner join keyed_readings as greatest_reading
        on
            session_bounds.session_id = greatest_reading.session_id
            and session_bounds.ride_key = greatest_reading.ride_key
            and session_bounds.greatest_seq = greatest_reading.seq
),

kept_by_ride as (
    select
        ride_key,
        sum(customers_change) as customers_change,
        sum(profit_change) as profit_change,
        bool_or(has_null_profit) as has_null_profit
    from session_changes
    group by ride_key
),

fact_by_ride as (
    select
        ride_key,
        coalesce(sum(customers_increase), 0) as customers_change,
        coalesce(sum(profit_usd), 0) as profit_change
    from {{ ref("fct_ride_day") }}
    group by ride_key
)

select coalesce(fact_by_ride.ride_key, kept_by_ride.ride_key) as ride_key
from fact_by_ride
full outer join kept_by_ride
    on fact_by_ride.ride_key = kept_by_ride.ride_key
where
    coalesce(fact_by_ride.customers_change, 0)
    is distinct from kept_by_ride.customers_change
    or (
        not coalesce(kept_by_ride.has_null_profit, false)
        and fact_by_ride.profit_change
        is distinct from kept_by_ride.profit_change
    )
