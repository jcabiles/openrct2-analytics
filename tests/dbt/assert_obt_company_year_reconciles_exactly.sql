{{ config(severity="error") }}

-- Returns a row (a failure) for each company year where obt_company_year
-- disagrees with its sum of closed obt_park_year rows, or where the closed
-- year set differs from the register. It catches a missing or extra year,
-- park or sum. It cannot catch a park year already wrong in both tables.
-- On the committed sample obt_company_year is empty, so only the park-year
-- tie is exercised by the sample build.
with

closed_years as (
    select distinct company_year
    from {{ ref("int_park_years__year_close") }}
    where is_company_year_closed
),

expected as (
    select
        company_year,
        count(distinct park_id) as parks_reporting,
        count(distinct case when is_partial_first_season then park_id end)
            as parks_partial_first_season,
        sum(statements_kept) as statements_kept,
        sum(months_checked) as months_checked,
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
    from {{ ref("obt_park_year") }}
    where is_company_year_closed
    group by company_year
),

comparison as (
    select
        closed_years.company_year as register_company_year,
        expected.company_year as expected_company_year,
        mart.company_year as mart_company_year,
        expected.parks_reporting as expected_parks_reporting,
        mart.parks_reporting as mart_parks_reporting,
        expected.parks_partial_first_season
            as expected_parks_partial_first_season,
        mart.parks_partial_first_season as mart_parks_partial_first_season,
        expected.statements_kept as expected_statements_kept,
        mart.statements_kept as mart_statements_kept,
        expected.months_checked as expected_months_checked,
        mart.months_checked as mart_months_checked,
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
        coalesce(
            closed_years.company_year,
            expected.company_year,
            mart.company_year
        )
            as company_year
    from closed_years
    full outer join expected
        on closed_years.company_year = expected.company_year
    full outer join {{ ref("obt_company_year") }} as mart
        on
            coalesce(closed_years.company_year, expected.company_year)
            = mart.company_year
)

select *
from comparison
where
    register_company_year is null
    or expected_company_year is null
    or mart_company_year is null
    or mart_parks_reporting is distinct from expected_parks_reporting
    or (
        mart_parks_partial_first_season
        is distinct from expected_parks_partial_first_season
    )
    or mart_statements_kept is distinct from expected_statements_kept
    or mart_months_checked is distinct from expected_months_checked
    or mart_operating_profit is distinct from expected_operating_profit
    or mart_operating_revenue is distinct from expected_operating_revenue
    or mart_ride_revenue is distinct from expected_ride_revenue
    or mart_food_drink_revenue is distinct from expected_food_drink_revenue
    or mart_merchandise_revenue is distinct from expected_merchandise_revenue
    or mart_entrance_revenue is distinct from expected_entrance_revenue
    or mart_operating_costs is distinct from expected_operating_costs
    or mart_ride_running_costs is distinct from expected_ride_running_costs
    or mart_staff_wages is distinct from expected_staff_wages
    or mart_stock_costs is distinct from expected_stock_costs
    or mart_marketing_costs is distinct from expected_marketing_costs
    or mart_research_costs is distinct from expected_research_costs
    or mart_capital_spending is distinct from expected_capital_spending
    or mart_interest_costs is distinct from expected_interest_costs
    or mart_guest_visits is distinct from expected_guest_visits
    or mart_operating_days is distinct from expected_operating_days
    or mart_days_with_visits is distinct from expected_days_with_visits
    or mart_park_rating_sum is distinct from expected_park_rating_sum
