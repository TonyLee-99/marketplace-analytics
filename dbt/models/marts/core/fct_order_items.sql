-- Grain: one row per order item line. Carries order context for slicing.
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
    s.seller_state || '>' || o.customer_state as lane,
    i.shipping_limit_at,
    i.price_brl,
    i.freight_brl,
    i.price_brl + i.freight_brl as item_total_brl,
    o.is_delivered,
    o.is_late,
    o.days_late,
    o.review_score
from {{ ref('stg_olist__order_items') }} as i
join {{ ref('fct_orders') }} as o using (order_id)
left join {{ ref('stg_olist__products') }} as p using (product_id)
left join {{ ref('stg_olist__sellers') }} as s using (seller_id)
