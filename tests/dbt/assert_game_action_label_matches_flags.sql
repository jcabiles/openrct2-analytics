-- Fails on each staged game action whose action_label disagrees with the
-- label worked out again from the raw columns: preview when flag bit 64 is
-- set, else prediction when the hook call is client-only, else confirmed.
select
    event_id,
    park_id,
    session_id,
    action_label,
    args_flags,
    is_client_only
from {{ ref("stg_game_action") }}
where
    action_label is distinct from case
        when coalesce(args_flags & 64, 0) != 0 then 'preview'
        when is_client_only then 'prediction'
        else 'confirmed'
    end
