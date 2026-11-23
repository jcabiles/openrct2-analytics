{{ config(severity="error") }}

-- Require whole March-to-October months and complete 245-day company seasons.
with date_rows as (
    select
        company_date,
        company_year,
        company_month,
        day_of_month,
        is_month_end
    from {{ ref("dim_date") }}
),

month_counts as (
    select
        company_year,
        company_month,
        count(*) as row_count,
        max(case when is_month_end then day_of_month end) as month_length
    from date_rows
    group by company_year, company_month
),

season_counts as (
    select
        company_year,
        count(*) as row_count,
        max(case when company_month = 3 then 1 else 0 end) as has_march,
        max(case when company_month = 10 then 1 else 0 end) as has_october
    from date_rows
    group by company_year
)

select
    'company_month_out_of_range' as failure,
    company_date,
    company_month,
    company_year
from date_rows
where company_month < 3 or company_month > 10

union all

select
    'company_month_not_whole' as failure,
    cast(null as date) as company_date,
    company_month,
    company_year
from month_counts
where month_length is null or row_count != month_length

union all

select
    'company_year_not_245_days' as failure,
    cast(null as date) as company_date,
    cast(null as integer) as company_month,
    company_year
from season_counts
where has_march = 1 and has_october = 1 and row_count != 245
