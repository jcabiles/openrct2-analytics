{{ config(severity="error") }}

-- Returns a row (a failure) for each park year where obt_park_year disagrees
-- with its own aggregate of obt_park_month: the year is on one side only,
-- statements_kept, months_checked or any sum differs. months_checked counts
-- monthly statements with a net cash change from fct_park_month.
-- It catches a missing or doubled monthly statement and a lost or changed sum.
-- It cannot catch a monthly statement that is already wrong in both sources.
with

expected as (
    select
        months.park_id,
        months.company_year,
        count(*) as statements_kept,
        count(cash.net_cash_change_usd) as months_checked,
        sum(months.operating_profit) as operating_profit,
        sum(months.operating_revenue) as operating_revenue,
        sum(months.ride_revenue) as ride_revenue,
        sum(months.food_drink_revenue) as food_drink_revenue,
        sum(months.merchandise_revenue) as merchandise_revenue,
        sum(months.entrance_revenue) as entrance_revenue,
        sum(months.operating_costs) as operating_costs,
        sum(months.ride_running_costs) as ride_running_costs,
        sum(months.staff_wages) as staff_wages,
        sum(months.stock_costs) as stock_costs,
        sum(months.marketing_costs) as marketing_costs,
        sum(months.research_costs) as research_costs,
        sum(months.capital_spending) as capital_spending,
        sum(months.interest_costs) as interest_costs,
        sum(months.guest_visits) as guest_visits,
        sum(months.operating_days) as operating_days,
        sum(months.days_with_visits) as days_with_visits,
        sum(months.park_rating_sum) as park_rating_sum
    from {{ ref("obt_park_month") }} as months
    left join {{ ref("fct_park_month") }} as cash
        on months.park_month_key = cash.park_month_key
    group by months.park_id, months.company_year
)

select
    expected.operating_profit as expected_operating_profit,
    mart.operating_profit as mart_operating_profit,
    expected.operating_revenue as expected_operating_revenue,
    mart.operating_revenue as mart_operating_revenue,
    expected.ride_revenue as expected_ride_revenue,
    mart.ride_revenue as mart_ride_revenue,
    expected.food_drink_revenue as expected_food_drink_revenue,
    mart.food_drink_revenue as mart_food_drink_revenue,
    expected.merchandise_revenue as expected_merchandise_revenue,
    mart.merchandise_revenue as mart_merchandise_revenue,
    expected.entrance_revenue as expected_entrance_revenue,
    mart.entrance_revenue as mart_entrance_revenue,
    expected.operating_costs as expected_operating_costs,
    mart.operating_costs as mart_operating_costs,
    expected.ride_running_costs as expected_ride_running_costs,
    mart.ride_running_costs as mart_ride_running_costs,
    expected.staff_wages as expected_staff_wages,
    mart.staff_wages as mart_staff_wages,
    expected.stock_costs as expected_stock_costs,
    mart.stock_costs as mart_stock_costs,
    expected.marketing_costs as expected_marketing_costs,
    mart.marketing_costs as mart_marketing_costs,
    expected.research_costs as expected_research_costs,
    mart.research_costs as mart_research_costs,
    expected.capital_spending as expected_capital_spending,
    mart.capital_spending as mart_capital_spending,
    expected.interest_costs as expected_interest_costs,
    mart.interest_costs as mart_interest_costs,
    expected.guest_visits as expected_guest_visits,
    mart.guest_visits as mart_guest_visits,
    expected.operating_days as expected_operating_days,
    mart.operating_days as mart_operating_days,
    expected.days_with_visits as expected_days_with_visits,
    mart.days_with_visits as mart_days_with_visits,
    expected.park_rating_sum as expected_park_rating_sum,
    mart.park_rating_sum as mart_park_rating_sum,
    expected.statements_kept as expected_statements_kept,
    mart.statements_kept as mart_statements_kept,
    expected.months_checked as expected_months_checked,
    mart.months_checked as mart_months_checked,
    coalesce(expected.park_id, mart.park_id) as park_id,
    coalesce(expected.company_year, mart.company_year) as company_year
from expected
full outer join {{ ref("obt_park_year") }} as mart
    on
        expected.park_id = mart.park_id
        and expected.company_year = mart.company_year
where
    expected.park_id is null
    or mart.park_id is null
    or mart.operating_profit is distinct from expected.operating_profit
    or mart.operating_revenue is distinct from expected.operating_revenue
    or mart.ride_revenue is distinct from expected.ride_revenue
    or mart.food_drink_revenue is distinct from expected.food_drink_revenue
    or mart.merchandise_revenue is distinct from expected.merchandise_revenue
    or mart.entrance_revenue is distinct from expected.entrance_revenue
    or mart.operating_costs is distinct from expected.operating_costs
    or mart.ride_running_costs is distinct from expected.ride_running_costs
    or mart.staff_wages is distinct from expected.staff_wages
    or mart.stock_costs is distinct from expected.stock_costs
    or mart.marketing_costs is distinct from expected.marketing_costs
    or mart.research_costs is distinct from expected.research_costs
    or mart.capital_spending is distinct from expected.capital_spending
    or mart.interest_costs is distinct from expected.interest_costs
    or mart.guest_visits is distinct from expected.guest_visits
    or mart.operating_days is distinct from expected.operating_days
    or mart.days_with_visits is distinct from expected.days_with_visits
    or mart.park_rating_sum is distinct from expected.park_rating_sum
    or mart.statements_kept is distinct from expected.statements_kept
    or mart.months_checked is distinct from expected.months_checked
