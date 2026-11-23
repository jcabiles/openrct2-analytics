{#
    One row per park and game year found in landed envelopes or monthly
    statements, mapped to a company year by the park's current registry row.
    Years without a registry mapping remain visible with a null company year.
#}
with

landed_years as (
    select distinct
        park_id,
        game_year
    from {{ ref("stg_envelope") }}
),

statement_years as (
    select distinct
        park_id,
        statement_year as game_year
    from {{ ref("stg_finance_month") }}
),

park_years as (
    select
        park_id,
        game_year
    from landed_years

    union

    select
        park_id,
        game_year
    from statement_years
),

registered as (
    select
        park_years.park_id,
        park_years.game_year,
        registry.data_set,
        registry.company_start_year,
        registry.game_year_origin,
        case
            when registry.park_id is null then 'unregistered'
            when park_years.game_year < registry.game_year_origin
                then 'before_origin'
            else 'mapped'
        end as mapping_status
    from park_years
    left join {{ ref("int_park_registry__current") }} as registry
        on park_years.park_id = registry.park_id
),

final as (
    select
        park_id,
        game_year,
        data_set,
        company_start_year,
        game_year_origin,
        mapping_status,
        park_id || '|' || cast(game_year as varchar) as park_year_key,
        case
            when mapping_status = 'mapped'
                then company_start_year + (game_year - game_year_origin)
        end as company_year
    from registered
)

select
    park_year_key,
    park_id,
    game_year,
    data_set,
    company_start_year,
    game_year_origin,
    company_year,
    mapping_status
from final
