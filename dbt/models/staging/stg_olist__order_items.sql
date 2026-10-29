select
    order_id,
    cast(order_item_id as integer)            as order_item_id,
    order_id || '-' || order_item_id          as order_item_key,
    product_id,
    seller_id,
    cast(shipping_limit_date as timestamp)    as shipping_limit_at,
    cast(price as decimal(12, 2))             as price_brl,
    cast(freight_value as decimal(12, 2))     as freight_brl
from {{ source('olist', 'order_items') }}
