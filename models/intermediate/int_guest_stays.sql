{#
    One row per kept guest arrival, joined to its exit by session_id and
    guest_key when the exit exists. An exit with no arrival (a guest
    seeded at session start) gives no row. Day number = (game_year - 1)
    * 245 + days before the month + game_day; the year origin cancels in
    the difference. Month lengths: docs/architecture/openrct2-facts.md.
#}
with

month_offsets as (
    select
        month_offset.game_month,
        month_offset.days_before_month
    from (
        values
        (0, 0),
        (1, 31),
        (2, 61),
        (3, 92),
        (4, 122),
        (5, 153),
        (6, 184),
        (7, 214)
    ) as month_offset (game_month, days_before_month)
),

arrivals as (
    select
        arrived.park_id,
        arrived.session_id,
        arrived.guest_key,
        arrived.game_year,
        arrived.game_month,
        arrived.game_day,
        arrived.generated_at_ticks,
        arrived.in_cohort,
        month_offsets.days_before_month
    from {{ ref("stg_guest_arrived") }} as arrived
    left join month_offsets
        on arrived.game_month = month_offsets.game_month
),

exits as (
    select
        left_event.session_id,
        left_event.guest_key,
        left_event.game_year,
        left_event.game_month,
        left_event.game_day,
        left_event.exit_reason,
        left_event.entered_park,
        month_offsets.days_before_month
    from {{ ref("stg_guest_left") }} as left_event
    left join month_offsets
        on left_event.game_month = month_offsets.game_month
),

arrivals_numbered as (
    select
        *,
        (game_year - 1) * 245 + days_before_month + game_day as day_number
    from arrivals
),

exits_numbered as (
    select
        *,
        (game_year - 1) * 245 + days_before_month + game_day as day_number
    from exits
)

select
    arrivals_numbered.park_id,
    arrivals_numbered.session_id,
    arrivals_numbered.guest_key,
    arrivals_numbered.game_year as arrival_game_year,
    arrivals_numbered.game_month as arrival_game_month,
    arrivals_numbered.game_day as arrival_game_day,
    arrivals_numbered.generated_at_ticks as arrival_game_ticks,
    arrivals_numbered.in_cohort,
    exits_numbered.game_year as exit_game_year,
    exits_numbered.game_month as exit_game_month,
    exits_numbered.game_day as exit_game_day,
    exits_numbered.exit_reason,
    exits_numbered.entered_park,
    exits_numbered.guest_key is null as is_open,
    exits_numbered.day_number
    - arrivals_numbered.day_number as stay_game_days
from arrivals_numbered
left join exits_numbered
    on
        arrivals_numbered.session_id = exits_numbered.session_id
        and arrivals_numbered.guest_key = exits_numbered.guest_key
