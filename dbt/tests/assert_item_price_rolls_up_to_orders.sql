-- Grain test: item facts roll up exactly to the order fact, order by order.
with i as (select order_id, sum(price_brl) v, count(*) n from {{ ref('fct_order_items') }} group by 1)
select o.order_id, o.items_price_brl, i.v, o.n_items, i.n
from {{ ref('fct_orders') }} o join i using (order_id)
where o.items_price_brl <> i.v or o.n_items <> i.n
