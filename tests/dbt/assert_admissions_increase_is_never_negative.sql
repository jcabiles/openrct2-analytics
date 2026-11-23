-- A rewound admissions counter never counts as negative visits.
{{ config(severity='error') }}

select
    park_day_key,
    session_id,
    seq,
    admissions_increase
from {{ ref('int_park_days__kept') }}
where admissions_increase < 0
