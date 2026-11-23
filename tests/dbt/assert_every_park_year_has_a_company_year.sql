{{ config(severity="error") }}

-- Returns a row (a failure) for each landed park-year the registry cannot map
-- to a company year: no registry row, a game year before the origin, or a game
-- month outside 0 to 7. The severity is error on every target.
select
    park_id,
    game_year,
    mapping_status
from {{ ref("int_park_years__company_year") }}
where mapping_status != 'mapped'
