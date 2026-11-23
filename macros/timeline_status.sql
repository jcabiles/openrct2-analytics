{#
    Labels an event kept or abandoned from its session's row in
    int_sessions__lineage (ADR 0024 decision 5). Kept means the session is
    on the kept path, it has a cut, and the event's seq is strictly below the
    cut. A missing lineage row (the left join found none), a null cut or seq >=
    cut_seq gives abandoned. The only place a model compares cut_seq.
#}
{% macro timeline_status(seq, lineage) -%}
    case
        when {{ lineage }}.is_on_kept_path
            and {{ lineage }}.cut_seq is not null
            and {{ seq }} < {{ lineage }}.cut_seq
            then 'kept'
        else 'abandoned'
    end
{%- endmacro %}
