-- Fails on each guest stay whose stay_game_days is negative, so an exit
-- never precedes its arrival (clock: game days).
select
    session_id,
    guest_key,
    stay_game_days
from {{ ref("int_guest_stays") }}
where stay_game_days < 0
