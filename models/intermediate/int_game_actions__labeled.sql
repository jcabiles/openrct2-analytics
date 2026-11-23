{#
    One row per staged game_action, with three labels that say who acted and
    whether the attempt was refused. The plugin's own label (action_label) is
    kept beside the raw signals; nothing here is filtered out. Previews and
    client-side predictions never count as player actions (invariant 4): an
    action is a player action only when the game ran it (hook = execute),
    the plugin labeled it confirmed and the plugin did not issue it itself.
    The plugin issued it when the row's player is in the variable
    plugin_issued_player_values or its arguments carry the key
    analytics_issued_by. On OpenRCT2 0.5.6 the key does not reach the
    recorded arguments, so that rule is inert and the player rule carries
    the provenance (its value is explained in dbt_project.yml).
#}
{%- set issued_players = var('plugin_issued_player_values') -%}
with

actions as (
    select
        stg_game_action.schema_version,
        stg_game_action.event_type,
        stg_game_action.plugin_version,
        stg_game_action.park_id,
        stg_game_action.session_id,
        stg_game_action.seq,
        stg_game_action.event_id,
        stg_game_action.game_year,
        stg_game_action.game_month,
        stg_game_action.game_day,
        stg_game_action.game_ticks_elapsed,
        stg_game_action.emitted_at,
        stg_game_action.received_at,
        stg_game_action._raw_file,
        stg_game_action._raw_line,
        stg_game_action.hook,
        stg_game_action.action,
        stg_game_action.action_label,
        stg_game_action.args_flags,
        stg_game_action.is_client_only,
        stg_game_action.player,
        stg_game_action.type,
        stg_game_action.args_json,
        stg_game_action.args_ride,
        stg_game_action.args_ride_type,
        stg_game_action.args_ride_object,
        stg_game_action.args_price_usd,
        stg_game_action.args_x,
        stg_game_action.args_y,
        stg_game_action.args_z,
        stg_game_action.result_error,
        stg_game_action.result_cost_usd,
        stg_game_action.result_ride,
        stg_game_action.action_at_ticks,
        stg_game_action.action_game_year,
        stg_game_action.action_game_month,
        stg_game_action.action_game_day,
        {% if issued_players | length > 0 -%}
            stg_game_action.player in ({{ issued_players | join(', ') }})
        {%- else -%}
            false
        {%- endif %}
        or json_exists(stg_game_action.args_json, '$.analytics_issued_by')
            as is_plugin_issued
    from {{ ref("stg_game_action") }} as stg_game_action
)

select
    schema_version,
    event_type,
    plugin_version,
    park_id,
    session_id,
    seq,
    event_id,
    game_year,
    game_month,
    game_day,
    game_ticks_elapsed,
    emitted_at,
    received_at,
    _raw_file,
    _raw_line,
    hook,
    action,
    action_label,
    args_flags,
    is_client_only,
    player,
    type,
    args_json,
    args_ride,
    args_ride_type,
    args_ride_object,
    args_price_usd,
    args_x,
    args_y,
    args_z,
    result_error,
    result_cost_usd,
    result_ride,
    action_at_ticks,
    action_game_year,
    action_game_month,
    action_game_day,
    is_plugin_issued,
    (
        hook = 'execute'
        and action_label = 'confirmed'
        and not is_plugin_issued
    ) as is_player_action,
    coalesce(result_error, 0) <> 0 as is_refused
from actions
