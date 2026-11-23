{#
    The registry note that marks a throwaway Sandbox park, as a SQL string
    literal. The Python copy is `registry_feed.PRACTICE_NOTE`;
    `tests/test_practice_note.py` fails when the two differ.
#}
{% macro practice_note() -%}
    'Throwaway practice park; not company data.'
{%- endmacro %}
