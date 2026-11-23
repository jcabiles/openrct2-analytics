-- Fails on each landed envelope date whose game_day is past the length
-- of its game_month (31, 30, 31, 30, 31, 31, 30, 31 for months 0 to 7,
-- docs/architecture/openrct2-facts.md). A month outside 0 to 7 gives no
-- row here; the company-year model flags it.
select
    park_id,
    session_id,
    game_year,
    game_month,
    game_day
from {{ ref("stg_envelope") }}
where
    game_day > case game_month
        when 0 then 31
        when 1 then 30
        when 2 then 31
        when 3 then 30
        when 4 then 31
        when 5 then 31
        when 6 then 30
        when 7 then 31
    end
