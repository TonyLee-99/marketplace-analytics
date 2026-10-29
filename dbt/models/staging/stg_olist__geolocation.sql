-- Raw geolocation: ~1.0M rows for 19k zip prefixes (many exact duplicates, some points
-- outside Brazil). Deduplicated in int_zip_geolocation.
select
    geolocation_zip_code_prefix                     as zip_prefix,
    cast(geolocation_lat as double)                 as lat,
    cast(geolocation_lng as double)                 as lng,
    lower(strip_accents(trim(geolocation_city)))    as city,
    upper(geolocation_state)                        as state,
    -- Brazil bounding box (approx.): lat -34..+6, lng -74..-34
    cast(geolocation_lat as double) between -34 and 6
        and cast(geolocation_lng as double) between -74 and -34 as is_inside_brazil
from {{ source('olist', 'geolocation') }}
