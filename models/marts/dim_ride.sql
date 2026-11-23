{#
    Answers which ride, stall, or facility occupies each ride key, with its
    latest kept descriptive values and the span of kept company dates. Grain:
    one row per ride_key. Key: ride_key. Type 1 replacement keeps the latest
    descriptive values. Unit: no unit; clock: game ticks for descriptive
    values (the latest kept reading), company date for the date span.
#}
with

ranked as (
    select
        ride_key,
        park_id,
        ride_id,
        build_date_months_elapsed,
        first_seen_ticks,
        ride_name,
        classification,
        ride_type,
        ride_object,
        shop_item,
        shop_item_secondary,
        game_ticks_elapsed,
        session_id,
        row_number() over (
            partition by ride_key
            order by game_ticks_elapsed desc, session_id desc
        ) as ride_rank
    from {{ ref("int_ride_days__kept") }}
),

spans as (
    select
        ride_key,
        min(company_date) as first_company_date,
        max(company_date) as last_company_date
    from {{ ref("int_ride_days__kept") }}
    group by ride_key
),

final as (
    select
        ranked.ride_key,
        ranked.park_id,
        ranked.ride_id,
        ranked.build_date_months_elapsed,
        ranked.first_seen_ticks,
        ranked.ride_name,
        ranked.classification,
        ranked.ride_type,
        ranked.ride_object,
        ranked.shop_item,
        ranked.shop_item_secondary,
        spans.first_company_date,
        spans.last_company_date
    from ranked
    inner join spans
        on ranked.ride_key = spans.ride_key
    where ranked.ride_rank = 1
)

select
    ride_key,
    park_id,
    ride_id,
    build_date_months_elapsed,
    first_seen_ticks,
    ride_name,
    classification,
    ride_type,
    ride_object,
    shop_item,
    shop_item_secondary,
    first_company_date,
    last_company_date
from final
