{{ config(severity="error") }}

-- Returns each park-month key where the mart differs from its statement,
-- game-month park-days, or its own arithmetic.
with

statements as (
    select
        park_month_key,
        park_id,
        statement_year,
        statement_month,
        statement_company_date,
        sum(operating_profit) as operating_profit,
        sum(
            park_ride_tickets_usd
            + food_drink_sales_usd
            + shop_sales_usd
            + park_entrance_tickets_usd
        ) as operating_revenue,
        sum(park_ride_tickets_usd) as ride_revenue,
        sum(food_drink_sales_usd) as food_drink_revenue,
        sum(shop_sales_usd) as merchandise_revenue,
        sum(park_entrance_tickets_usd) as entrance_revenue,
        sum(
            ride_runningcosts_usd
            + wages_usd
            + shop_stock_usd
            + food_drink_stock_usd
            + marketing_usd
            + research_usd
        ) as operating_costs,
        sum(ride_runningcosts_usd) as ride_running_costs,
        sum(wages_usd) as staff_wages,
        sum(shop_stock_usd + food_drink_stock_usd) as stock_costs,
        sum(marketing_usd) as marketing_costs,
        sum(research_usd) as research_costs,
        sum(capital_spending) as capital_spending,
        sum(interest_usd) as interest_costs
    from {{ ref("fct_park_month") }}
    group by
        park_month_key,
        park_id,
        statement_year,
        statement_month,
        statement_company_date
),

park_days as (
    select
        park_id,
        game_year,
        game_month,
        park_day_key,
        company_date,
        admissions_increase,
        park_rating
    from {{ ref("fct_park_day") }}
),

days_by_month as (
    select
        park_id,
        game_year,
        game_month,
        count(park_day_key) as operating_days,
        count(admissions_increase) as days_with_visits,
        sum(admissions_increase) as guest_visits,
        sum(park_rating) as park_rating_sum
    from park_days
    group by park_id, game_year, game_month
),

expected as (
    select
        statements.*,
        days_by_month.operating_days,
        days_by_month.days_with_visits,
        days_by_month.guest_visits,
        days_by_month.park_rating_sum
    from statements
    left join days_by_month
        on
            statements.park_id = days_by_month.park_id
            and statements.statement_year = days_by_month.game_year
            and statements.statement_month = days_by_month.game_month
),

joined as (
    select
        expected.*,
        mart.park_month_key as mart_park_month_key,
        mart.park_id as mart_park_id,
        mart.statement_year as mart_statement_year,
        mart.statement_month as mart_statement_month,
        mart.company_date as mart_company_date,
        mart.operating_profit as mart_operating_profit,
        mart.operating_revenue as mart_operating_revenue,
        mart.ride_revenue as mart_ride_revenue,
        mart.food_drink_revenue as mart_food_drink_revenue,
        mart.merchandise_revenue as mart_merchandise_revenue,
        mart.entrance_revenue as mart_entrance_revenue,
        mart.operating_costs as mart_operating_costs,
        mart.ride_running_costs as mart_ride_running_costs,
        mart.staff_wages as mart_staff_wages,
        mart.stock_costs as mart_stock_costs,
        mart.marketing_costs as mart_marketing_costs,
        mart.research_costs as mart_research_costs,
        mart.capital_spending as mart_capital_spending,
        mart.interest_costs as mart_interest_costs,
        mart.operating_days as mart_operating_days,
        mart.days_with_visits as mart_days_with_visits,
        mart.guest_visits as mart_guest_visits,
        mart.park_rating_sum as mart_park_rating_sum,
        mart.average_park_rating,
        mart.revenue_per_visit,
        mart.ride_revenue_per_visit,
        mart.food_drink_revenue_per_visit,
        mart.merchandise_revenue_per_visit,
        mart.revenue_per_operating_day
    from expected
    full outer join {{ ref("obt_park_month") }} as mart
        on expected.park_month_key = mart.park_month_key
)

select coalesce(park_month_key, mart_park_month_key) as park_month_key
from joined
where
    park_month_key is null
    or mart_park_month_key is null
    or mart_park_id is distinct from park_id
    or mart_statement_year is distinct from statement_year
    or mart_statement_month is distinct from statement_month
    or mart_company_date is distinct from statement_company_date
    or mart_operating_profit is distinct from operating_profit
    or mart_operating_revenue is distinct from operating_revenue
    or mart_ride_revenue is distinct from ride_revenue
    or mart_food_drink_revenue is distinct from food_drink_revenue
    or mart_merchandise_revenue is distinct from merchandise_revenue
    or mart_entrance_revenue is distinct from entrance_revenue
    or mart_operating_costs is distinct from operating_costs
    or mart_ride_running_costs is distinct from ride_running_costs
    or mart_staff_wages is distinct from staff_wages
    or mart_stock_costs is distinct from stock_costs
    or mart_marketing_costs is distinct from marketing_costs
    or mart_research_costs is distinct from research_costs
    or mart_capital_spending is distinct from capital_spending
    or mart_interest_costs is distinct from interest_costs
    or mart_operating_revenue + mart_operating_costs
    is distinct from mart_operating_profit
    or mart_operating_days is distinct from cast(
        coalesce(operating_days, 0) as integer
    )
    or mart_days_with_visits is distinct from cast(
        coalesce(days_with_visits, 0) as integer
    )
    or mart_guest_visits is distinct from cast(guest_visits as bigint)
    or mart_park_rating_sum is distinct from cast(
        park_rating_sum as bigint
    )
    or average_park_rating is distinct from cast(
        mart_park_rating_sum / nullif(mart_operating_days, 0)
        as decimal(18, 2)
    )
    or revenue_per_visit is distinct from cast(
        mart_operating_revenue / nullif(mart_guest_visits, 0)
        as decimal(18, 2)
    )
    or ride_revenue_per_visit is distinct from cast(
        mart_ride_revenue / nullif(mart_guest_visits, 0)
        as decimal(18, 2)
    )
    or food_drink_revenue_per_visit is distinct from cast(
        mart_food_drink_revenue / nullif(mart_guest_visits, 0)
        as decimal(18, 2)
    )
    or merchandise_revenue_per_visit is distinct from cast(
        mart_merchandise_revenue / nullif(mart_guest_visits, 0)
        as decimal(18, 2)
    )
    or revenue_per_operating_day is distinct from cast(
        mart_operating_revenue / nullif(mart_operating_days, 0)
        as decimal(18, 2)
    )
    or exists (
        select 1
        from park_days
        where
            park_days.park_id = joined.park_id
            and park_days.game_year = joined.statement_year
            and park_days.game_month = joined.statement_month
            and date_trunc('month', park_days.company_date)
            is distinct from joined.statement_company_date
    )
