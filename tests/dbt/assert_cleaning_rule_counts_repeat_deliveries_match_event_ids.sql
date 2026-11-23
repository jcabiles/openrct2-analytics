{{ config(severity="error") }}

-- Returns each repeat-delivery count row where rows_excluded differs from the
-- stg_envelope deliveries of its event type minus their distinct event IDs, or
-- whose model matches no event type although the row saw deliveries
-- (rows_in above 0). An event type with no deliveries has no group here, so
-- its expected count is 0 and a model with no deliveries passes, as on a
-- zero-row build or a data set that never captured one type.
with

deliveries_by_type as (
    select
        event_type,
        count(*) - count(distinct event_id) as repeat_deliveries
    from {{ ref("stg_envelope") }}
    group by event_type
)

select
    counts.cleaning_rule_key,
    counts.model_name,
    counts.rows_excluded,
    coalesce(deliveries.repeat_deliveries, 0) as repeat_deliveries
from {{ ref("fct_cleaning_rule_count") }} as counts
left join deliveries_by_type as deliveries
    on counts.model_name = 'stg_' || deliveries.event_type
where
    counts.rule_name = 'repeat_delivery'
    and (
        (deliveries.event_type is null and counts.rows_in > 0)
        or counts.rows_excluded != coalesce(deliveries.repeat_deliveries, 0)
    )
