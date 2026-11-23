-- Returns a row (a failure) for each current registry row whose data_set is
-- not the name of the target being built (one data set per park, ADR 0013).
-- Only the rehearsal and company targets are checked; other targets return no
-- rows, so a dev or ci build keeps the mixed sample.
select
    park_id,
    data_set,
    delivery_file
from {{ ref("int_park_registry__current") }}
where
    '{{ target.name }}' in ('rehearsal', 'company')
    and data_set != '{{ target.name }}'
