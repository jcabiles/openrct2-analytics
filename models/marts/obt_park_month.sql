{#
    One row per park per kept statement month, on the company calendar. Park-days
    are rolled up by game month before they are joined to statements, so a
    statement month with no kept park-days remains present with zero counts and
    null visits and rating totals. The casts keep contract types explicit.
#}
with

statements as (
    select
        park_month_key,
        park_id,
        statement_year,
        statement_month,
        company_year,
        statement_company_date,
        operating_profit,
        park_ride_tickets_usd,
        food_drink_sales_usd,
        shop_sales_usd,
        park_entrance_tickets_usd,
        ride_runningcosts_usd,
        wages_usd,
        shop_stock_usd,
        food_drink_stock_usd,
        marketing_usd,
        research_usd,
        capital_spending,
        interest_usd
    from {{ ref("fct_park_month") }}
),

park_days as (
    select
        park_id,
        game_year,
        game_month,
        park_day_key,
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

joined as (
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

subtotals as (
    select
        park_month_key,
        park_id,
        statement_year,
        statement_month,
        company_year,
        statement_company_date,
        operating_profit,
        park_ride_tickets_usd,
        food_drink_sales_usd,
        shop_sales_usd,
        park_entrance_tickets_usd,
        ride_runningcosts_usd,
        wages_usd,
        shop_stock_usd,
        food_drink_stock_usd,
        marketing_usd,
        research_usd,
        capital_spending,
        interest_usd,
        operating_days,
        days_with_visits,
        guest_visits,
        park_rating_sum,
        ride_runningcosts_usd as ride_running_costs,
        wages_usd as staff_wages,
        marketing_usd as marketing_costs,
        research_usd as research_costs,
        park_ride_tickets_usd
        + food_drink_sales_usd
        + shop_sales_usd
        + park_entrance_tickets_usd as operating_revenue,
        ride_runningcosts_usd
        + wages_usd
        + shop_stock_usd
        + food_drink_stock_usd
        + marketing_usd
        + research_usd as operating_costs,
        shop_stock_usd + food_drink_stock_usd as stock_costs
    from joined
),

derived as (
    select
        park_month_key,
        park_id,
        statement_year,
        statement_month,
        company_year,
        statement_company_date,
        operating_profit,
        park_ride_tickets_usd,
        food_drink_sales_usd,
        shop_sales_usd,
        park_entrance_tickets_usd,
        ride_runningcosts_usd,
        wages_usd,
        shop_stock_usd,
        food_drink_stock_usd,
        marketing_usd,
        research_usd,
        capital_spending,
        interest_usd,
        operating_days,
        days_with_visits,
        guest_visits,
        park_rating_sum,
        ride_running_costs,
        staff_wages,
        marketing_costs,
        research_costs,
        operating_revenue,
        operating_costs,
        stock_costs,
        cast(
            park_rating_sum / nullif(coalesce(operating_days, 0), 0)
            as decimal(18, 2)
        ) as average_park_rating,
        cast(
            operating_revenue / nullif(guest_visits, 0)
            as decimal(18, 2)
        ) as revenue_per_visit,
        cast(
            park_ride_tickets_usd / nullif(guest_visits, 0)
            as decimal(18, 2)
        ) as ride_revenue_per_visit,
        cast(
            food_drink_sales_usd / nullif(guest_visits, 0)
            as decimal(18, 2)
        ) as food_drink_revenue_per_visit,
        cast(
            shop_sales_usd / nullif(guest_visits, 0)
            as decimal(18, 2)
        ) as merchandise_revenue_per_visit,
        cast(
            park_entrance_tickets_usd / nullif(guest_visits, 0)
            as decimal(18, 2)
        ) as entrance_revenue_per_visit,
        cast(
            100 * park_ride_tickets_usd / nullif(operating_revenue, 0)
            as decimal(18, 2)
        ) as ride_revenue_share_pct,
        cast(
            100 * food_drink_sales_usd / nullif(operating_revenue, 0)
            as decimal(18, 2)
        ) as food_drink_revenue_share_pct,
        cast(
            100 * shop_sales_usd / nullif(operating_revenue, 0)
            as decimal(18, 2)
        ) as merchandise_revenue_share_pct,
        cast(
            100 * park_entrance_tickets_usd / nullif(operating_revenue, 0)
            as decimal(18, 2)
        ) as entrance_revenue_share_pct,
        cast(
            operating_revenue / nullif(coalesce(operating_days, 0), 0)
            as decimal(18, 2)
        ) as revenue_per_operating_day
    from subtotals
)

select
    park_month_key,
    park_id,
    statement_year,
    statement_month,
    company_year,
    statement_company_date as company_date,
    cast(operating_profit as decimal(18, 2)) as operating_profit,
    cast(operating_revenue as decimal(18, 2)) as operating_revenue,
    cast(park_ride_tickets_usd as decimal(18, 2)) as ride_revenue,
    cast(food_drink_sales_usd as decimal(18, 2)) as food_drink_revenue,
    cast(shop_sales_usd as decimal(18, 2)) as merchandise_revenue,
    cast(park_entrance_tickets_usd as decimal(18, 2)) as entrance_revenue,
    cast(operating_costs as decimal(18, 2)) as operating_costs,
    cast(ride_running_costs as decimal(18, 2)) as ride_running_costs,
    cast(staff_wages as decimal(18, 2)) as staff_wages,
    cast(stock_costs as decimal(18, 2)) as stock_costs,
    cast(marketing_costs as decimal(18, 2)) as marketing_costs,
    cast(research_costs as decimal(18, 2)) as research_costs,
    cast(capital_spending as decimal(18, 2)) as capital_spending,
    cast(interest_usd as decimal(18, 2)) as interest_costs,
    cast(guest_visits as bigint) as guest_visits,
    cast(coalesce(operating_days, 0) as integer) as operating_days,
    cast(coalesce(days_with_visits, 0) as integer) as days_with_visits,
    cast(park_rating_sum as bigint) as park_rating_sum,
    average_park_rating,
    revenue_per_visit,
    ride_revenue_per_visit,
    food_drink_revenue_per_visit,
    merchandise_revenue_per_visit,
    entrance_revenue_per_visit,
    ride_revenue_share_pct,
    food_drink_revenue_share_pct,
    merchandise_revenue_share_pct,
    entrance_revenue_share_pct,
    revenue_per_operating_day
from derived
