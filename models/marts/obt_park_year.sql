{#
    One row per park per company year with a kept statement.
    Month sums are summed; every ratio is recomputed from the year's sums, never averaged.
    A company year maps to exactly one game year, so min(statement_year) is that year.
    Close status comes from the year-close register; this model derives no close rule.
#}
with

months as (
    select
        park_month_key,
        park_id,
        statement_year,
        company_year,
        company_date,
        operating_profit,
        operating_revenue,
        ride_revenue,
        food_drink_revenue,
        merchandise_revenue,
        entrance_revenue,
        operating_costs,
        ride_running_costs,
        staff_wages,
        stock_costs,
        marketing_costs,
        research_costs,
        capital_spending,
        interest_costs,
        guest_visits,
        operating_days,
        days_with_visits,
        park_rating_sum
    from {{ ref("obt_park_month") }}
),

cash as (
    select
        park_month_key,
        net_cash_change_usd
    from {{ ref("fct_park_month") }}
),

register as (
    select
        park_id,
        company_year,
        statements_expected,
        statements_kept,
        close_status,
        is_partial_first_season,
        is_company_year_closed
    from {{ ref("int_park_years__year_close") }}
),

joined as (
    select
        months.*,
        cash.net_cash_change_usd
    from months
    left join cash
        on months.park_month_key = cash.park_month_key
),

by_park_year as (
    select
        park_id,
        company_year,
        park_id || '|' || cast(min(statement_year) as varchar) as park_year_key,
        min(statement_year) as game_year,
        min(company_date) as first_statement_company_date,
        max(company_date) as last_statement_company_date,
        count(net_cash_change_usd) as months_checked,
        sum(operating_profit) as operating_profit,
        sum(operating_revenue) as operating_revenue,
        sum(ride_revenue) as ride_revenue,
        sum(food_drink_revenue) as food_drink_revenue,
        sum(merchandise_revenue) as merchandise_revenue,
        sum(entrance_revenue) as entrance_revenue,
        sum(operating_costs) as operating_costs,
        sum(ride_running_costs) as ride_running_costs,
        sum(staff_wages) as staff_wages,
        sum(stock_costs) as stock_costs,
        sum(marketing_costs) as marketing_costs,
        sum(research_costs) as research_costs,
        sum(capital_spending) as capital_spending,
        sum(interest_costs) as interest_costs,
        sum(guest_visits) as guest_visits,
        sum(operating_days) as operating_days,
        sum(days_with_visits) as days_with_visits,
        sum(park_rating_sum) as park_rating_sum
    from joined
    group by park_id, company_year
)

select
    y.park_year_key,
    y.park_id,
    cast(y.company_year as integer) as company_year,
    cast(y.game_year as integer) as game_year,
    y.first_statement_company_date,
    y.last_statement_company_date,
    cast(register.statements_kept as integer) as statements_kept,
    cast(register.statements_expected as integer) as statements_expected,
    register.close_status,
    register.is_partial_first_season,
    register.is_company_year_closed,
    cast(y.months_checked as integer) as months_checked,
    cast(y.operating_profit as decimal(18, 2)) as operating_profit,
    cast(y.operating_revenue as decimal(18, 2)) as operating_revenue,
    cast(y.ride_revenue as decimal(18, 2)) as ride_revenue,
    cast(y.food_drink_revenue as decimal(18, 2)) as food_drink_revenue,
    cast(y.merchandise_revenue as decimal(18, 2)) as merchandise_revenue,
    cast(y.entrance_revenue as decimal(18, 2)) as entrance_revenue,
    cast(y.operating_costs as decimal(18, 2)) as operating_costs,
    cast(y.ride_running_costs as decimal(18, 2)) as ride_running_costs,
    cast(y.staff_wages as decimal(18, 2)) as staff_wages,
    cast(y.stock_costs as decimal(18, 2)) as stock_costs,
    cast(y.marketing_costs as decimal(18, 2)) as marketing_costs,
    cast(y.research_costs as decimal(18, 2)) as research_costs,
    cast(y.capital_spending as decimal(18, 2)) as capital_spending,
    cast(y.interest_costs as decimal(18, 2)) as interest_costs,
    cast(y.guest_visits as bigint) as guest_visits,
    cast(y.operating_days as integer) as operating_days,
    cast(y.days_with_visits as integer) as days_with_visits,
    cast(y.park_rating_sum as bigint) as park_rating_sum,
    cast(
        y.park_rating_sum / nullif(y.operating_days, 0)
        as decimal(18, 2)
    ) as average_park_rating,
    cast(
        y.operating_revenue / nullif(y.guest_visits, 0)
        as decimal(18, 2)
    ) as revenue_per_visit,
    cast(
        y.ride_revenue / nullif(y.guest_visits, 0)
        as decimal(18, 2)
    ) as ride_revenue_per_visit,
    cast(
        y.food_drink_revenue / nullif(y.guest_visits, 0)
        as decimal(18, 2)
    ) as food_drink_revenue_per_visit,
    cast(
        y.merchandise_revenue / nullif(y.guest_visits, 0)
        as decimal(18, 2)
    ) as merchandise_revenue_per_visit,
    cast(
        y.operating_revenue / nullif(y.operating_days, 0)
        as decimal(18, 2)
    ) as revenue_per_operating_day
from by_park_year as y
left join register
    on
        y.park_id = register.park_id
        and y.company_year = register.company_year
