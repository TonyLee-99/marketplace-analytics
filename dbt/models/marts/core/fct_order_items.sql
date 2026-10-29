-- Grain: one row per order item line.
-- Columns prefixed order_ are ORDER-level attributes repeated on every item line: they are
-- for slicing only and must not be averaged at this grain (an item-weighted average review
-- differs from the order-level one). item_lane uses the item's own seller, so it can differ
-- from fct_orders.lane (primary seller) on multi-seller orders.
select
    i.order_item_key,
    i.order_id,
    i.order_item_id,
    i.product_id,
    i.seller_id,
    o.customer_unique_id,
    o.order_status,
    o.is_revenue_order,
    o.purchased_at,
    o.purchase_date,
    o.purchase_month,
    p.category,
    s.seller_state,
    o.customer_state,
    s.seller_state || '>' || o.customer_state as item_lane,
    i.shipping_limit_at,
    i.price_brl,
    i.freight_brl,
    i.price_brl + i.freight_brl as item_total_brl,
    o.is_delivered as order_is_delivered,
    o.is_late      as order_is_late,
    o.days_late    as order_days_late,
    o.review_score as order_review_score
from {{ ref('stg_olist__order_items') }} as i
join {{ ref('fct_orders') }} as o using (order_id)
left join {{ ref('stg_olist__products') }} as p using (product_id)
left join {{ ref('stg_olist__sellers') }} as s using (seller_id)
