{{ config(severity="error") }}

-- Returns a row (a failure) for each kept monthly statement without a
-- company date: the registry cannot map it (no registry row, a statement
-- year before the origin, or a statement month outside 0 to 7), or it is
-- marked mapped but its company year or company date is null. Abandoned
-- statements are not checked. The severity is error on every target.
select
    park_id,
    session_id,
    event_id,
    statement_year,
    statement_month,
    mapping_status,
    statement_company_date,
    company_year
from {{ ref("int_statements__labeled") }}
where
    timeline_status = 'kept'
    and (
        mapping_status != 'mapped'
        or statement_company_date is null
        or company_year is null
    )
