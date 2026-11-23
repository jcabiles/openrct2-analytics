{{ config(severity="error") }}

-- Returns a row (a failure) for each statement in fct_park_month whose
-- cash_usd differs from cash_usd on day 1 of the next game month in
-- fct_park_day for the same park (docs/CONVENTIONS.md, glossary entry
-- "monthly statement": the statement's
-- cash is read at day 1 of the next month). The inner join means a day that
-- was not captured is not checked. Game months run 0 to 7, so the month
-- index is year * 8 + month and month 7 rolls to month 0 of the next year.
-- On the ci target a guard row also fails the test when the number of
-- compared pairs is not 3 (the committed rehearsal sample) and fct_park_month
-- has at least one row, so the test cannot pass while comparing nothing on
-- the sample. The guard is silent on the zero-row extract, where there is
-- nothing to compare; other targets check values only.
with

pairs as (
    select
        m.park_id,
        m.statement_year,
        m.statement_month,
        m.cash_usd as statement_cash_usd,
        d.cash_usd as next_day_start_cash_usd
    from {{ ref("fct_park_month") }} as m
    inner join {{ ref("fct_park_day") }} as d
        on
            m.park_id = d.park_id
            and d.game_year * 8 + d.game_month
            = m.statement_year * 8 + m.statement_month + 1
            and d.game_day = 1
),

mismatches as (
    select
        park_id,
        statement_year,
        statement_month,
        statement_cash_usd,
        next_day_start_cash_usd
    from pairs
    where statement_cash_usd is distinct from next_day_start_cash_usd
)

select * from mismatches
{% if target.name == 'ci' %}
    union all
    select
        cast(null as varchar) as park_id,
        cast(null as integer) as statement_year,
        cast(null as integer) as statement_month,
        cast(null as bigint) as statement_cash_usd,
        cast(null as bigint) as next_day_start_cash_usd
    from (
        select
            (select count(*) from pairs) as compared,
            (select count(*) from {{ ref("fct_park_month") }}) as statements
    ) as pair_count
    where compared != 3 and statements > 0
{% endif %}
