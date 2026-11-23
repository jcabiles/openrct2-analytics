{{ config(severity="error") }}

-- Returns a row (a failure) for each park-month in fct_park_month whose cash
-- does not reconcile with the park's previous kept statement: the ledger lines
-- do not add up to the change in cash less loan less the money already booked
-- to the new month (new_month_booked_usd, 0 for statements without it),
-- net_cash_change_usd or months_since_previous_statement disagrees with the
-- value computed here, a first statement carries a cash change, or a game
-- month is missing between two kept statements. Game months run 0 to 7, so
-- the month index is statement_year * 8 + statement_month. The severity is
-- error on every target.
with

previous as (
    select
        park_id,
        statement_year,
        statement_month,
        operating_profit,
        capital_spending,
        interest_usd,
        net_cash_change_usd,
        months_since_previous_statement,
        statement_year * 8 + statement_month as month_index,
        cash_usd - bank_loan_usd - new_month_booked_usd as cash_less_loan,
        lag(statement_year * 8 + statement_month) over (
            partition by park_id
            order by statement_year, statement_month
        ) as previous_month_index,
        lag(cash_usd - bank_loan_usd - new_month_booked_usd) over (
            partition by park_id
            order by statement_year, statement_month
        ) as previous_cash_less_loan
    from {{ ref("fct_park_month") }}
)

select
    park_id,
    statement_year,
    statement_month
from previous
where
    (
        previous_month_index is not null
        and operating_profit + capital_spending + interest_usd
        is distinct from cash_less_loan - previous_cash_less_loan
    )
    or net_cash_change_usd
    is distinct from cash_less_loan - previous_cash_less_loan
    or (previous_month_index is null and net_cash_change_usd is not null)
    or (
        previous_month_index is not null
        and month_index - previous_month_index is distinct from 1
    )
    or months_since_previous_statement
    is distinct from month_index - previous_month_index
