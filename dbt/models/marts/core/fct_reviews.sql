-- Grain: one row per order (latest review). Used by the voice-of-customer analysis.
select
    r.review_key,
    r.review_id,
    r.order_id,
    r.review_score,
    r.review_title,
    r.review_message,
    r.review_sent_at,
    r.review_answered_at,
    r.n_reviews_for_order,
    o.primary_seller_id,
    o.lane,
    o.primary_category,
    o.customer_state,
    o.is_delivered,
    o.is_late,
    o.days_late,
    o.purchase_month,
    o.is_review_before_delivery
from {{ ref('int_reviews_latest_per_order') }} as r
join {{ ref('fct_orders') }} as o using (order_id)
