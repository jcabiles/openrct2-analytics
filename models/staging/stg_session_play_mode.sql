{#-
    A data set may hold no label file yet (company before its first autopilot
    run; rehearsal), and DuckDB's read_csv fails on a pattern that matches no
    file even when a filter keeps every row out. So the executed SQL names the
    source only when glob() finds a label file, under the registry root and
    file glob the source config holds. The parse pass (execute is false) takes
    the source branch, so dbt records the lineage. Both branches return the
    same columns, all text, as the source reads them.

    A file counts only when its base name is session_play_mode_YYYY-MM-DD_NN.csv
    with NN other than 00, the rule play_mode_feed and the park registry
    history apply; any other file adds no rows. The shape is checked by
    position: digits are blanked and what is left must be empty.
-#}
{%- set shape_parts = [
    "substring(file_name, 19, 4)",
    "substring(file_name, 24, 2)",
    "substring(file_name, 27, 2)",
    "substring(file_name, 30, 2)",
] -%}
{%- set shape = namespace(expr=shape_parts | join(" || ")) -%}
{%- for digit in range(10) -%}
    {%- set shape.expr = dbt.replace(shape.expr, "'" ~ digit ~ "'", "''") -%}
{%- endfor -%}
{%- set has_label_file = true -%}
{%- if execute -%}
    {%- set label_source = graph.sources[
        'source.' ~ project_name ~ '.registry.session_play_mode'
    ].config -%}
    {%- set label_glob = (
        label_source.registry_root ~ '/' ~ label_source.file_glob
    ) | replace("'", "''") -%}
    {%- set has_label_file = run_query(
        "select count(*) from glob('" ~ label_glob ~ "')"
    ).columns[0].values()[0] > 0 -%}
{%- endif %}

with

landing_session_play_mode as (
    {% if has_label_file %}
        select
            session_id,
            park_id,
            play_mode,
            ready_confirmation,
            data_set,
            delivered_on,
            filename,
            {{ dbt.split_part("filename", "'/'", -1) }} as file_name
        from {{ source('registry', 'session_play_mode') }}
    {% else %}
        select
            cast(null as varchar) as session_id,
            cast(null as varchar) as park_id,
            cast(null as varchar) as play_mode,
            cast(null as varchar) as ready_confirmation,
            cast(null as varchar) as data_set,
            cast(null as varchar) as delivered_on,
            cast(null as varchar) as filename,
            cast(null as varchar) as file_name
        where false
    {% endif %}
),

final as (
    select
        session_id,
        park_id,
        play_mode,
        ready_confirmation,
        data_set,
        cast(delivered_on as date) as delivered_on,
        filename as delivery_file
    from landing_session_play_mode
    where
        {{ dbt.length("file_name") }} = 35
        and substring(file_name, 1, 18) = 'session_play_mode_'
        and {{ dbt.right("file_name", 4) }} = '.csv'
        and substring(file_name, 23, 1) = '-'
        and substring(file_name, 26, 1) = '-'
        and substring(file_name, 29, 1) = '_'
        and {{ shape.expr }} = ''
        and substring(file_name, 30, 2) != '00'
)

select
    session_id,
    park_id,
    play_mode,
    ready_confirmation,
    data_set,
    delivered_on,
    delivery_file
from final
