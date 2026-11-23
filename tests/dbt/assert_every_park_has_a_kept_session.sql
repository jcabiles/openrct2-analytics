-- A row means a park has no kept-path session, or a session is its own parent.
with parks_without_kept_sessions as (
    select distinct
        envelope.park_id,
        cast(null as varchar) as session_id,
        'park has no kept-path session' as reason
    from {{ ref("stg_envelope") }} as envelope
    where not exists (
        select 1
        from {{ ref("int_sessions__lineage") }} as lineage
        where
            lineage.park_id = envelope.park_id
            and lineage.is_on_kept_path
    )
),

self_parent_sessions as (
    select
        park_id,
        session_id,
        'session is its own parent' as reason
    from {{ ref("int_sessions__lineage") }}
    where parent_session_id = session_id
)

select
    park_id,
    session_id,
    reason
from parks_without_kept_sessions

union all

select
    park_id,
    session_id,
    reason
from self_parent_sessions
