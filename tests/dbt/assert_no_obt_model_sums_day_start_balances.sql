{{ config(severity="error") }}

-- Returns one row (a failure) for each summary model (a model named obt_*)
-- whose SQL text names cash_usd or guests_in_park: both are day-start
-- balances, and summing them across days adds a reading that is not a flow.
-- The whole text is searched, not only sum(...), because no obt_ model has a
-- reason to read a day-start balance, and an alias made in an earlier CTE
-- (cash_usd as balance, then sum(balance)) would escape a sum-only match.
-- Known limits: it reads SQL text, so a balance read through a macro or an
-- upstream model is not seen, and a comment that names cash_usd fails it (a
-- safe false alarm). bank_loan_usd, also a balance, is not checked.
-- A pattern or star expression such as columns('^cash_') reads a balance
-- without naming it and is not caught.
{% set offenders = [] %}
{% if execute %}
    {% for node in graph.nodes.values() %}
        {% if node.resource_type == 'model' and node.name.startswith('obt_') %}
            {% set code = node.raw_code | lower %}
            {% if modules.re.search('cash_usd|guests_in_park', code) %}
                {% do offenders.append(node.name) %}
            {% endif %}
        {% endif %}
    {% endfor %}
{% endif %}

{% if offenders | length > 0 %}
    {% for name in offenders %}
        select '{{ name }}' as model_name
        {% if not loop.last %}
            union all
        {% endif %}
    {% endfor %}
{% else %}
    select cast(null as varchar) as model_name
    where false
{% endif %}
