{#
    One row per session seen in stg_envelope, with its place on the kept
    timeline (ADR 0024). Each session gets a load status and a
    parent, a first recursive walk assigns every session to a tree, each
    tree's most recently started session is its frontier, and a second
    recursive walk climbs from each frontier to mark the kept path. The first
    walk starts from sessions that have no parent; the second starts from each
    tree's one frontier and climbs parents; neither can loop. A session in a
    parent loop is never reached
    and keeps a null tree_root_session_id, which a not_null test fails.
    stg_envelope is read only through group by and distinct, so a repeated
    delivery changes nothing.
#}
with recursive

sessions as (
    select
        session_id,
        park_id,
        min(seq) as first_seq
    from {{ ref("stg_envelope") }}
    group by session_id, park_id
),

session_events as (
    select distinct
        session_id,
        seq,
        game_ticks_elapsed
    from {{ ref("stg_envelope") }}
),

session_starts as (
    select
        session_id,
        emitted_at,
        loaded_save_id,
        loaded_save_session_id,
        loaded_save_seq_floor,
        loaded_save_lines_waiting
    from {{ ref("stg_session_start") }}
),

saves as (
    select
        save_id,
        session_id,
        seq
    from {{ ref("stg_save_written") }}
),

loads as (
    select
        sessions.session_id,
        sessions.park_id,
        session_starts.emitted_at as session_started_at,
        session_starts.loaded_save_id,
        session_starts.loaded_save_session_id,
        session_starts.loaded_save_seq_floor,
        session_starts.loaded_save_lines_waiting,
        loaded_saves.session_id as loaded_save_writer_id,
        loaded_saves.seq as loaded_save_seq,
        sessions.first_seq = 1 as first_seq_is_one,
        session_starts.session_id is not null as has_session_start,
        case
            when session_starts.loaded_save_id is null
                then 'root'
            when loaded_saves.save_id is not null
                then 'loaded'
            when
                session_starts.loaded_save_session_id in (
                    select known.session_id from sessions as known
                )
                and session_starts.loaded_save_seq_floor is not null
                and session_starts.loaded_save_lines_waiting is not null
                then 'estimated'
            else 'orphan'
        end as load_status
    from sessions
    left join session_starts
        on sessions.session_id = session_starts.session_id
    left join saves as loaded_saves
        on session_starts.loaded_save_id = loaded_saves.save_id
),

classified as (
    select
        session_id,
        park_id,
        session_started_at,
        loaded_save_id,
        load_status,
        first_seq_is_one,
        has_session_start,
        case load_status
            when 'loaded' then loaded_save_writer_id
            when 'estimated' then loaded_save_session_id
        end as parent_session_id,
        case load_status
            when 'loaded' then loaded_save_seq
            when 'estimated'
                then loaded_save_seq_floor + loaded_save_lines_waiting + 1
        end as implied_cut_seq
    from loads
),

tree_starts as (
    select
        session_id,
        session_id as tree_root_session_id
    from classified
    where load_status = 'root'
    union all
    select
        session_id,
        first_value(session_id) over (
            partition by park_id, loaded_save_id
            order by session_started_at, session_id
        ) as tree_root_session_id
    from classified
    where load_status = 'orphan'
),

tree_walk as (
    select
        session_id,
        tree_root_session_id
    from tree_starts
    union all
    select
        child.session_id,
        tree_walk.tree_root_session_id
    from tree_walk
    inner join classified as child
        on tree_walk.session_id = child.parent_session_id
),

trees as (
    select
        classified.*,
        tree_walk.tree_root_session_id
    from classified
    left join tree_walk
        on classified.session_id = tree_walk.session_id
),

frontiers as (
    select
        session_id,
        parent_session_id,
        row_number() over (
            partition by tree_root_session_id
            order by session_started_at desc nulls last, session_id desc
        ) = 1 as is_frontier
    from trees
    where tree_root_session_id is not null
),

kept_walk as (
    select
        session_id,
        parent_session_id,
        cast(null as varchar) as continued_by_session_id
    from frontiers
    where is_frontier
    union all
    select
        parent.session_id,
        parent.parent_session_id,
        kept_walk.session_id as continued_by_session_id
    from kept_walk
    inner join classified as parent
        on kept_walk.parent_session_id = parent.session_id
),

own_last_saves as (
    select
        session_id,
        max(seq) as own_last_save_seq
    from saves
    group by session_id
),

cuts as (
    select
        trees.session_id,
        trees.park_id,
        trees.first_seq_is_one,
        trees.has_session_start,
        trees.session_started_at,
        trees.loaded_save_id,
        trees.load_status,
        trees.parent_session_id,
        trees.tree_root_session_id,
        kept_walk.continued_by_session_id,
        coalesce(frontiers.is_frontier, false) as is_frontier,
        kept_walk.session_id is not null as is_on_kept_path,
        case
            when kept_walk.session_id is null
                then null
            when kept_walk.continued_by_session_id is null
                then own_last_saves.own_last_save_seq
            else continued_by.implied_cut_seq
        end as cut_seq,
        case
            when kept_walk.session_id is null
                then null
            when kept_walk.continued_by_session_id is null
                then
                    case
                        when own_last_saves.own_last_save_seq is not null
                            then false
                    end
            else continued_by.load_status = 'estimated'
        end as cut_is_estimated
    from trees
    left join frontiers
        on trees.session_id = frontiers.session_id
    left join kept_walk
        on trees.session_id = kept_walk.session_id
    left join classified as continued_by
        on kept_walk.continued_by_session_id = continued_by.session_id
    left join own_last_saves
        on trees.session_id = own_last_saves.session_id
),

kept_ticks as (
    select
        cuts.session_id,
        min(session_events.game_ticks_elapsed) as first_kept_game_ticks,
        max(session_events.game_ticks_elapsed) as last_kept_game_ticks
    from cuts
    inner join session_events
        on
            cuts.session_id = session_events.session_id
            and cuts.cut_seq > session_events.seq
    group by cuts.session_id
),

ranged as (
    select
        cuts.*,
        kept_ticks.first_kept_game_ticks,
        kept_ticks.last_kept_game_ticks
    from cuts
    left join kept_ticks
        on cuts.session_id = kept_ticks.session_id
),

overlapping_sessions as (
    select
        this_session.session_id,
        min(other_session.session_id) as overlaps_kept_session_id
    from ranged as this_session
    inner join ranged as other_session
        on
            this_session.park_id = other_session.park_id
            and this_session.session_id <> other_session.session_id
            and this_session.first_kept_game_ticks
            < other_session.last_kept_game_ticks
            and this_session.last_kept_game_ticks
            > other_session.first_kept_game_ticks
    group by this_session.session_id
),

final as (
    select
        ranged.session_id,
        ranged.park_id,
        ranged.first_seq_is_one,
        ranged.has_session_start,
        ranged.session_started_at,
        ranged.loaded_save_id,
        ranged.load_status,
        ranged.parent_session_id,
        ranged.tree_root_session_id,
        ranged.is_frontier,
        ranged.is_on_kept_path,
        ranged.continued_by_session_id,
        ranged.cut_seq,
        ranged.cut_is_estimated,
        ranged.first_kept_game_ticks,
        ranged.last_kept_game_ticks,
        overlapping_sessions.overlaps_kept_session_id
    from ranged
    left join overlapping_sessions
        on ranged.session_id = overlapping_sessions.session_id
)

select * from final
