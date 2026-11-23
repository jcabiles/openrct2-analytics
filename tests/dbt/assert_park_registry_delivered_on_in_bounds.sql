-- Warns when delivered_on is before 2026-01-01 or after the build's UTC date.
-- delivered_on is a UTC date, so use UTC rather than the session time zone.
-- It reads the staged feed, so a row from a misnamed file is checked too.
{{ config(severity="warn") }}

select
    park_id,
    delivery_file,
    delivered_on
from {{ ref("stg_park_registry") }}
where
    delivered_on < cast('2026-01-01' as date)
    or delivered_on > cast(
        timezone('UTC', {{ dbt.current_timestamp() }}) as date
    )
