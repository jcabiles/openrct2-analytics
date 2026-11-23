{#
    Keeps every park registry delivery with the interval it was the latest
    word on its park. A delivery is a file: its identity is the park and the
    file, and the file name carries the date and the sequence. Each park's
    deliveries are ordered by the name's date, then the sequence, so a
    same-day correction (_02) follows the first file (_01). A delivery is
    valid from the name's date until the next distinct delivery's name date.
    The delivered_on cell never orders or dates a delivery; it is kept as a
    column and the date tests compare it with the name. Sequences run from 01.

    The date and sequence are read from the file's base name, never from the
    path, because delivery_file is relative in ci and absolute in a publish.
    The name's shape is checked by position: the separators sit at fixed
    places and the eight date and sequence characters are all digits, so no
    cast can fail on a misnamed file; that file, and one with sequence 00, is
    left out here and the pattern test warns about it. A name that has the
    shape but an impossible date (2026-02-30) fails the build at the date cast.
#}
{%- set shape_parts = [
    "substring(file_name, 15, 4)",
    "substring(file_name, 20, 2)",
    "substring(file_name, 23, 2)",
    "substring(file_name, 26, 2)",
] -%}
{%- set shape = namespace(expr=shape_parts | join(" || ")) -%}
{%- for digit in range(10) -%}
    {%- set shape.expr = dbt.replace(shape.expr, "'" ~ digit ~ "'", "''") -%}
{%- endfor -%}

with

registry_rows as (
    select
        park_id,
        company_start_year,
        game_year_origin,
        data_set,
        note,
        delivered_on,
        delivery_file,
        {{ dbt.split_part("delivery_file", "'/'", -1) }} as file_name
    from {{ ref("stg_park_registry") }}
),

named_rows as (
    select
        park_id,
        company_start_year,
        game_year_origin,
        data_set,
        note,
        delivered_on,
        delivery_file,
        file_name,
        substring(file_name, 15, 10) as file_date,
        {{ dbt.cast("substring(file_name, 26, 2)", dbt.type_int()) }}
            as file_sequence
    from registry_rows
    where
        {{ dbt.length("file_name") }} = 31
        and substring(file_name, 1, 14) = 'park_registry_'
        and {{ dbt.right("file_name", 4) }} = '.csv'
        and substring(file_name, 19, 1) = '-'
        and substring(file_name, 22, 1) = '-'
        and substring(file_name, 25, 1) = '_'
        and {{ shape.expr }} = ''
        and substring(file_name, 26, 2) != '00'
),

deliveries as (
    select distinct
        park_id,
        delivery_file,
        file_name,
        file_date,
        file_sequence
    from named_rows
),

delivery_intervals as (
    select
        park_id,
        delivery_file,
        {{ dbt.cast("file_date", "date") }} as valid_from,
        lead({{ dbt.cast("file_date", "date") }}) over (
            partition by park_id
            order by
                {{ dbt.cast("file_date", "date") }},
                file_sequence,
                file_name,
                delivery_file
        ) as valid_to
    from deliveries
)

select
    n.park_id,
    n.company_start_year,
    n.game_year_origin,
    n.data_set,
    n.note,
    n.delivered_on,
    n.delivery_file,
    n.file_name,
    n.file_date,
    n.file_sequence,
    i.valid_from,
    i.valid_to,
    i.valid_to is null as is_current
from named_rows as n
inner join delivery_intervals as i
    on
        n.park_id = i.park_id
        and n.delivery_file = i.delivery_file
