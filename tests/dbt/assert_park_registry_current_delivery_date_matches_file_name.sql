-- Returns a row (a failure) for each row of a park's current delivery whose
-- delivered_on differs from the date in its file name. Only the current
-- delivery fails the build; a later delivery cures a bad one, and the
-- superseded ones only warn (the superseded test).
select
    park_id,
    delivery_file,
    delivered_on,
    file_date
from {{ ref("int_park_registry__history") }}
where
    is_current
    and {{ dbt.cast("delivered_on", dbt.type_string()) }} != file_date
