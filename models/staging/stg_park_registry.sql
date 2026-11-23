with

landing_park_registry as (
    select
        park_id,
        company_start_year,
        game_year_origin,
        data_set,
        note,
        delivered_on,
        filename
    from {{ source('registry', 'park_registry') }}
),

final as (
    select
        park_id,
        cast(company_start_year as integer) as company_start_year,
        cast(game_year_origin as integer) as game_year_origin,
        data_set,
        note,
        cast(delivered_on as date) as delivered_on,
        filename as delivery_file
    from landing_park_registry
)

select
    park_id,
    company_start_year,
    game_year_origin,
    data_set,
    note,
    delivered_on,
    delivery_file
from final
