-- Returns a month when: entrance revenue per visit is negative; or it is
-- not null while visits are null or 0; or visits are above 0 and entrance
-- revenue is not null but the per-visit figure is null.
{{ config(severity='error') }}

select
    park_month_key,
    guest_visits,
    entrance_revenue,
    entrance_revenue_per_visit
from {{ ref('obt_park_month') }}
where
    entrance_revenue_per_visit < 0
    or (
        entrance_revenue_per_visit is not null
        and coalesce(guest_visits, 0) = 0
    )
    or (
        coalesce(guest_visits, 0) > 0
        and entrance_revenue is not null
        and entrance_revenue_per_visit is null
    )
