-- The workhorse: one row per order with customer, items, payments, review, logistics.
with orders as (select * from {{ ref('stg_olist__orders') }}),
customers as (select * from {{ ref('stg_olist__customers') }}),
items as (select * from {{ ref('int_order_items_by_order') }}),
payments as (select * from {{ ref('int_payments_by_order') }}),
reviews as (select * from {{ ref('int_reviews_latest_per_order') }}),
sellers as (select * from {{ ref('stg_olist__sellers') }}),
geo as (select * from {{ ref('int_zip_geolocation') }}),

base as (
    select
        o.order_id,
        o.customer_id,
        c.customer_unique_id,
        c.customer_zip_prefix,
        c.customer_city,
        c.customer_state,
        o.order_status,
        o.order_status not in (
            {%- for s in var('non_revenue_statuses') %}'{{ s }}'{{ "," if not loop.last }}{% endfor -%}
        ) and i.order_id is not null                          as is_revenue_order,
        o.purchased_at,
        cast(o.purchased_at as date)                          as purchase_date,
        o.approved_at,
        o.delivered_to_carrier_at,
        o.delivered_to_customer_at,
        o.estimated_delivery_date,

        coalesce(i.n_items, 0)                                as n_items,
        coalesce(i.n_sellers, 0)                              as n_sellers,
        coalesce(i.items_price_brl, 0)                        as items_price_brl,
        coalesce(i.freight_brl, 0)                            as freight_brl,
        coalesce(i.items_total_brl, 0)                        as items_total_brl,
        i.shipping_limit_at,
        i.primary_seller_id,
        coalesce(i.primary_category, 'no_items')              as primary_category,
        s.seller_state                                        as primary_seller_state,

        p.payment_total_brl,
        p.n_payments,
        p.max_installments,
        p.primary_payment_type,
        p.used_voucher,

        r.review_score,
        r.review_message is not null                          as has_review_text,
        r.n_reviews_for_order,
        r.review_sent_at,
        r.review_answered_at,

        {{ haversine_km('sg.lat', 'sg.lng', 'cg.lat', 'cg.lng') }} as seller_customer_km,

        -- Logistics (only meaningful for delivered orders)
        o.order_status = 'delivered' and o.delivered_to_customer_at is not null as is_delivered,
        {{ day_diff('o.purchased_at', 'o.estimated_delivery_date') }}            as promised_days,
        {{ frac_days('o.purchased_at', 'o.delivered_to_customer_at') }}          as delivery_days,
        {{ frac_days('o.purchased_at', 'o.approved_at') }}                       as approval_days,
        {{ frac_days('o.approved_at', 'o.delivered_to_carrier_at') }}            as handling_days,
        {{ frac_days('o.delivered_to_carrier_at', 'o.delivered_to_customer_at') }} as carrier_transit_days,
        {{ day_diff('o.estimated_delivery_date', 'o.delivered_to_customer_at') }} as days_late
    from orders as o
    left join customers as c using (customer_id)
    left join items as i using (order_id)
    left join payments as p using (order_id)
    left join reviews as r using (order_id)
    left join sellers as s on i.primary_seller_id = s.seller_id
    left join geo as sg on s.seller_zip_prefix = sg.zip_prefix
    left join geo as cg on c.customer_zip_prefix = cg.zip_prefix
)

select
    *,
    case when is_delivered then days_late > 0 end                     as is_late,
    case when is_delivered then -days_late end                        as promise_padding_days,
    -- Customer's n-th revenue order (person-level, via customer_unique_id)
    case when is_revenue_order then
        row_number() over (
            partition by customer_unique_id, is_revenue_order
            order by purchased_at, order_id
        )
    end                                                               as customer_order_number,
    -- n-th distinct purchase DAY of the person (same-day split baskets share a number).
    -- Governed repeat definition: a returning customer has customer_purchase_day_number >= 2.
    case when is_revenue_order then
        dense_rank() over (
            partition by customer_unique_id, is_revenue_order
            order by purchase_date
        )
    end                                                               as customer_purchase_day_number
from base
