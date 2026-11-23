-- Returns a row (a failure) for each fixed reading whose counter_change
-- differs from its expected change. Part 'column': session A reads 4, 10, 15
-- on game 9/0/30, 9/0/31 (31 March) and 9/1/1 (1 April); session B, which
-- loaded A's save, reads 18 and 20; a second entity in A reads 7, 7. Each
-- change belongs to the earlier reading, the last reading of a session has
-- none, and no change crosses from A to B (ADR 0024 decision 7). Part
-- 'expression': the counter is the expression reading_a - reading_b (10 - 3
-- = 7, then 15 - 4 = 11), so the change is 4; a macro that leaves the
-- expression unparenthesised returns -2 instead.
with

readings as (
    select fixture.*
    from (
        values
        ('park1', 'session_a', 'entity_1', 1, 9, 0, 30, 4, 6),
        ('park1', 'session_a', 'entity_1', 2, 9, 0, 31, 10, 5),
        ('park1', 'session_a', 'entity_1', 3, 9, 1, 1, 15, null),
        ('park1', 'session_b', 'entity_1', 1, 9, 1, 2, 18, 2),
        ('park1', 'session_b', 'entity_1', 2, 9, 1, 3, 20, null),
        ('park1', 'session_a', 'entity_2', 1, 9, 0, 30, 7, 0),
        ('park1', 'session_a', 'entity_2', 2, 9, 0, 31, 7, null)
    ) as fixture (
        park_id, session_id, entity_id, seq, game_year, game_month,
        game_day, reading, expected_change
    )
),

expression_readings as (
    select fixture.*
    from (
        values
        ('park1', 'session_a', 1, 10, 3, 4),
        ('park1', 'session_a', 2, 15, 4, null)
    ) as fixture (
        park_id, session_id, seq, reading_a, reading_b, expected_change
    )
),

computed as (
    select
        'column' as part,
        session_id,
        seq,
        expected_change,
        {{ counter_change('reading', ['entity_id']) }} as computed_change
    from readings
    union all
    select
        'expression' as part,
        session_id,
        seq,
        expected_change,
        {{ counter_change('reading_a - reading_b') }} as computed_change
    from expression_readings
)

select *
from computed
where computed_change is distinct from expected_change
