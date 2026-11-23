{#
    One row per closed company year, summed across parks.
    Input is the park-year table only: rows whose company year the register marks closed,
    including partial first seasons. Sums are summed; every ratio is recomputed from the sums.
#}
with

park_years as (
    select
        park_id,
        company_year,
        is_partial_first_season,
        statements_kept,
        months_checked,
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
    from {{ ref("obt_park_year") }}
    where is_company_year_closed
),

by_company_year as (
    select
        company_year,
        count(distinct park_id) as parks_reporting,
        count(
            distinct case when is_partial_first_season then park_id end
        ) as parks_partial_first_season,
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
    from park_years
    group by company_year
)

select
    cast(company_year as integer) as company_year,
    cast(parks_reporting as integer) as parks_reporting,
    cast(parks_partial_first_season as integer) as parks_partial_first_season,
    cast(statements_kept as integer) as statements_kept,
    cast(months_checked as integer) as months_checked,
    cast(operating_profit as decimal(18, 2)) as operating_profit,
    cast(operating_revenue as decimal(18, 2)) as operating_revenue,
    cast(ride_revenue as decimal(18, 2)) as ride_revenue,
    cast(food_drink_revenue as decimal(18, 2)) as food_drink_revenue,
    cast(merchandise_revenue as decimal(18, 2)) as merchandise_revenue,
    cast(entrance_revenue as decimal(18, 2)) as entrance_revenue,
    cast(operating_costs as decimal(18, 2)) as operating_costs,
    cast(ride_running_costs as decimal(18, 2)) as ride_running_costs,
    cast(staff_wages as decimal(18, 2)) as staff_wages,
    cast(stock_costs as decimal(18, 2)) as stock_costs,
    cast(marketing_costs as decimal(18, 2)) as marketing_costs,
    cast(research_costs as decimal(18, 2)) as research_costs,
    cast(capital_spending as decimal(18, 2)) as capital_spending,
    cast(interest_costs as decimal(18, 2)) as interest_costs,
    cast(guest_visits as bigint) as guest_visits,
    cast(operating_days as integer) as operating_days,
    cast(days_with_visits as integer) as days_with_visits,
    cast(park_rating_sum as bigint) as park_rating_sum,
    cast(
        park_rating_sum / nullif(operating_days, 0)
        as decimal(18, 2)
    ) as average_park_rating,
    cast(
        operating_revenue / nullif(guest_visits, 0)
        as decimal(18, 2)
    ) as revenue_per_visit,
    cast(
        ride_revenue / nullif(guest_visits, 0)
        as decimal(18, 2)
    ) as ride_revenue_per_visit,
    cast(
        food_drink_revenue / nullif(guest_visits, 0)
        as decimal(18, 2)
    ) as food_drink_revenue_per_visit,
    cast(
        merchandise_revenue / nullif(guest_visits, 0)
        as decimal(18, 2)
    ) as merchandise_revenue_per_visit,
    cast(
        operating_revenue / nullif(operating_days, 0)
        as decimal(18, 2)
    ) as revenue_per_operating_day
from by_company_year
