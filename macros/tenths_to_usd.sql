{#
    The only money conversion: the game's tenths of a dollar become dollars.
    The decimal(18, 0) step first makes the multiplication exact for integers
    below 10^17 tenths; larger values fail the decimal(18,2) cast with an error, as the inline cast chain did.
#}
{% macro tenths_to_usd(column) -%}
    {{ dbt.cast(
        dbt.cast(column, api.Column.numeric_type('decimal', 18, 0)) ~ ' * 0.1',
        api.Column.numeric_type('decimal', 18, 2)
    ) }}
{%- endmacro %}
