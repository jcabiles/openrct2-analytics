{#
    Answers which game item codes appear on kept ride-days. Grain: one row per
    distinct non-null item code; key: shop_item.
#}
with

codes as (
    select shop_item
    from {{ ref("int_ride_days__kept") }}

    union

    select shop_item_secondary as shop_item
    from {{ ref("int_ride_days__kept") }}
),

final as (
    select shop_item
    from codes
    where shop_item is not null
)

select shop_item
from final
