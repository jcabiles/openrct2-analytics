-- Warns about each feed file whose name is not
-- park_registry_<YYYY-MM-DD>_<NN>.csv. The history model leaves such a file
-- out, so its rows are missing there; the warning names the file.
{{ config(severity="warn") }}

select distinct s.delivery_file
from {{ ref("stg_park_registry") }} as s
left join {{ ref("int_park_registry__history") }} as h
    on s.delivery_file = h.delivery_file
where h.delivery_file is null
