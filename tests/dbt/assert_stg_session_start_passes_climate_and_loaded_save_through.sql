-- Returns a row (a failure) for each session_start whose climate or loaded-save
-- fields differ from the source, nulls included. A column missing from
-- stg_session_start makes the query fail, so a dropped column cannot pass.
select s.event_id
from {{ ref("stg_session_start") }} as s
inner join
    {{ source("landing", "session_start") }} as r
    on
        s.event_id = r.event_id
        and s._raw_file = r._raw_file
        and s._raw_line = r._raw_line
where
    s.climate is distinct from r.climate
    or s.loaded_save_id is distinct from r.loaded_save_id
    or s.loaded_save_session_id is distinct from r.loaded_save_session_id
    or s.loaded_save_seq_floor is distinct from r.loaded_save_seq_floor
    or s.loaded_save_lines_waiting is distinct from r.loaded_save_lines_waiting
