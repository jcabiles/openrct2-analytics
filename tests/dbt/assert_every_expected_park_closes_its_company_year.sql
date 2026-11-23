{{ config(severity=sample_warn_severity(), store_failures=true) }}

-- Warn on ci and dev over the committed sample; error elsewhere. This checks
-- which company years appear in obt_company_year against the close register's
-- closed flag, and incomplete park-years in the register.
-- The hint points to lost statements or an early registry start.
with

register as (
    select
        park_id,
        company_year,
        statements_kept,
        statements_expected,
        missing_statement_months,
        close_status,
        first_captured_company_year,
        is_company_year_closed
    from {{ ref("int_park_years__year_close") }}
),

incomplete_park_years as (
    select
        'park_year_incomplete' as failure_kind,
        park_id,
        company_year,
        statements_kept,
        statements_expected,
        missing_statement_months,
        case
            when company_year < first_captured_company_year
                then
                    'The registry start year is earlier than the park''s '
                    || 'first captured day; '
                    || 'the registry row was most likely entered wrong and '
                    || 'needs a corrected delivery (ADR 0023).'
            else
                'Missing statement months ' || missing_statement_months
                || '; those before the last kept statement of the year, '
                || 'or all of them once a later year has a statement, are lost.'
        end as hint
    from register
    where close_status = 'incomplete'
),

closed_company_years as (
    select distinct company_year
    from register
    where is_company_year_closed
),

company_years_not_closed as (
    select
        'company_year_not_closed' as failure_kind,
        cast(null as varchar) as park_id,
        company_years.company_year,
        cast(null as integer) as statements_kept,
        cast(null as integer) as statements_expected,
        cast(null as varchar) as missing_statement_months,
        'The company year is not marked closed by the '
        || 'park-year register.' as hint
    from {{ ref("obt_company_year") }} as company_years
    left join closed_company_years as closed_years
        on company_years.company_year = closed_years.company_year
    where closed_years.company_year is null
)

select * from incomplete_park_years
union all
select * from company_years_not_closed
