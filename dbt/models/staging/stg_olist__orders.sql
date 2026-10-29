-- Typed orders. Timestamps are local Brazil time without zone (as published).
select
    order_id,
    customer_id,
    order_status,
    cast(order_purchase_timestamp as timestamp)       as purchased_at,
    cast(order_approved_at as timestamp)              as approved_at,
    cast(order_delivered_carrier_date as timestamp)   as delivered_to_carrier_at,
    cast(order_delivered_customer_date as timestamp)  as delivered_to_customer_at,
    -- The estimate is always midnight: it is a promised *date*, so keep it as a date.
    cast(cast(order_estimated_delivery_date as timestamp) as date) as estimated_delivery_date,
    _loaded_at
from {{ source('olist', 'orders') }}
