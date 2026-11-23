with

landing_finance_month as (
    select
        schema_version,
        event_type,
        plugin_version,
        park_id,
        session_id,
        seq,
        event_id,
        game_year,
        game_month,
        game_day,
        game_ticks_elapsed,
        emitted_at,
        received_at,
        _raw_file,
        _raw_line,
        statement_year,
        statement_month,
        ride_construction_tenths,
        ride_runningcosts_tenths,
        land_purchase_tenths,
        landscaping_tenths,
        park_entrance_tickets_tenths,
        park_ride_tickets_tenths,
        shop_sales_tenths,
        shop_stock_tenths,
        food_drink_sales_tenths,
        food_drink_stock_tenths,
        wages_tenths,
        marketing_tenths,
        research_tenths,
        interest_tenths,
        cash_tenths,
        bank_loan_tenths,
        new_month_booked_tenths
    from {{ source('landing', 'finance_month') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by event_id
            order by received_at, _raw_file, _raw_line
        ) as delivery_rank
    from landing_finance_month
),

final as (
    select
        schema_version,
        event_type,
        plugin_version,
        park_id,
        session_id,
        seq,
        event_id,
        game_year,
        game_month,
        game_day,
        game_ticks_elapsed,
        emitted_at,
        received_at,
        _raw_file,
        _raw_line,
        statement_year,
        statement_month,
        {{ tenths_to_usd('ride_construction_tenths') }}
            as ride_construction_usd,
        {{ tenths_to_usd('ride_runningcosts_tenths') }}
            as ride_runningcosts_usd,
        {{ tenths_to_usd('land_purchase_tenths') }} as land_purchase_usd,
        {{ tenths_to_usd('landscaping_tenths') }} as landscaping_usd,
        {{ tenths_to_usd('park_entrance_tickets_tenths') }}
            as park_entrance_tickets_usd,
        {{ tenths_to_usd('park_ride_tickets_tenths') }}
            as park_ride_tickets_usd,
        {{ tenths_to_usd('shop_sales_tenths') }} as shop_sales_usd,
        {{ tenths_to_usd('shop_stock_tenths') }} as shop_stock_usd,
        {{ tenths_to_usd('food_drink_sales_tenths') }} as food_drink_sales_usd,
        {{ tenths_to_usd('food_drink_stock_tenths') }} as food_drink_stock_usd,
        {{ tenths_to_usd('wages_tenths') }} as wages_usd,
        {{ tenths_to_usd('marketing_tenths') }} as marketing_usd,
        {{ tenths_to_usd('research_tenths') }} as research_usd,
        {{ tenths_to_usd('interest_tenths') }} as interest_usd,
        {{ tenths_to_usd('cash_tenths') }} as cash_usd,
        {{ tenths_to_usd('bank_loan_tenths') }} as bank_loan_usd,
        {{ tenths_to_usd('new_month_booked_tenths') }}
            as new_month_booked_usd
    from ranked
    where delivery_rank = 1
)

select * from final
