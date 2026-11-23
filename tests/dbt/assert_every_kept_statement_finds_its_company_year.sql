{{ config(severity="error") }}

-- Returns kept statements with no registry year or a mapped company-year
-- mismatch.
select
    labeled.event_id,
    labeled.park_id,
    labeled.statement_year,
    labeled.mapping_status,
    labeled.company_year,
    registry_year.company_year as registry_company_year
from {{ ref("int_statements__labeled") }} as labeled
left join {{ ref("int_park_years__registry_mapped") }} as registry_year
    on
        labeled.park_id = registry_year.park_id
        and labeled.statement_year = registry_year.game_year
where
    labeled.timeline_status = 'kept'
    and (
        registry_year.park_id is null
        or (
            labeled.mapping_status = 'mapped'
            and (
                labeled.company_year is null
                or labeled.company_year is distinct from
                registry_year.company_year
            )
        )
    )
