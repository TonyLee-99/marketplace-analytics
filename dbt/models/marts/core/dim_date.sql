with days as (
    select cast(d as date) as date_day
    from range(date '2016-09-01', date '2019-01-01', interval 1 day) as t(d)
)

select
    d.date_day,
    cast(date_trunc('week', d.date_day) as date)   as week_start,
    cast(date_trunc('month', d.date_day) as date)  as month_start,
    cast(date_trunc('quarter', d.date_day) as date) as quarter_start,
    year(d.date_day)                               as year,
    month(d.date_day)                              as month,
    dayofweek(d.date_day)                          as day_of_week,   -- 0 = Sunday
    dayname(d.date_day)                            as day_name,
    dayofweek(d.date_day) in (0, 6)                as is_weekend,
    e.event_name,
    e.event_type,
    e.event_name is not null                       as is_known_event,
    -- Data coverage flag: Olist order capture is sparse before 2017-01 and after 2018-08.
    d.date_day between date '2017-01-01' and date '2018-08-31' as is_in_reliable_window
from days as d
left join {{ ref('retail_events') }} as e on d.date_day = e.event_date
