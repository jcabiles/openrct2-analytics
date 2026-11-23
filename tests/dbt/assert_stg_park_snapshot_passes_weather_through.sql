-- Returns a row (a failure) for each park snapshot whose weather or
-- temperature differs from the source, nulls included. A column missing from
-- stg_park_snapshot makes the query fail, so a dropped column cannot pass.
select s.event_id
from {{ ref("stg_park_snapshot") }} as s
inner join
    {{ source("landing", "park_snapshot") }} as r
    on
        s.event_id = r.event_id
        and s._raw_file = r._raw_file
        and s._raw_line = r._raw_line
where
    s.weather is distinct from r.weather
    or s.temperature_c is distinct from r.temperature_c
