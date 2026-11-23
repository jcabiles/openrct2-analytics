-- Warns about each guest exit with no arrival in the same session whose
-- arrived_in_session is not false. A guest seeded at session start has no
-- arrival and arrived_in_session false; any other exit with no arrival
-- means an arrival was lost.
{{ config(severity="warn") }}

select
    exits.session_id,
    exits.guest_key,
    exits.arrived_in_session
from {{ ref("stg_guest_left") }} as exits
left join {{ ref("stg_guest_arrived") }} as arrivals
    on
        exits.session_id = arrivals.session_id
        and exits.guest_key = arrivals.guest_key
where
    arrivals.event_id is null
    and exits.arrived_in_session is distinct from false
