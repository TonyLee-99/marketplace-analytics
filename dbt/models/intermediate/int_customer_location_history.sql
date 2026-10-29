-- SCD Type 2 history of a person's delivery address, derived from order events.
-- Olist issues a new customer_id per order, so a person (customer_unique_id) who moves
-- shows up with a new zip on a later order. Each address version is valid from the first
-- order placed with it until the next version starts.
with events as (
    select
        c.customer_unique_id,
        c.customer_zip_prefix,
        c.customer_city,
        c.customer_state,
        o.purchased_at,
        o.order_id
    from {{ ref('stg_olist__orders') }} as o
    join {{ ref('stg_olist__customers') }} as c using (customer_id)
),

flagged as (
    select
        *,
        case
            when lag(customer_zip_prefix) over w is null then 1
            when lag(customer_zip_prefix) over w <> customer_zip_prefix then 1
            else 0
        end as is_new_version
    from events
    window w as (partition by customer_unique_id order by purchased_at, order_id)
),

versioned as (
    select
        *,
        sum(is_new_version) over (
            partition by customer_unique_id order by purchased_at, order_id
            rows between unbounded preceding and current row
        ) as version_number
    from flagged
),

collapsed as (
    select
        customer_unique_id,
        version_number,
        any_value(customer_zip_prefix) as customer_zip_prefix,
        any_value(customer_city)       as customer_city,
        any_value(customer_state)      as customer_state,
        min(purchased_at)              as valid_from
    from versioned
    group by customer_unique_id, version_number
)

select
    md5(customer_unique_id || '-' || version_number) as customer_location_sk,
    customer_unique_id,
    version_number,
    customer_zip_prefix,
    customer_city,
    customer_state,
    valid_from,
    lead(valid_from) over (partition by customer_unique_id order by version_number) as valid_to,
    lead(valid_from) over (partition by customer_unique_id order by version_number) is null as is_current
from collapsed
