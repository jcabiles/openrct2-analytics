{#
    One row per park snapshot on the kept timeline, with the admissions rise
    assigned to the earlier kept reading. The last kept reading per session
    has no following reading and therefore a null admissions increase.
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
        cash_usd,
        guests_in_park,
        park_rating,
        total_admissions,
        weather,
        temperature_c
    from {{ ref("stg_park_snapshot") }}
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

kept as (
    select *
    from labeled
    where timeline_status = 'kept'
),

with_admissions as (
    select
        *,
        {{ counter_change("total_admissions", ["park_id"]) }}
            as admissions_increase
    from kept
),

with_company_date as (
    select
        with_admissions.park_id,
        with_admissions.session_id,
        with_admissions.seq,
        with_admissions.event_id,
        with_admissions.game_year,
        with_admissions.game_month,
        with_admissions.game_day,
        with_admissions.game_ticks_elapsed,
        calendar.company_year,
        calendar.company_date,
        with_admissions.cash_usd,
        with_admissions.guests_in_park,
        with_admissions.park_rating,
        with_admissions.total_admissions,
        with_admissions.admissions_increase,
        with_admissions.weather,
        with_admissions.temperature_c
    from with_admissions
    left join {{ ref("int_park_days__company_calendar") }} as calendar
        on
            with_admissions.park_id = calendar.park_id
            and with_admissions.game_year = calendar.game_year
            and with_admissions.game_month = calendar.game_month
            and with_admissions.game_day = calendar.game_day
),

keyed as (
    select
        *,
        park_id || '|' || game_year || '|' || game_month || '|' || game_day
            as park_day_key
    from with_company_date
)

select
    park_day_key,
    park_id,
    session_id,
    seq,
    event_id,
    game_year,
    game_month,
    game_day,
    game_ticks_elapsed,
    company_year,
    company_date,
    cash_usd,
    guests_in_park,
    park_rating,
    total_admissions,
    admissions_increase,
    weather,
    temperature_c
from keyed
