-- A row means a session overlaps another session on its park's kept timeline.
select
    park_id,
    session_id,
    overlaps_kept_session_id
from {{ ref("int_sessions__lineage") }}
where overlaps_kept_session_id is not null
