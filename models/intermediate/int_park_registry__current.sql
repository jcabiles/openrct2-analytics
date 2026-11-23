{#
    Keeps the one registry row per park that is the latest word on it: the
    rows of the park's current delivery, as the history model marks them.
    Two rows for one park in that delivery are kept, and the key test on
    park_id fails the build until a later delivery cures them.
#}
select
    park_id,
    company_start_year,
    game_year_origin,
    data_set,
    note,
    delivered_on,
    delivery_file,
    valid_from
from {{ ref("int_park_registry__history") }}
where is_current
