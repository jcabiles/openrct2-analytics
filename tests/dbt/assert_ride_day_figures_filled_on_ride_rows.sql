-- On the sample every figure has a value on some ride row; a column wired to
-- null fails. Elsewhere it returns no rows, as rows_on_sample does: real data
-- may lack a figure (a new ride has no rating).
{{ config(severity='error') }}

{% set sample_root = 'data/sample/rehearsal' %}
{% set on_sample = (
    target.name == 'ci' and var('parquet_root', sample_root) == sample_root
) %}

with

ride_rows as (
    select
        count(*) as ride_row_count,
        count(availability_from_downtime_pct) as availability_count,
        count(longest_queue_seen_minutes) as queue_count,
        count(guest_rating_pct) as rating_count
    from {{ ref('fct_ride_day') }}
    where classification = 'ride'
),

figures as (
    select
        'availability_from_downtime_pct' as figure,
        ride_row_count,
        availability_count as filled_count
    from ride_rows
    union all
    select
        'longest_queue_seen_minutes' as figure,
        ride_row_count,
        queue_count as filled_count
    from ride_rows
    union all
    select
        'guest_rating_pct' as figure,
        ride_row_count,
        rating_count as filled_count
    from ride_rows
)

select
    figure,
    ride_row_count
from figures
where
    ride_row_count > 0
    and filled_count = 0
    and {{ 'true' if on_sample else 'false' }}
