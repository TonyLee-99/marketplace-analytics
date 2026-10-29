-- Grain: one row per payment instrument per order.
select
    p.payment_key,
    p.order_id,
    p.payment_sequential,
    p.payment_type,
    p.payment_installments,
    p.payment_value_brl,
    o.purchase_date,
    o.purchase_month,
    o.customer_unique_id,
    o.is_revenue_order
from {{ ref('stg_olist__payments') }} as p
join {{ ref('fct_orders') }} as o using (order_id)
