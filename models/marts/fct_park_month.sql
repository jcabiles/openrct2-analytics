{#
    One row per park and closed game month on the kept timeline, dated by the
    statement's own month, never by the day-1 event that carried it (ADR 0008).
    The previous kept statement of the same park gives the gap in months and
    the change in cash less loan less the money already booked to the new
    month; both are null for a park's first kept statement. A statement
    without the booked amount (sent by plugins before 0.6.0) counts it as 0,
    here and nowhere else. The cast keeps the contract type explicit in the
    SQL.
#}
with

kept as (
    select
        park_id,
        statement_year,
        statement_month,
        company_year,
        statement_company_date,
        ride_construction_usd,
        ride_runningcosts_usd,
        land_purchase_usd,
        landscaping_usd,
        park_entrance_tickets_usd,
        park_ride_tickets_usd,
        shop_sales_usd,
        shop_stock_usd,
        food_drink_sales_usd,
        food_drink_stock_usd,
        wages_usd,
        marketing_usd,
        research_usd,
        interest_usd,
        cash_usd,
        bank_loan_usd,
        cast(coalesce(new_month_booked_usd, 0) as decimal(18, 2))
            as new_month_booked_usd
    from {{ ref("int_statements__labeled") }}
    where timeline_status = 'kept'
),

with_previous as (
    select
        *,
        lag(statement_year * 8 + statement_month) over (
            partition by park_id
            order by statement_year, statement_month
        ) as previous_month_index,
        lag(cash_usd - bank_loan_usd - new_month_booked_usd) over (
            partition by park_id
            order by statement_year, statement_month
        ) as previous_cash_less_loan
    from kept
),

derived as (
    select
        *,
        cast(
            (cash_usd - bank_loan_usd - new_month_booked_usd)
            - previous_cash_less_loan
            as decimal(18, 2)
        ) as net_cash_change_usd,
        cast(
            park_ride_tickets_usd
            + food_drink_sales_usd
            + shop_sales_usd
            + park_entrance_tickets_usd
            + ride_runningcosts_usd
            + wages_usd
            + shop_stock_usd
            + food_drink_stock_usd
            + marketing_usd
            + research_usd
            as decimal(18, 2)
        ) as operating_profit,
        cast(
            ride_construction_usd + land_purchase_usd + landscaping_usd
            as decimal(18, 2)
        ) as capital_spending,
        park_id || '|' || statement_year || '|' || statement_month
            as park_month_key,
        statement_year * 8 + statement_month - previous_month_index
            as months_since_previous_statement
    from with_previous
)

select
    park_month_key,
    park_id,
    statement_year,
    statement_month,
    company_year,
    statement_company_date,
    ride_construction_usd,
    ride_runningcosts_usd,
    land_purchase_usd,
    landscaping_usd,
    park_entrance_tickets_usd,
    park_ride_tickets_usd,
    shop_sales_usd,
    shop_stock_usd,
    food_drink_sales_usd,
    food_drink_stock_usd,
    wages_usd,
    marketing_usd,
    research_usd,
    interest_usd,
    cash_usd,
    bank_loan_usd,
    new_month_booked_usd,
    months_since_previous_statement,
    net_cash_change_usd,
    operating_profit,
    capital_spending
from derived
