{{ config(severity="error") }}

-- Returns a row for each company month with a missing side, a sum mismatch,
-- or a rating or ratio that does not match its pooled company-month formula.
with

expected as (
    select
        company_date,
        count(*) as parks_reporting,
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
    from {{ ref("obt_park_month") }}
    group by company_date
)

select
    expected.parks_reporting as expected_parks_reporting,
    mart.parks_reporting as mart_parks_reporting,
    expected.operating_profit as expected_operating_profit,
    mart.operating_profit as mart_operating_profit,
    coalesce(expected.company_date, mart.company_date) as company_date
from expected
full outer join {{ ref("obt_company_month") }} as mart
    on expected.company_date = mart.company_date
where
    expected.company_date is null
    or mart.company_date is null
    or mart.parks_reporting is distinct from expected.parks_reporting
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
    or mart.average_park_rating is distinct from cast(
        expected.park_rating_sum
        / nullif(coalesce(expected.operating_days, 0), 0)
        as decimal(18, 2)
    )
    or mart.revenue_per_visit is distinct from cast(
        expected.operating_revenue / nullif(expected.guest_visits, 0)
        as decimal(18, 2)
    )
    or mart.ride_revenue_per_visit is distinct from cast(
        expected.ride_revenue / nullif(expected.guest_visits, 0)
        as decimal(18, 2)
    )
    or mart.food_drink_revenue_per_visit is distinct from cast(
        expected.food_drink_revenue / nullif(expected.guest_visits, 0)
        as decimal(18, 2)
    )
    or mart.merchandise_revenue_per_visit is distinct from cast(
        expected.merchandise_revenue / nullif(expected.guest_visits, 0)
        as decimal(18, 2)
    )
    or mart.revenue_per_operating_day is distinct from cast(
        expected.operating_revenue
        / nullif(coalesce(expected.operating_days, 0), 0)
        as decimal(18, 2)
    )
