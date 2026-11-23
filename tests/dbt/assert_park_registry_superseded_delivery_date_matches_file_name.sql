-- Warns about each row of a superseded delivery whose delivered_on differs
-- from the date in its file name. A later delivery already replaced it, so
-- the build is not blocked (the current-delivery test is the error).
{{ config(severity="warn") }}

select
    park_id,
    delivery_file,
    delivered_on,
    file_date
from {{ ref("int_park_registry__history") }}
where
    not is_current
    and {{ dbt.cast("delivered_on", dbt.type_string()) }} != file_date
