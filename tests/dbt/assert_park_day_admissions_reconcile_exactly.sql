{{ config(severity="error") }}

-- Returns each park-session whose summed daily admissions rise does not match
-- the change between its first and last kept cumulative admissions readings.
with

admissions_by_session as (
    select
        park_id,
        session_id,
        coalesce(sum(admissions_increase), 0) as summed_admissions_increase
    from {{ ref("fct_park_day") }}
    group by park_id, session_id
),

kept_bounds as (
    select
        park_id,
        session_id,
        min(seq) as least_seq,
        max(seq) as greatest_seq
    from {{ ref("int_park_days__kept") }}
    group by park_id, session_id
),

kept_change_by_session as (
    select
        kept_bounds.park_id,
        kept_bounds.session_id,
        greatest_reading.total_admissions
        - least_reading.total_admissions as kept_admissions_change
    from kept_bounds
    inner join {{ ref("int_park_days__kept") }} as least_reading
        on
            kept_bounds.park_id = least_reading.park_id
            and kept_bounds.session_id = least_reading.session_id
            and kept_bounds.least_seq = least_reading.seq
    inner join {{ ref("int_park_days__kept") }} as greatest_reading
        on
            kept_bounds.park_id = greatest_reading.park_id
            and kept_bounds.session_id = greatest_reading.session_id
            and kept_bounds.greatest_seq = greatest_reading.seq
)

select
    coalesce(admissions_by_session.park_id, kept_change_by_session.park_id)
        as park_id,
    coalesce(
        admissions_by_session.session_id,
        kept_change_by_session.session_id
    )
        as session_id
from admissions_by_session
full outer join kept_change_by_session
    on
        admissions_by_session.park_id = kept_change_by_session.park_id
        and admissions_by_session.session_id = kept_change_by_session.session_id
where
    coalesce(admissions_by_session.summed_admissions_increase, 0)
    is distinct from kept_change_by_session.kept_admissions_change
