{#
    The only month-to-date rule: game month 0 to 7 is March to October
    (contracts/envelope.odcs.yaml), so the date is in company year
    `company_year`, month `game_month + 3`, on day `game_day`. The day passes
    through. A month outside 0 to 7, or a null argument, gives null, so no date
    falls in November to February.
#}
{% macro company_date(company_year, game_month, game_day) -%}
    case
        when {{ game_month }} between 0 and 7
            then {{ dbt.cast(
                dbt.concat([
                    dbt.cast(company_year, dbt.type_string()),
                    "'-'",
                    dbt.cast("(" ~ game_month ~ " + 3)", dbt.type_string()),
                    "'-'",
                    dbt.cast(game_day, dbt.type_string()),
                ]),
                api.Column.translate_type('date')
            ) }}
    end
{%- endmacro %}
