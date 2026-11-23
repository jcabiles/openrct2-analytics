{#
    Warns about each event_id that a source delivered more than once with
    different content. It returns one row per such event_id and the number of
    different versions seen, and the stored failures keep them for review.
    Two deliveries always differ in received_at, _raw_file and _raw_line, so
    those three are left out of the comparison; a repeat that differs in
    nothing else is an ordinary repeat and is not returned.

    source_relation is the source() of the event type to check. It is passed
    as an argument, so the generated source file stays generator-owned. A
    model-level test ignores the model argument.
#}
{% test repeat_delivery_payload_differs(model, source_relation) %}

    {{ config(severity="warn", store_failures=true) }}

    {%- set excluded = ["received_at", "_raw_file", "_raw_line"] -%}
    {%- set compared = [] -%}
    {%- if execute -%}
        {%- for column in adapter.get_columns_in_relation(source_relation) -%}
            {%- if column.name not in excluded -%}
                {%- do compared.append(adapter.quote(column.name)) -%}
            {%- endif -%}
        {%- endfor -%}
    {%- endif %}

    with

    versions as (
        select distinct {{ compared | join(", ") }}
        from {{ source_relation }}
    )

    select
        event_id,
        count(*) as versions_seen
    from versions
    group by event_id
    having count(*) > 1

{% endtest %}
