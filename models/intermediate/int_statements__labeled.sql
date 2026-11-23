{#
    One row per statement event in stg_finance_month, kept or abandoned,
    with the park's company year, the company date the statement closes and
    the event's place on the kept timeline (ADR 0024; R4 to R6 of `git show 6eafb6d:docs/ai-dlc/specs/save-lineage.md`). The company
    year comes from statement_year, never the carrying event's game_year,
    because a statement written in the day-1 callback of a month closes the
    month before it. The kept selection is done downstream. Labels are
    recomputed on every build, so a later session can change them.
#}
with

statements as (
    select
        stg_finance_month.schema_version,
        stg_finance_month.event_type,
        stg_finance_month.plugin_version,
        stg_finance_month.park_id,
        stg_finance_month.session_id,
        stg_finance_month.seq,
        stg_finance_month.event_id,
        stg_finance_month.game_year,
        stg_finance_month.game_month,
        stg_finance_month.game_day,
        stg_finance_month.game_ticks_elapsed,
        stg_finance_month.emitted_at,
        stg_finance_month.received_at,
        stg_finance_month._raw_file,
        stg_finance_month._raw_line,
        stg_finance_month.statement_year,
        stg_finance_month.statement_month,
        stg_finance_month.ride_construction_usd,
        stg_finance_month.ride_runningcosts_usd,
        stg_finance_month.land_purchase_usd,
        stg_finance_month.landscaping_usd,
        stg_finance_month.park_entrance_tickets_usd,
        stg_finance_month.park_ride_tickets_usd,
        stg_finance_month.shop_sales_usd,
        stg_finance_month.shop_stock_usd,
        stg_finance_month.food_drink_sales_usd,
        stg_finance_month.food_drink_stock_usd,
        stg_finance_month.wages_usd,
        stg_finance_month.marketing_usd,
        stg_finance_month.research_usd,
        stg_finance_month.interest_usd,
        stg_finance_month.cash_usd,
        stg_finance_month.bank_loan_usd,
        stg_finance_month.new_month_booked_usd,
        years.company_year,
        years.company_start_year,
        years.game_year_origin,
        case
            when years.mapping_status != 'mapped'
                then years.mapping_status
            when stg_finance_month.statement_month not between 0 and 7
                then 'game_month_out_of_range'
            when years.mapping_status = 'mapped' then 'mapped'
        end as mapping_status,
        {{ timeline_status('stg_finance_month.seq', 'lineage') }}
            as timeline_status
    from {{ ref("stg_finance_month") }} as stg_finance_month
    left join {{ ref("int_sessions__lineage") }} as lineage
        on stg_finance_month.session_id = lineage.session_id
    left join {{ ref("int_park_years__registry_mapped") }} as years
        on
            stg_finance_month.park_id = years.park_id
            and stg_finance_month.statement_year = years.game_year
)

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
    company_start_year,
    game_year_origin,
    case when mapping_status = 'mapped' then company_year end as company_year,
    {{ company_date("company_year", "statement_month", "1") }}
        as statement_company_date,
    mapping_status,
    timeline_status
from statements
