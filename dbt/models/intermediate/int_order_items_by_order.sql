-- Order-level rollup of items. "Primary" seller / category = the one with the largest
-- price share in the order (1,278 orders have more than one seller).
with items as (
    select i.*, p.category
    from {{ ref('stg_olist__order_items') }} as i
    left join {{ ref('stg_olist__products') }} as p using (product_id)
),

seller_share as (
    select order_id, seller_id, sum(price_brl) as seller_price
    from items group by order_id, seller_id
),

primary_seller as (
    select order_id, seller_id as primary_seller_id
    from seller_share
    qualify row_number() over (partition by order_id order by seller_price desc, seller_id) = 1
),

category_share as (
    select order_id, category, sum(price_brl) as category_price
    from items group by order_id, category
),

primary_category as (
    select order_id, category as primary_category
    from category_share
    qualify row_number() over (partition by order_id order by category_price desc, category) = 1
)

select
    i.order_id,
    count(*)                         as n_items,
    count(distinct i.product_id)     as n_products,
    count(distinct i.seller_id)      as n_sellers,
    sum(i.price_brl)                 as items_price_brl,
    sum(i.freight_brl)               as freight_brl,
    sum(i.price_brl + i.freight_brl) as items_total_brl,
    max(i.shipping_limit_at)         as shipping_limit_at,
    any_value(ps.primary_seller_id)  as primary_seller_id,
    any_value(pc.primary_category)   as primary_category
from items as i
left join primary_seller as ps using (order_id)
left join primary_category as pc using (order_id)
group by i.order_id
