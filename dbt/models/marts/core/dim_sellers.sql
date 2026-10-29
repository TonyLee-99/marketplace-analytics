with items as (
    select * from {{ ref('fct_order_items') }} where is_revenue_order
),

agg as (
    select
        seller_id,
        count(distinct order_id)   as n_orders,
        count(*)                   as n_items,
        sum(price_brl)             as gmv_brl,
        sum(freight_brl)           as freight_brl,
        min(purchased_at)          as first_sale_at,
        max(purchased_at)          as last_sale_at,
        count(distinct category)   as n_categories
    from items
    group by seller_id
)

select
    s.seller_id,
    s.seller_zip_prefix,
    s.seller_city,
    s.seller_state,
    st.region                  as seller_region,
    g.lat                      as seller_lat,
    g.lng                      as seller_lng,
    coalesce(a.n_orders, 0)    as n_orders,
    coalesce(a.n_items, 0)     as n_items,
    coalesce(a.gmv_brl, 0)     as gmv_brl,
    coalesce(a.freight_brl, 0) as freight_brl,
    a.first_sale_at,
    a.last_sale_at,
    a.n_categories,
    d.won_at                   as acquired_via_funnel_at,
    d.business_segment         as funnel_business_segment,
    m.origin                   as funnel_lead_origin,
    d.mql_id is not null       as is_from_marketing_funnel
from {{ ref('stg_olist__sellers') }} as s
left join agg as a using (seller_id)
left join {{ ref('br_states') }} as st on s.seller_state = st.state_code
left join {{ ref('int_zip_geolocation') }} as g on s.seller_zip_prefix = g.zip_prefix
left join {{ ref('stg_olist__closed_deals') }} as d using (seller_id)
left join {{ ref('stg_olist__mqls') }} as m on d.mql_id = m.mql_id
