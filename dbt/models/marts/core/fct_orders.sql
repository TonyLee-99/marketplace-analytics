-- Grain: one row per order. Measures in BRL. See _core.yml for column docs.
select
    o.order_id,
    o.customer_id,
    o.customer_unique_id,
    o.order_status,
    o.is_revenue_order,
    o.purchased_at,
    o.purchase_date,
    cast(date_trunc('month', o.purchase_date) as date) as purchase_month,
    o.approved_at,
    o.delivered_to_carrier_at,
    o.delivered_to_customer_at,
    o.estimated_delivery_date,
    o.customer_zip_prefix,
    o.customer_state,
    cr.region                       as customer_region,
    o.primary_seller_id,
    o.primary_seller_state,
    sr.region                       as primary_seller_region,
    o.primary_seller_state || '>' || o.customer_state as lane,
    o.primary_category,
    o.n_items,
    o.n_sellers,
    o.items_price_brl,
    o.freight_brl,
    o.items_total_brl,
    o.payment_total_brl,
    o.n_payments,
    o.max_installments,
    o.primary_payment_type,
    o.used_voucher,
    o.review_score,
    o.review_sent_at,
    o.review_answered_at,
    -- Olist sends the survey ~2 days after the PROMISED date even if the parcel has not
    -- arrived, so for late orders most reviews are written before delivery.
    case when o.review_score is not null then
        o.delivered_to_customer_at is null or o.review_answered_at < o.delivered_to_customer_at
    end                                                    as is_review_before_delivery,
    o.shipping_limit_at,
    case when o.delivered_to_carrier_at is not null then
        o.delivered_to_carrier_at > o.shipping_limit_at
    end                                                    as is_late_handover,
    case
        when o.delivered_to_carrier_at is null then 'not_handed_over'
        when o.delivered_to_carrier_at > o.shipping_limit_at then 'seller_late_handover'
        else 'seller_on_time_handover'
    end                                                    as fulfilment_leg,
    o.has_review_text,
    o.n_reviews_for_order,
    o.seller_customer_km,
    o.is_delivered,
    o.promised_days,
    o.delivery_days,
    o.approval_days,
    o.handling_days,
    o.carrier_transit_days,
    o.days_late,
    o.is_late,
    o.promise_padding_days,
    o.customer_order_number,
    o.customer_purchase_day_number,
    o.customer_order_number = 1 as is_first_order
from {{ ref('int_orders_enriched') }} as o
left join {{ ref('br_states') }} as cr on o.customer_state = cr.state_code
left join {{ ref('br_states') }} as sr on o.primary_seller_state = sr.state_code
