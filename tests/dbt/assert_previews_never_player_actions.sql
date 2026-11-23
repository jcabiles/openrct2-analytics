-- Fails on each labeled game action counted as a player action while a raw
-- signal says it was not: flag bit 64 (a build preview), a client-only hook
-- call (a prediction), a hook other than execute (a query), the derived
-- is_plugin_issued flag (the plugin's own player values or marker key), or the
-- marker key in the raw arguments, which is re-checked here. It never reads
-- action_label, so it checks the label rule independently of the label
-- (invariant 4).
select
    event_id,
    park_id,
    session_id,
    hook,
    args_flags,
    is_client_only,
    player
from {{ ref("int_game_actions__labeled") }}
where
    is_player_action
    and (
        coalesce(args_flags & 64, 0) != 0
        or is_client_only
        or hook != 'execute'
        or is_plugin_issued
        or json_exists(args_json, '$.analytics_issued_by')
    )
