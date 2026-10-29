-- Grain: one row per PERSON (customer_unique_id). Olist's customer_id is order-scoped:
-- 99,441 customer_ids map to 96,096 people. Using customer_id would make every customer
-- look like a one-time buyer.
with orders as (
    select * from {{ ref('fct_orders') }}
),

agg as (
    select
        customer_unique_id,
        count(*)                                              as n_orders_all_status,
        count(*) filter (where is_revenue_order)              as n_revenue_orders,
        min(purchased_at) filter (where is_revenue_order)     as first_purchase_at,
        max(purchased_at) filter (where is_revenue_order)     as last_purchase_at,
        coalesce(sum(items_price_brl) filter (where is_revenue_order), 0) as lifetime_gmv_brl
    from orders
    group by customer_unique_id
),

current_location as (
    select * from {{ ref('int_customer_location_history') }} where is_current
),

loc_versions as (
    select customer_unique_id, count(*) as n_address_versions
    from {{ ref('int_customer_location_history') }} group by 1
)

select
    a.customer_unique_id,
    l.customer_zip_prefix  as current_zip_prefix,
    l.customer_city        as current_city,
    l.customer_state       as current_state,
    s.region               as current_region,
    v.n_address_versions,
    a.n_orders_all_status,
    a.n_revenue_orders,
    a.first_purchase_at,
    a.last_purchase_at,
    cast(date_trunc('month', a.first_purchase_at) as date) as cohort_month,
    a.lifetime_gmv_brl,
    a.n_revenue_orders >= 2 as is_repeat_customer
from agg as a
left join current_location as l using (customer_unique_id)
left join loc_versions as v using (customer_unique_id)
left join {{ ref('br_states') }} as s on l.customer_state = s.state_code
