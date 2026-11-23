{#
    One row per cleaning rule per model that applies it. Each count is a
    scalar subquery, so every pair keeps its row, with zero counts, on an
    empty build. Rows that a rule removes are counted as the difference between
    the layer before and the layer after, except the statement rule and the
    guest-exit rule, which are counted on their own so that the add-up test
    checks them. The placeholder counts read the landing data, because staging
    has already turned each placeholder into a null. The mart compares no
    save cut and reads no money column.
#}
with

envelope as (
    select event_type
    from {{ ref("stg_envelope") }}
),

landing_ride as (
    select
        event_id,
        _raw_file,
        _raw_line,
        excitement_hundredths,
        intensity_hundredths,
        nausea_hundredths,
        shop_item,
        shop_item_secondary,
        satisfaction_pct
    from {{ source("landing", "ride_snapshot") }}
),

landing_guest as (
    select
        event_id,
        _raw_file,
        _raw_line,
        thought_item
    from {{ source("landing", "guest_snapshot") }}
),

repeat_read as (
    select
        'stg_finance_month' as model_name,
        (
            select count(*) from envelope
            where event_type = 'finance_month'
        ) as rows_in,
        (select count(*) from {{ ref("stg_finance_month") }}) as rows_kept
    union all
    select
        'stg_game_action' as model_name,
        (
            select count(*) from envelope
            where event_type = 'game_action'
        ) as rows_in,
        (select count(*) from {{ ref("stg_game_action") }}) as rows_kept
    union all
    select
        'stg_guest_arrived' as model_name,
        (
            select count(*) from envelope
            where event_type = 'guest_arrived'
        ) as rows_in,
        (select count(*) from {{ ref("stg_guest_arrived") }}) as rows_kept
    union all
    select
        'stg_guest_boarded' as model_name,
        (
            select count(*) from envelope
            where event_type = 'guest_boarded'
        ) as rows_in,
        (select count(*) from {{ ref("stg_guest_boarded") }}) as rows_kept
    union all
    select
        'stg_guest_left' as model_name,
        (
            select count(*) from envelope
            where event_type = 'guest_left'
        ) as rows_in,
        (select count(*) from {{ ref("stg_guest_left") }}) as rows_kept
    union all
    select
        'stg_guest_refused' as model_name,
        (
            select count(*) from envelope
            where event_type = 'guest_refused'
        ) as rows_in,
        (select count(*) from {{ ref("stg_guest_refused") }}) as rows_kept
    union all
    select
        'stg_guest_snapshot' as model_name,
        (
            select count(*) from envelope
            where event_type = 'guest_snapshot'
        ) as rows_in,
        (select count(*) from {{ ref("stg_guest_snapshot") }}) as rows_kept
    union all
    select
        'stg_park_snapshot' as model_name,
        (
            select count(*) from envelope
            where event_type = 'park_snapshot'
        ) as rows_in,
        (select count(*) from {{ ref("stg_park_snapshot") }}) as rows_kept
    union all
    select
        'stg_ride_snapshot' as model_name,
        (
            select count(*) from envelope
            where event_type = 'ride_snapshot'
        ) as rows_in,
        (select count(*) from {{ ref("stg_ride_snapshot") }}) as rows_kept
    union all
    select
        'stg_save_written' as model_name,
        (
            select count(*) from envelope
            where event_type = 'save_written'
        ) as rows_in,
        (select count(*) from {{ ref("stg_save_written") }}) as rows_kept
    union all
    select
        'stg_session_start' as model_name,
        (
            select count(*) from envelope
            where event_type = 'session_start'
        ) as rows_in,
        (select count(*) from {{ ref("stg_session_start") }}) as rows_kept
),

layer_read as (
    select
        'int_park_days__kept' as model_name,
        (select count(*) from {{ ref("stg_park_snapshot") }}) as rows_in,
        (select count(*) from {{ ref("int_park_days__kept") }}) as rows_kept
    union all
    select
        'int_ride_days__kept' as model_name,
        (select count(*) from {{ ref("stg_ride_snapshot") }}) as rows_in,
        (select count(*) from {{ ref("int_ride_days__kept") }}) as rows_kept
),

statement_read as (
    select
        (select count(*) from {{ ref("int_statements__labeled") }})
            as rows_in,
        (select count(*) from {{ ref("fct_park_month") }}) as rows_kept,
        (
            select count(*)
            from {{ ref("int_statements__labeled") }}
            where timeline_status = 'abandoned'
        ) as rows_excluded
),

last_reading_read as (
    select
        'int_park_days__kept' as model_name,
        (select count(*) from {{ ref("int_park_days__kept") }}) as rows_in,
        (
            select count(*)
            from {{ ref("int_park_days__kept") }}
            where admissions_increase is null
        ) as rows_changed
    union all
    select
        'int_ride_days__kept' as model_name,
        (select count(*) from {{ ref("int_ride_days__kept") }}) as rows_in,
        (
            select count(*)
            from {{ ref("int_ride_days__kept") }} as rd
            where
                (rd.customers_increase is null or rd.profit_usd is null)
                and not exists (
                    select 1
                    from {{ ref("int_ride_days__kept") }} as later
                    where
                        later.ride_key = rd.ride_key
                        and later.session_id = rd.session_id
                        and later.game_ticks_elapsed > rd.game_ticks_elapsed
                )
        ) as rows_changed
),

placeholder_read as (
    select
        'placeholder_null_minus_1' as rule_name,
        'stg_ride_snapshot' as model_name,
        (select count(*) from {{ ref("stg_ride_snapshot") }}) as rows_in,
        (
            select count(*)
            from {{ ref("stg_ride_snapshot") }} as staged
            inner join landing_ride as landed
                on
                    staged.event_id = landed.event_id
                    and staged._raw_file = landed._raw_file
                    and staged._raw_line = landed._raw_line
            where
                landed.excitement_hundredths = -1
                or landed.intensity_hundredths = -1
                or landed.nausea_hundredths = -1
        ) as rows_changed
    union all
    select
        'placeholder_null_255' as rule_name,
        'stg_ride_snapshot' as model_name,
        (select count(*) from {{ ref("stg_ride_snapshot") }}) as rows_in,
        (
            select count(*)
            from {{ ref("stg_ride_snapshot") }} as staged
            inner join landing_ride as landed
                on
                    staged.event_id = landed.event_id
                    and staged._raw_file = landed._raw_file
                    and staged._raw_line = landed._raw_line
            where landed.shop_item = 255 or landed.shop_item_secondary = 255
        ) as rows_changed
    union all
    select
        'placeholder_null_1275' as rule_name,
        'stg_ride_snapshot' as model_name,
        (select count(*) from {{ ref("stg_ride_snapshot") }}) as rows_in,
        (
            select count(*)
            from {{ ref("stg_ride_snapshot") }} as staged
            inner join landing_ride as landed
                on
                    staged.event_id = landed.event_id
                    and staged._raw_file = landed._raw_file
                    and staged._raw_line = landed._raw_line
            where landed.satisfaction_pct = 1275
        ) as rows_changed
    union all
    select
        'placeholder_null_65535' as rule_name,
        'stg_guest_snapshot' as model_name,
        (select count(*) from {{ ref("stg_guest_snapshot") }}) as rows_in,
        (
            select count(*)
            from {{ ref("stg_guest_snapshot") }} as staged
            inner join landing_guest as landed
                on
                    staged.event_id = landed.event_id
                    and staged._raw_file = landed._raw_file
                    and staged._raw_line = landed._raw_line
            where landed.thought_item = 65535
        ) as rows_changed
),

exit_read as (
    select
        (select count(*) from {{ ref("stg_guest_left") }}) as rows_in,
        (
            select count(*)
            from {{ ref("int_guest_stays") }}
            where not is_open
        ) as rows_kept,
        (
            select count(*)
            from {{ ref("stg_guest_left") }} as exits
            where not exists (
                select 1
                from {{ ref("stg_guest_arrived") }} as arrivals
                where
                    arrivals.session_id = exits.session_id
                    and arrivals.guest_key = exits.guest_key
            )
        ) as rows_excluded
),

rules as (
    select
        'repeat_delivery' as rule_name,
        model_name,
        'source' as cause,
        rows_in,
        rows_kept,
        rows_in - rows_kept as rows_excluded,
        0 as rows_changed,
        'A second delivery of one event is dropped and the first is kept, '
        || 'so the game or the transport sending an event twice does not '
        || 'count twice. This model keeps one row per event ID of its '
        || 'event type.' as reason,
        'repeat_delivery_payload_differs; '
        || 'assert_stg_envelope_keeps_every_delivery; ADR 0006' as guarded_by
    from repeat_read
    union all
    select
        'abandoned_branch' as rule_name,
        model_name,
        'transform' as cause,
        rows_in,
        rows_kept,
        rows_in - rows_kept as rows_excluded,
        0 as rows_changed,
        case
            when model_name = 'int_park_days__kept'
                then
                    'Park readings on an abandoned save branch are left out. '
                    || 'The count reflects the player''s reload plus the '
                    || 'lineage rule; on the committed sample these are each '
                    || 'session''s readings after its last save.'
            else
                'Ride readings on an abandoned save branch are left out, '
                || 'which reflects the player''s reload plus the lineage '
                || 'rule; on the sample these are each session''s readings '
                || 'after its last save. Any readings collapsed to one per '
                || 'ride per game day also count here; the sample has none.'
        end as reason,
        'ADR 0024' as guarded_by
    from layer_read
    union all
    select
        'abandoned_branch' as rule_name,
        'fct_park_month' as model_name,
        'transform' as cause,
        rows_in,
        rows_kept,
        rows_excluded,
        0 as rows_changed,
        'Monthly statements on an abandoned save branch are left out. The '
        || 'count reflects the player''s reload plus the lineage rule; the '
        || 'committed sample has no abandoned statement.' as reason,
        'ADR 0024' as guarded_by
    from statement_read
    union all
    select
        'last_reading_null' as rule_name,
        model_name,
        'transform' as cause,
        rows_in,
        rows_in as rows_kept,
        0 as rows_excluded,
        rows_changed,
        case
            when model_name = 'int_park_days__kept'
                then
                    'Each session''s last kept park reading has no next '
                    || 'reading, so its change in admissions is unknown and '
                    || 'is set to null.'
            else
                'A ride day''s change in customers or profit is null when '
                || 'no next reading exists: after a session''s last kept '
                || 'reading and where a ride occupancy ends. A ride day is '
                || 'counted only when no later kept reading exists for its '
                || 'ride and session, so a profit the game itself sent as '
                || 'null is not counted. A same-day collapse can hide a '
                || 'session-end null inside a day sum.'
        end as reason,
        'assert_counter_change_stays_within_one_session; '
        || 'ADR 0024 decision 7' as guarded_by
    from last_reading_read
    union all
    select
        rule_name,
        model_name,
        'source' as cause,
        rows_in,
        rows_in as rows_kept,
        0 as rows_excluded,
        rows_changed,
        case rule_name
            when 'placeholder_null_minus_1'
                then
                    'The game sends -1 in a ride rating to mean no reading, '
                    || 'so staging sets it to null.'
            when 'placeholder_null_255'
                then
                    'The game sends 255 in a ride item column to mean no '
                    || 'reading, so staging sets it to null.'
            when 'placeholder_null_1275'
                then
                    'The game sends 1275 in a ride satisfaction to mean no '
                    || 'reading, so staging sets it to null; the sample '
                    || 'never holds it.'
            else
                'The game sends 65535 in a guest thought item to mean no '
                || 'reading, so staging sets it to null.'
        end as reason,
        case rule_name
            when 'placeholder_null_65535' then 'ADR 0028'
            else
                'stg_ride_snapshot_nulls_each_placeholder_only_in_'
                || 'its_own_columns'
        end as guarded_by
    from placeholder_read
    union all
    select
        'exit_without_arrival' as rule_name,
        'int_guest_stays' as model_name,
        'source' as cause,
        rows_in,
        rows_kept,
        rows_excluded,
        0 as rows_changed,
        'A guest exit with no arrival in the same session is not a stay. A '
        || 'guest seeded at session start has an exit but no arrival.'
            as reason,
        'assert_guest_exit_without_arrival_was_seeded; ADR 0029'
            as guarded_by
    from exit_read
)

select
    cast(rule_name || '|' || model_name as varchar) as cleaning_rule_key,
    cast(rule_name as varchar) as rule_name,
    cast(model_name as varchar) as model_name,
    cast(cause as varchar) as cause,
    cast(rows_in as bigint) as rows_in,
    cast(rows_kept as bigint) as rows_kept,
    cast(rows_excluded as bigint) as rows_excluded,
    cast(rows_changed as bigint) as rows_changed,
    cast(reason as varchar) as reason,
    cast(guarded_by as varchar) as guarded_by
from rules
