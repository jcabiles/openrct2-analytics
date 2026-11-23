{#
    Returns one row unless the model holds exactly the expected number of rows
    on the committed sample. It counts only on the ci target with parquet_root
    set to the sample; on the zero-row build, the dev target and the publish
    targets it returns no rows. The branch is in the SQL, not in
    config(enabled=...), so it is rendered again on every invocation.
#}
{% test rows_on_sample(model, expected) %}

    {%- if target.name == 'ci' and var('parquet_root', 'data/sample/rehearsal') == 'data/sample/rehearsal' -%}
        select
            count(*) as rows_found,
            {{ expected }} as rows_expected
        from {{ model }}
        having count(*) != {{ expected }}
    {%- else -%}
        select 1 as rows_found, 1 as rows_expected where false
    {%- endif -%}

{% endtest %}
