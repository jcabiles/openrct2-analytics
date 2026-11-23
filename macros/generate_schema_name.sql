{#
    The schema is the layer name from `+schema` in dbt_project.yml (`staging`,
    `intermediate`, `marts`), with no target prefix. dbt's default
    would build `main_staging`. The override is safe only because every
    environment is its own DuckDB file (ADR 0013), so two targets never share
    a schema. Do not copy it to a project whose targets share one database.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
