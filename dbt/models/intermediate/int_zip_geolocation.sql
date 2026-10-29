-- One row per zip prefix. The raw table repeats each prefix ~53 times on average
-- (1,000,163 rows / 19,015 prefixes), with jittered coordinates and spelling variants
-- of the city. We drop points outside Brazil, then take the median coordinate and the
-- most frequent city/state per prefix.
select
    zip_prefix,
    median(lat)          as lat,
    median(lng)          as lng,
    mode(city)           as city,
    mode(state)          as state,
    count(*)             as n_raw_rows,
    count(distinct (lat, lng)) as n_distinct_points
from {{ ref('stg_olist__geolocation') }}
where is_inside_brazil
group by zip_prefix
