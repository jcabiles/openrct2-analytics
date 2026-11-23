{#
    A counter's change from this reading to the next one in the same
    session (and the same entity columns), ordered by seq (ADR 0024
    decision 7). seq restarts in every session, so no change crosses a
    session boundary. The change belongs to the earlier reading; the last
    reading of each session gets null. The caller passes kept rows only
    and must expose session_id and seq.
#}
{% macro counter_change(counter, entity_columns=[]) -%}
    lead({{ counter }}) over (
        partition by session_id{% for column in entity_columns %},
        {{ column }}{% endfor %}
        order by seq
    ) - ({{ counter }})
{%- endmacro %}
