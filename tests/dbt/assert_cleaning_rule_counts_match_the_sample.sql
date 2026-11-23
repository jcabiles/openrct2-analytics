-- depends_on: {{ ref('fct_cleaning_rule_count') }}
{{ config(severity="error") }}

-- Pins all 21 rows to the counts and the cause measured on the committed
-- sample. The numbers come from a fresh ci build over the sample and are
-- updated with the findings table
-- (docs/ai-dlc/reports/dbt-design--findings.md, section 6.2) whenever the
-- sample is rebuilt.
{% if
    target.name == 'ci'
    and var('parquet_root', 'data/sample/rehearsal') == 'data/sample/rehearsal'
%}

    with

    expected_counts (
        rule_name,
        model_name,
        cause,
        rows_in,
        rows_kept,
        rows_excluded,
        rows_changed
    ) as (
        values
        ('repeat_delivery', 'stg_finance_month', 'source', 3, 3, 0, 0),
        ('repeat_delivery', 'stg_game_action', 'source', 0, 0, 0, 0),
        ('repeat_delivery', 'stg_guest_arrived', 'source', 178, 178, 0, 0),
        ('repeat_delivery', 'stg_guest_boarded', 'source', 2370, 2370, 0, 0),
        ('repeat_delivery', 'stg_guest_left', 'source', 81, 81, 0, 0),
        ('repeat_delivery', 'stg_guest_refused', 'source', 1951, 1951, 0, 0),
        ('repeat_delivery', 'stg_guest_snapshot', 'source', 1478, 1478, 0, 0),
        ('repeat_delivery', 'stg_park_snapshot', 'source', 108, 108, 0, 0),
        ('repeat_delivery', 'stg_ride_snapshot', 'source', 3132, 3132, 0, 0),
        ('repeat_delivery', 'stg_save_written', 'source', 3, 3, 0, 0),
        ('repeat_delivery', 'stg_session_start', 'source', 3, 3, 0, 0),
        (
            'abandoned_branch', 'int_park_days__kept', 'transform',
            108, 105, 3, 0
        ),
        (
            'abandoned_branch', 'int_ride_days__kept', 'transform',
            3132, 3045, 87, 0
        ),
        ('abandoned_branch', 'fct_park_month', 'transform', 3, 3, 0, 0),
        (
            'last_reading_null', 'int_park_days__kept', 'transform',
            105, 105, 0, 3
        ),
        (
            'last_reading_null', 'int_ride_days__kept', 'transform',
            3045, 3045, 0, 87
        ),
        (
            'placeholder_null_minus_1', 'stg_ride_snapshot', 'source',
            3132, 3132, 0, 2376
        ),
        (
            'placeholder_null_255', 'stg_ride_snapshot', 'source',
            3132, 3132, 0, 2916
        ),
        (
            'placeholder_null_1275', 'stg_ride_snapshot', 'source',
            3132, 3132, 0, 0
        ),
        (
            'placeholder_null_65535', 'stg_guest_snapshot', 'source',
            1478, 1478, 0, 277
        ),
        ('exit_without_arrival', 'int_guest_stays', 'source', 81, 15, 66, 0)
    ),

    actual_counts as (
        select
            cleaning_rule_key,
            rule_name,
            model_name,
            cause,
            rows_in,
            rows_kept,
            rows_excluded,
            rows_changed
        from {{ ref("fct_cleaning_rule_count") }}
    ),

    compared_counts as (
        select
            actual.cleaning_rule_key as actual_key,
            expected.cause as expected_cause,
            actual.cause as actual_cause,
            expected.rows_in as expected_rows_in,
            actual.rows_in as actual_rows_in,
            expected.rows_kept as expected_rows_kept,
            actual.rows_kept as actual_rows_kept,
            expected.rows_excluded as expected_rows_excluded,
            actual.rows_excluded as actual_rows_excluded,
            expected.rows_changed as expected_rows_changed,
            actual.rows_changed as actual_rows_changed,
            expected.rule_name || '|' || expected.model_name as expected_key
        from expected_counts as expected
        full outer join actual_counts as actual
            on
                expected.rule_name = actual.rule_name
                and expected.model_name = actual.model_name
    )

    select
        expected_key,
        actual_key,
        expected_cause,
        actual_cause,
        expected_rows_in,
        actual_rows_in,
        expected_rows_kept,
        actual_rows_kept,
        expected_rows_excluded,
        actual_rows_excluded,
        expected_rows_changed,
        actual_rows_changed
    from compared_counts
    where
        actual_key is distinct from expected_key
        or expected_cause is distinct from actual_cause
        or expected_rows_in is distinct from actual_rows_in
        or expected_rows_kept is distinct from actual_rows_kept
        or expected_rows_excluded is distinct from actual_rows_excluded
        or expected_rows_changed is distinct from actual_rows_changed

{% else %}

select
    cast(null as varchar) as expected_key,
    cast(null as varchar) as actual_key
where false

{% endif %}
