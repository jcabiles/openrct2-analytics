-- A row means a park-year keeps more statements than it expects, which
-- would show on the page as "8 of 7". The first reportable month is
-- derived from what the first captured day can carry, so this should hold.
select
    park_id,
    company_year,
    statements_kept,
    statements_expected
from {{ ref("int_park_years__year_close") }}
where statements_kept > statements_expected
