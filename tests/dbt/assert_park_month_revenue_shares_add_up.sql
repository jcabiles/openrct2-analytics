-- Returns a month when: operating revenue is non-zero and the four revenue
-- shares do not add to 100 within rounding (0.04), or any of them is null;
-- or operating revenue is null or 0 and any share is not null.
{{ config(severity='error') }}

select
    park_month_key,
    operating_revenue,
    ride_revenue_share_pct,
    food_drink_revenue_share_pct,
    merchandise_revenue_share_pct,
    entrance_revenue_share_pct
from {{ ref('obt_park_month') }}
where
    (
        coalesce(operating_revenue, 0) != 0
        and abs(
            ride_revenue_share_pct
            + food_drink_revenue_share_pct
            + merchandise_revenue_share_pct
            + entrance_revenue_share_pct
            - 100
        ) > 0.04
    )
    or (
        coalesce(operating_revenue, 0) != 0
        and (
            ride_revenue_share_pct is null
            or food_drink_revenue_share_pct is null
            or merchandise_revenue_share_pct is null
            or entrance_revenue_share_pct is null
        )
    )
    or (
        coalesce(operating_revenue, 0) = 0
        and (
            ride_revenue_share_pct is not null
            or food_drink_revenue_share_pct is not null
            or merchandise_revenue_share_pct is not null
            or entrance_revenue_share_pct is not null
        )
    )
